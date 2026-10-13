"""文件说明：按知识侧操作回执收尾中断任务；没有确切结果时保留原阶段待核查。"""

import json
from sqlalchemy import select, text, func, or_

from app.application.task_lease import claim, LeaseExecution
from app.application.ingestion_service import IngestionService
from app.infrastructure.db.models import IngestionJob, IngestionArtifact
from knowledge.storage import repository


def recover_completed_ingestion(factory, paths, *, job_id=None):
    states = {"PARSING": ("PARSE_QUEUED", "PARSE_REVIEW", "PARSE_RUN", "parse_run_id"),
              "CHUNKING": ("CHUNK_QUEUED", "CHUNK_REVIEW", "CHUNK_RUN", "chunk_run_id")}
    with factory() as session:
        rows = list(session.scalars(select(IngestionJob).where(
            IngestionJob.state.in_(states), IngestionJob.id == job_id if job_id else True,
            or_(IngestionJob.lease_expires_at.is_(None),
                IngestionJob.lease_expires_at <= func.clock_timestamp())
        ).order_by(IngestionJob.created_at).limit(20)))
    recovered = 0
    for row in rows:
        queued, target, run_type, field = states[row.state]
        with repository.engine_for(paths.database_url).connect() as connection:
            receipt = connection.execute(text("SELECT generation,result_json FROM worker_operation WHERE operation_key=:key"),
                                         {"key": f"ingestion:{row.id}:{queued}"}).mappings().first()
        # 收尾自身中断会递增Platform租约代次，但不会产生新的知识运行。
        # 新执行阶段会先覆盖知识代次并清空回执，因此可重用较早的完成回执。
        if not receipt or receipt["generation"] > row.lease_generation or not receipt["result_json"]:
            continue
        result = json.loads(receipt["result_json"])
        table = "parse_run" if run_type == "PARSE_RUN" else "chunk_run"
        with repository.engine_for(paths.database_url).connect() as connection:
            actual = connection.execute(text(f"SELECT document_id,status FROM {table} WHERE id=:id"),
                                        {"id": int(result["id"])}).mappings().first()
        if not actual or actual["status"] not in {"succeeded", "review_required", "failed"} or actual["document_id"] != int(result["document_id"]):
            continue
        with factory() as session:
            token = claim(session, IngestionJob, key_name="id", owner="receipt-recovery",
                          eligible=[IngestionJob.id == row.id, IngestionJob.state == row.state,
                                    IngestionJob.lease_generation == row.lease_generation],
                          order_by=IngestionJob.created_at)
        if token is None:
            continue
        with LeaseExecution(factory, token) as execution, factory() as session, execution.guard_session(session):
            job = session.get(IngestionJob, row.id)
            job.document_id = int(result["document_id"])
            setattr(job, field, int(result["id"]))
            recovered_target = target
            if actual["status"] == "failed":
                recovered_target = "FAILED"
                job.failed_stage = row.state
                job.error_code = str(result.get("error_code") or "KNOWLEDGE_RUN_FAILED")
                job.error_summary = str(result.get("error_message") or "知识运行失败，按回执恢复")[:1000]
                job.retryable = run_type == "PARSE_RUN" and job.error_code == "PIPELINE_EXCEPTION"
            for kind, path_key, checksum_key in (("ACCEPTED_DOCX", "accepted_docx_path", "accepted_checksum"),
                                                 ("REVIEW_PDF", "pdf_path", "pdf_checksum")):
                relative = result.get(path_key)
                if relative and session.scalar(select(IngestionArtifact.id).where(
                        IngestionArtifact.job_id == job.id, IngestionArtifact.artifact_type == kind,
                        IngestionArtifact.relative_path == relative)) is None:
                    session.add(IngestionArtifact(job_id=job.id, artifact_type=kind,
                                                 relative_path=relative, sha256=result.get(checksum_key)))
            IngestionService(session, paths).transition(job, recovered_target, "按知识操作完成回执恢复任务状态",
                                                       run_type=run_type, run_id=int(result["id"]))
            recovered += 1
    return recovered


def pending_ingestion_recovery(session):
    """诊断缺少回执的中断阶段，不把租约过期等同于运行失败。"""
    rows = session.scalars(select(IngestionJob).where(
        IngestionJob.state.in_(["PREFLIGHTING", "PARSING", "CHUNKING"]),
        or_(IngestionJob.lease_expires_at.is_(None), IngestionJob.lease_expires_at <= func.clock_timestamp()),
    ).order_by(IngestionJob.created_at).limit(50))
    return [{"id": row.id, "state": row.state, "document_id": row.document_id,
             "parse_run_id": row.parse_run_id, "chunk_run_id": row.chunk_run_id} for row in rows]


def mark_interrupted_ingestion(factory, paths, job_id, *, executor_stopped=False):
    """明确确认旧执行结束后登记无完成回执的中断；人工重试沿用业务状态机。"""
    if not executor_stopped:
        raise ValueError("必须确认旧执行者及外部调用已经结束")
    # 优先兑现已完成回执，避免把已经成功的运行误标失败。
    recover_completed_ingestion(factory, paths, job_id=job_id)
    with factory() as session:
        token = claim(session, IngestionJob, key_name="id", owner="admin-ingestion-recovery",
                      eligible=[IngestionJob.id == job_id, IngestionJob.state.in_(["PREFLIGHTING", "PARSING", "CHUNKING"])],
                      order_by=IngestionJob.created_at)
    if token is None:
        raise ValueError("任务已收尾、仍有有效租约或不在可核查阶段")
    with LeaseExecution(factory, token) as execution, factory() as session, execution.guard_session(session):
        job = session.get(IngestionJob, job_id)
        job.failed_stage = job.state
        job.retryable = job.state in {"PREFLIGHTING", "PARSING"}
        job.error_code = "WORKER_INTERRUPTED"
        job.error_summary = "管理员已确认旧执行者停止；解析可人工重试，分块须核查未完成ChunkRun后返工"
        IngestionService(session, paths).transition(job, "FAILED", job.error_summary)
