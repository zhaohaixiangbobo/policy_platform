"""文件说明：单进程轻量自测Worker；显式领取、有限生成、CAS发布结果和过期清理。"""

from app.worker_control import WorkerControl
from app.infrastructure.db.worker_mutex import worker_mutex

import argparse
import json
import logging
import os
from contextlib import ExitStack
from datetime import timedelta

from sqlalchemy import select, update, and_

from app.application.learning_service import clean_slot, encode, aware
from app.application.task_lease import claim, LeaseExecution, LeaseLostError
from app.config import get_settings, PROJECT_ROOT
from app.infrastructure.db.models import LearningAssessmentSlot as Slot, utc_now
from app.infrastructure.db.session import get_session_factory
from app.logging_config import configure_rotating_logger
from knowledge.learning_generator import generate_assessment, model_client, LearningContentError, PROMPT_VERSION
from knowledge.rag.generator import GeneratorError, GeneratorTransportError
from knowledge.learning_generator import transport_failure

LOGGER = logging.getLogger("policy_platform.learning")


def run_once(factory=None, settings=None, client_factory=model_client):
    with ExitStack() as stack:
        return _run_once(stack, factory, settings, client_factory)


def _run_once(stack, factory=None, settings=None, client_factory=model_client):
    settings = settings or get_settings()
    if not settings.learning_assessment_enabled:
        return False
    factory = factory or get_session_factory()
    # 每次只清理有限个到期槽位，不扫描整个用户库，不保留隐性历史。
    now = utc_now()
    with factory() as session:
        stale = session.scalars(select(Slot).where(
            (Slot.expires_at <= now)
            | and_(Slot.task_state == "GENERATING", Slot.task_created_at <= now - timedelta(seconds=settings.learning_assessment_task_timeout_seconds))
            | (Slot.task_created_at <= now - timedelta(hours=24))
        ).limit(100).with_for_update(skip_locked=True)).all()
        for row in stale:
            clean_slot(row, settings.learning_assessment_task_timeout_seconds)
            if (not row.current_json and row.task_state != "GENERATING" and row.task_created_at
                    and aware(row.task_created_at) <= now - timedelta(hours=24)):
                session.delete(row)
        session.commit()
        token = claim(session, Slot, key_name="user_id", owner=f"learning-{os.getpid()}",
                      eligible=[Slot.task_state == "GENERATING"], order_by=Slot.task_created_at)
        if token is None:
            return False
        execution = stack.enter_context(LeaseExecution(factory, token))
        row = session.get(Slot, token.key)
        task_id, payload = row.task_id, json.loads(row.pending_json)
        execution.check(session)
        claimed = session.execute(update(Slot).where(*token.conditions(), Slot.task_id == task_id, Slot.task_state == "GENERATING").values(
            claimed_at=now, progress="开始按条款取材", version=Slot.version + 1))
        session.commit()
        if claimed.rowcount != 1:
            return False

    def progress(message):
        with factory() as session:
            execution.check(session)
            changed = session.execute(update(Slot).where(*token.conditions(), Slot.task_id == task_id, Slot.task_state == "GENERATING",
                                                         Slot.task_created_at > utc_now() - timedelta(seconds=settings.learning_assessment_task_timeout_seconds)).values(
                progress=message, version=Slot.version + 1))
            session.commit()
            if changed.rowcount != 1:
                raise ValueError("任务已过期或被替换")
        LOGGER.info(
            "event=learning_progress task_id=%s progress=%s", task_id, message)

    LOGGER.info("event=learning_started task_id=%s prompt=%s",
                task_id, PROMPT_VERSION)
    try:
        with client_factory() as client:
            client.learning_task_id = task_id
            questions = generate_assessment(
                payload["source"], payload["counts"], client, progress)
        ready = utc_now()
        expires = ready + \
            timedelta(hours=settings.learning_assessment_ttl_hours)
        source = {key: value for key,
                  value in payload["source"].items() if key != "units"}
        data = {**source, "assessment_id": task_id, "status": "READY", "questions": questions,
                "user_answers": {}, "created_at": now.isoformat(), "ready_at": ready.isoformat(),
                "expires_at": expires.isoformat(), "counts": payload["counts"]}
        with factory() as session:
            execution.check(session)
            result = session.execute(update(Slot).where(*token.conditions(), Slot.task_id == task_id, Slot.task_state == "GENERATING",
                                                        Slot.task_created_at > ready - timedelta(seconds=settings.learning_assessment_task_timeout_seconds)).values(
                current_id=task_id, current_json=encode(data), expires_at=expires,
                task_state="READY", pending_json=None, progress="题目已生成", error_message=None, version=Slot.version + 1))
            session.commit()
        LOGGER.info("event=learning_completed task_id=%s published=%s",
                    task_id, result.rowcount == 1)
    except LeaseLostError:
        LOGGER.warning("event=learning_result_abandoned task_id=%s generation=%s", task_id, token.generation)
    except Exception as exc:
        # 只记录类型和任务ID，避免模型错误响应携带原文或答案进入日志。
        LOGGER.warning(
            "event=learning_failed task_id=%s error_type=%s", task_id, type(exc).__name__)
        # 区分传输/服务类错误与内容不达标：前者提示服务问题；后者用生成器给出的具体原因
        # （如“仅有9/10道题通过校验”），消息不含模型输出，可以直接展示。
        if isinstance(exc, GeneratorTransportError):
            kind, _, _ = transport_failure(exc)
            message = {
                "timeout": "模型响应超时，有限重试后仍未完成，请稍后重试",
                "connection": "模型服务连接失败，有限重试后仍未恢复，请稍后重试",
                "busy": "模型服务繁忙，有限重试后仍受限，请稍后重试",
                "unavailable": "模型服务暂时不可用，有限重试后仍未恢复，请稍后重试",
                "response": "模型服务响应异常，请稍后重试",
            }[kind] + "；原检测保留"
        elif isinstance(exc, GeneratorError):
            message = "模型服务响应不符合约定，请联系管理员检查服务配置；原检测保留"
        elif isinstance(exc, LearningContentError):
            message = f"{exc}；原检测保留"
        else:
            message = "题目生成或校验未通过，请减少题量、扩大范围或稍后重试；原检测保留"
        with factory() as session:
            session.execute(update(Slot).where(*token.conditions(), Slot.task_id == task_id, Slot.task_state == "GENERATING").values(
                task_state="FAILED", pending_json=None, progress="生成失败", error_message=message, version=Slot.version + 1))
            session.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    from app.infrastructure.db.readiness import check_readiness
    check_readiness()
    settings = get_settings()
    if not settings.learning_assessment_enabled:
        print("学习检测未启用，Worker退出")
        return 0
    configure_rotating_logger("policy_platform.learning", level_name="INFO",
                              log_file=os.getenv("PLATFORM_LEARNING_LOG_FILE", str(PROJECT_ROOT / "logs/learning.log")), max_bytes=10485760, backup_count=3)
    with worker_mutex("learning"), WorkerControl("learning") as control:
        while not control.is_set():
            try:
                worked = run_once()
            except Exception as exc:
                LOGGER.warning(
                    "event=learning_poll_failed error_type=%s", type(exc).__name__)
                worked = False
            if args.once:
                return 0
            if not worked:
                control.wait(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
