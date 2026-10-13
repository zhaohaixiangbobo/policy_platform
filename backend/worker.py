"""文件说明：第二期本机单Worker入口，串行推进预检、解析、分块、索引和发布。"""

from __future__ import annotations

from app.worker_control import WorkerControl
from app.infrastructure.db.worker_mutex import worker_mutex

import argparse
import json
import logging
import os
import time
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.application.ingestion_service import IngestionService
from app.application.task_lease import claim, LeaseExecution, LeaseLostError
from app.application.publication_recovery import finish_publication, pending_recovery
from app.application.ingestion_recovery import recover_completed_ingestion
from app.application.publication_service import PublicationService
from app.config import get_settings
from app.logging_config import configure_rotating_logger
from app.infrastructure.db.models import IndexPublicationRequest, IngestionArtifact, IngestionJob, MetadataChangeRequest, utc_now
from app.infrastructure.db.session import get_session_factory
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.storage.repository import engine_for
from knowledge.storage.execution import knowledge_execution


WORKER_STATES = ("UPLOADED", "PARSE_QUEUED", "CHUNK_QUEUED")
LOGGER = logging.getLogger("policy_platform.worker")


def configure_logging() -> None:
    """使用标准库输出控制台和滚动文件日志，空闲轮询保持安静。"""

    configure_rotating_logger(
        "policy_platform.worker",
        level_name=os.getenv("PLATFORM_WORKER_LOG_LEVEL", "INFO"),
        log_file=os.getenv(
            "PLATFORM_WORKER_LOG_FILE",
            str(Path(__file__).resolve().parents[1] / "logs" / "worker.log"),
        ),
        max_bytes=int(os.getenv("PLATFORM_WORKER_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        backup_count=int(os.getenv("PLATFORM_WORKER_LOG_BACKUP_COUNT", "5")),
    )


class KnowledgeRunFailedError(RuntimeError):
    """知识流水线已落库失败结果，Worker 必须据此终止当前阶段。"""

    def __init__(self, run_type: str, result: dict[str, object]) -> None:
        self.run_type = run_type
        self.run_id = int(result["id"])
        self.error_code = str(result.get("error_code") or f"{run_type}_VALIDATION_FAILED")
        # ParseRun 的内部异常可通过新建运行重试；校验失败和已固化的 ChunkRun 需先修正来源或配置。
        self.retryable = run_type == "PARSE_RUN" and self.error_code == "PIPELINE_EXCEPTION"
        detail = str(result.get("error_message") or "运行结果为 failed")
        super().__init__(f"{run_type} {self.run_id} 失败：{detail}")


def ensure_knowledge_run_succeeded(run_type: str, result: dict[str, object]) -> None:
    """阻止 Worker 把知识库返回的失败运行推进到人工审核阶段。"""

    if str(result.get("status") or "").lower() == "failed":
        raise KnowledgeRunFailedError(run_type, result)
    if result.get("status") not in {"succeeded", "review_required"}:
        raise KnowledgeRunFailedError(run_type, {**result, "error_code": "INCOMPLETE_KNOWLEDGE_RUN",
                                                "error_message": "知识运行尚未完成，请核查中断运行，禁止进入人工审核"})


def record_artifact(session, job_id: str, artifact_type: str, relative_path: str | None, checksum: str | None) -> None:
    """幂等登记知识运行生成的受控文件，不在Platform保存绝对路径。"""

    if not relative_path:
        return
    exists = session.scalar(select(IngestionArtifact).where(IngestionArtifact.job_id == job_id, IngestionArtifact.artifact_type == artifact_type, IngestionArtifact.relative_path == relative_path))
    if exists is None:
        session.add(IngestionArtifact(job_id=job_id, artifact_type=artifact_type, relative_path=relative_path, sha256=checksum))


def run_once(worker_id: str) -> bool:
    """领取并推进一个任务阶段；返回本轮是否处理到任务。"""

    settings = get_settings()
    paths = KnowledgePaths(settings.knowledge_data_root)
    management = KnowledgeManagementService(
        paths,
        progress=lambda message: LOGGER.info("event=knowledge_progress message=%s", message),
    )
    factory = get_session_factory()
    if recover_completed_ingestion(factory, paths):
        return True
    with ExitStack() as stack, factory() as session:
        token = claim(session, IndexPublicationRequest, key_name="id", owner=worker_id,
                      eligible=[IndexPublicationRequest.status.in_(["BUILD_QUEUED", "PUBLISH_QUEUED"])],
                      order_by=IndexPublicationRequest.created_at)
        if token is not None:
            execution = stack.enter_context(LeaseExecution(factory, token))
            stack.enter_context(execution.guard_session(session))
            stack.enter_context(knowledge_execution(engine_for(paths.database_url),
                                f"publication:{token.key}", token.generation, execution.check))
            publication = session.get(IndexPublicationRequest, token.key)
            LOGGER.info(
                "event=publication_claimed worker_id=%s publication_id=%s status=%s",
                worker_id, publication.id, publication.status,
            )
            return run_publication(session, publication, management, paths, execution=execution)
        token = claim(session, IngestionJob, key_name="id", owner=worker_id,
                      eligible=[IngestionJob.state.in_(WORKER_STATES)], order_by=IngestionJob.created_at)
        if token is None:
            return False
        execution = stack.enter_context(LeaseExecution(factory, token))
        stack.enter_context(execution.guard_session(session))
        job = session.get(IngestionJob, token.key)
        operation = stack.enter_context(knowledge_execution(engine_for(paths.database_url),
                                        f"ingestion:{token.key}:{job.state}", token.generation, execution.check))
        ingestion = IngestionService(session, paths)
        session.commit()
        started = time.perf_counter()
        LOGGER.info(
            "event=job_claimed worker_id=%s job_id=%s document_id=%s state=%s attempt=%s",
            worker_id, job.id, job.document_id, job.state, job.attempt_no,
        )
        try:
            result = None
            if job.state == "UPLOADED":
                ingestion.transition(job, "PREFLIGHTING", "单Worker开始异步预检")
                source = (paths.data_root / job.stored_path).resolve()
                if not source.is_relative_to(paths.pending_documents.resolve()) or not source.is_file():
                    raise FileNotFoundError("受控pending源文件不存在")
                ingestion.transition(job, "PARSE_QUEUED", "异步预检通过")
            elif job.state == "PARSE_QUEUED":
                ingestion.transition(job, "PARSING", "单Worker开始ParseRun")
                source = (paths.data_root / job.stored_path).resolve()
                result = management.parse_pending_document(source)
                execution.check()
                operation.complete(result)
                job.document_id = int(result["document_id"])
                job.parse_run_id = int(result["id"])
                record_artifact(session, job.id, "ACCEPTED_DOCX", result.get("accepted_docx_path"), result.get("accepted_checksum"))
                record_artifact(session, job.id, "REVIEW_PDF", result.get("pdf_path"), result.get("pdf_checksum"))
                ensure_knowledge_run_succeeded("PARSE_RUN", result)
                ingestion.transition(job, "PARSE_REVIEW", "ParseRun已生成，等待人工审核", run_type="PARSE_RUN", run_id=job.parse_run_id)
            elif job.state == "CHUNK_QUEUED":
                if job.document_id is None:
                    raise ValueError("任务缺少Document ID")
                ingestion.transition(job, "CHUNKING", "单Worker开始ChunkRun")
                result = management.build_chunk_run(job.document_id)
                execution.check()
                operation.complete(result)
                job.chunk_run_id = int(result["id"])
                ensure_knowledge_run_succeeded("CHUNK_RUN", result)
                ingestion.transition(job, "CHUNK_REVIEW", "ChunkRun已生成，等待人工审核", run_type="CHUNK_RUN", run_id=job.chunk_run_id)
            session.commit()
            LOGGER.info(
                "event=job_stage_completed worker_id=%s job_id=%s document_id=%s state=%s "
                "parse_run_id=%s chunk_run_id=%s elapsed_ms=%d",
                worker_id, job.id, job.document_id, job.state, job.parse_run_id,
                job.chunk_run_id, int((time.perf_counter() - started) * 1000),
            )
        except (LeaseLostError, SQLAlchemyError):
            session.rollback()
            LOGGER.warning("event=job_result_abandoned job_id=%s generation=%s", token.key, token.generation)
        except Exception as exc:
            session.rollback()
            execution.check()
            session.refresh(job)
            failed_stage = job.state
            # rollback后重挂本次已持久化的知识运行，保留失败审核与诊断入口。
            if isinstance(exc, KnowledgeRunFailedError) and result:
                job.document_id = int(result["document_id"])
                if exc.run_type == "PARSE_RUN":
                    job.parse_run_id = exc.run_id
                else:
                    job.chunk_run_id = exc.run_id
            job.failed_stage = failed_stage
            if isinstance(exc, KnowledgeRunFailedError):
                job.retryable = exc.retryable
                job.error_code = exc.error_code
            else:
                # ChunkRun 失败记录具有版本唯一性，当前阶段不声明可原地重试。
                job.retryable = failed_stage in {"PARSING", "INDEXING", "PUBLISHING"}
                job.error_code = exc.__class__.__name__.upper()
            job.error_summary = str(exc)[:1000]
            ingestion.transition(job, "FAILED", f"{failed_stage}失败：{exc}")
            LOGGER.exception(
                "event=job_stage_failed worker_id=%s job_id=%s document_id=%s "
                "failed_stage=%s error_code=%s retryable=%s elapsed_ms=%d",
                worker_id, job.id, job.document_id, failed_stage, job.error_code,
                job.retryable, int((time.perf_counter() - started) * 1000),
            )
        return True


def run_publication(session, publication: IndexPublicationRequest, management: KnowledgeManagementService, paths: KnowledgePaths, *, execution=None) -> bool:
    """串行构建或发布一个全局索引快照；Alias成功是唯一正式发布时点。"""

    ingestion = IngestionService(session, paths)
    document_ids = [int(value) for value in json.loads(publication.source_document_ids_json)]
    publication_service = PublicationService(session, ingestion)
    bound_sources = []
    started = time.perf_counter()
    try:
        bound_sources = publication_service.bound_sources(publication.id)
        active_snapshot = management.active_index_snapshot()
        if active_snapshot["index_run_id"] != publication.base_index_run_id:
            raise RuntimeError(
                "发布基线已变化，请基于当前active IndexRun重新创建发布请求："
                f"expected={publication.base_index_run_id}, actual={active_snapshot['index_run_id']}"
            )
        if publication.status == "BUILD_QUEUED":
            invalid = [
                (job.id, job.state)
                for binding, job in bound_sources
                if binding.source_role == "CHANGE" and job is not None and job.state != "INDEX_QUEUED"
            ]
            if invalid:
                raise RuntimeError(f"发布请求绑定任务状态不一致：{invalid}")
            publication.status = "BUILDING"
            session.commit()
            for binding, job in bound_sources:
                if binding.source_role != "CHANGE" or job is None:
                    continue
                ingestion.transition(job, "INDEXING", f"开始构建索引发布请求 {publication.id}")
            LOGGER.info(
                "event=index_build_started publication_id=%s documents=%s bound_jobs=%d",
                publication.id, document_ids,
                sum(1 for _binding, job in bound_sources if job is not None),
            )
            frozen_manifest = [
                {
                    "document_id": int(binding.document_id),
                    "parse_run_id": int(binding.parse_run_id),
                    "chunk_run_id": int(binding.chunk_run_id),
                    "metadata_revision_id": int(binding.metadata_revision_id),
                }
                for binding, _job in bound_sources
            ]
            # 来源读取可能开启只读事务；外部Embedding/Qdrant调用前释放连接。
            session.commit()
            result = management.build_index_run(frozen_sources=frozen_manifest)
            if execution:
                execution.check()
            publication.index_run_id = int(result["index_run_id"])
            sources = {
                int(source["document_id"]): source
                for source in management.index_run_sources(publication.index_run_id)
            }
            expected_documents = {int(binding.document_id) for binding, _job in bound_sources}
            if set(sources) != expected_documents:
                raise RuntimeError(
                    "IndexRun来源集合与冻结全量快照不一致："
                    f"expected={sorted(expected_documents)}, actual={sorted(sources)}"
                )
            for binding, _job in bound_sources:
                source = sources.get(binding.document_id)
                expected = (
                    binding.parse_run_id,
                    binding.chunk_run_id,
                    binding.metadata_revision_id,
                )
                actual = (
                    int(source["parse_run_id"]),
                    int(source["chunk_run_id"]),
                    int(source["metadata_revision_id"]),
                ) if source else None
                if actual != expected:
                    raise RuntimeError(
                        f"制度 {binding.document_id} 的发布绑定与IndexRun来源不一致："
                        f"expected={expected}, actual={actual}"
                    )
                binding.index_run_id = publication.index_run_id
            publication.status = "READY_TO_PUBLISH"
            for binding, job in bound_sources:
                if binding.source_role != "CHANGE" or job is None:
                    continue
                job.index_run_id = publication.index_run_id
                ingestion.transition(
                    job, "READY_TO_PUBLISH", "全局IndexRun已完成核验",
                    run_type="INDEX_RUN", run_id=publication.index_run_id,
                )
            session.commit()
            LOGGER.info(
                "event=index_build_completed publication_id=%s index_run_id=%s reused=%s "
                "source_documents=%d elapsed_ms=%d",
                publication.id, publication.index_run_id, result.get("reused"),
                len(sources), int((time.perf_counter() - started) * 1000),
            )
            return True

        if not publication.published_by:
            raise ValueError("发布请求缺少管理员确认，禁止切换Alias")
        invalid = [
            (job.id, job.state)
            for binding, job in bound_sources
            if binding.source_role == "CHANGE" and job is not None and job.state != "READY_TO_PUBLISH"
        ]
        if invalid:
            raise RuntimeError(f"发布请求绑定任务状态不一致：{invalid}")
        publication.status = "PUBLISHING"
        session.commit()
        for binding, job in bound_sources:
            if binding.source_role != "CHANGE" or job is None:
                continue
            ingestion.transition(job, "PUBLISH_QUEUED", f"发布请求 {publication.id} 已获管理员确认")
            ingestion.transition(job, "PUBLISHING", "开始原子切换Platform Qdrant Alias")
        if publication.index_run_id is None:
            raise ValueError("发布请求缺少IndexRun ID")
        LOGGER.info(
            "event=alias_switch_started publication_id=%s index_run_id=%s alias=%s",
            publication.id, publication.index_run_id, publication.alias_name,
        )
        session.commit()
        if execution:
            execution.check()
        management.publish_index_run(publication.index_run_id)
        if execution:
            execution.check()
        # Alias/Knowledge成功后以单个Platform事务收尾，异常保留PUBLISHING供对账。
        finish_publication(session, publication, bound_sources)
        LOGGER.info(
            "event=alias_switch_completed publication_id=%s index_run_id=%s elapsed_ms=%d",
            publication.id, publication.index_run_id,
            int((time.perf_counter() - started) * 1000),
        )
        return True
    except LeaseLostError:
        session.rollback()
        LOGGER.warning("event=publication_result_abandoned publication_id=%s", publication.id)
        return True
    except Exception as exc:
        session.rollback()
        if execution:
            execution.check()
        session.refresh(publication)
        failed_stage = publication.status
        if isinstance(exc, SQLAlchemyError) and failed_stage in {"BUILDING", "READY_TO_PUBLISH", "PUBLISHING", "PUBLISHED"}:
            LOGGER.exception("event=publication_commit_uncertain publication_id=%s status=%s", publication.id, failed_stage)
            session.rollback()
            return True
        if failed_stage == "PUBLISHING":
            publication.error_summary = f"发布结果待核查：{type(exc).__name__}"[:2000]
            session.commit()
            LOGGER.exception("event=publication_recovery_required publication_id=%s", publication.id)
            return True
        publication.status = "FAILED"
        publication.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
        for binding, job in bound_sources:
            if binding.source_role != "CHANGE" or job is None:
                continue
            if job.state in {"INDEXING", "PUBLISHING"}:
                job.failed_stage = job.state
                job.retryable = True
                job.error_code = exc.__class__.__name__.upper()
                job.error_summary = str(exc)[:1000]
                ingestion.transition(job, "FAILED", f"{failed_stage}失败：{exc}")
        session.commit()
        LOGGER.exception(
            "event=publication_failed publication_id=%s failed_stage=%s error_code=%s elapsed_ms=%d",
            publication.id, failed_stage, exc.__class__.__name__.upper(),
            int((time.perf_counter() - started) * 1000),
        )
        return True


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="制度知识平台单Worker")
    parser.add_argument("--once", action="store_true", help="只推进一个任务阶段后退出")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    from app.infrastructure.db.readiness import check_readiness
    check_readiness()
    with worker_mutex("ingestion"), WorkerControl("ingestion") as control:
        with get_session_factory()() as session:
            for item in pending_recovery(session):
                LOGGER.warning("event=publication_recovery_scan publication_id=%s status=%s index_run_id=%s",
                               item["id"], item["status"], item["index_run_id"])
        worker_id = f"local-worker-{os.getpid()}"
        LOGGER.info(
            "event=worker_started worker_id=%s once=%s poll_seconds=%s",
            worker_id, args.once, args.poll_seconds,
        )
        while not control.is_set():
            try:
                worked = run_once(worker_id)
            except (SQLAlchemyError, LeaseLostError) as exc:
                LOGGER.warning("event=worker_poll_deferred error_type=%s", type(exc).__name__)
                worked = False
            if args.once:
                return 0
            if not worked:
                control.wait(max(args.poll_seconds, 0.5))
        LOGGER.info("event=worker_stopped worker_id=%s", worker_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
