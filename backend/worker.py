"""文件说明：第二期本机单Worker入口，串行推进预检、解析、分块、索引和发布。"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.application.ingestion_service import IngestionService
from app.config import get_settings
from app.infrastructure.db.models import IndexPublicationRequest, IngestionArtifact, IngestionJob, MetadataChangeRequest, utc_now
from app.infrastructure.db.session import get_session_factory
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService


WORKER_STATES = ("UPLOADED", "PARSE_QUEUED", "CHUNK_QUEUED")


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
    management = KnowledgeManagementService(paths, progress=lambda message: print(message, flush=True))
    with get_session_factory()() as session:
        publication = session.scalar(select(IndexPublicationRequest).where(
            IndexPublicationRequest.status.in_(["BUILD_QUEUED", "PUBLISH_QUEUED"])
        ).order_by(IndexPublicationRequest.created_at))
        if publication is not None:
            return run_publication(session, publication, management, paths)
        job = session.scalar(select(IngestionJob).where(IngestionJob.state.in_(WORKER_STATES)).order_by(IngestionJob.created_at))
        if job is None:
            return False
        ingestion = IngestionService(session, paths)
        job.lease_owner = worker_id
        job.lease_expires_at = utc_now() + timedelta(minutes=10)
        job.heartbeat_at = utc_now()
        session.commit()
        try:
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
                job.chunk_run_id = int(result["id"])
                ensure_knowledge_run_succeeded("CHUNK_RUN", result)
                ingestion.transition(job, "CHUNK_REVIEW", "ChunkRun已生成，等待人工审核", run_type="CHUNK_RUN", run_id=job.chunk_run_id)
            job.lease_owner = None
            job.lease_expires_at = None
            session.commit()
        except Exception as exc:
            failed_stage = job.state
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
        return True


def run_publication(session, publication: IndexPublicationRequest, management: KnowledgeManagementService, paths: KnowledgePaths) -> bool:
    """串行构建或发布一个全局索引快照；Alias成功是唯一正式发布时点。"""

    ingestion = IngestionService(session, paths)
    document_ids = [int(value) for value in json.loads(publication.source_document_ids_json)]
    jobs = list(session.scalars(select(IngestionJob).where(
        IngestionJob.document_id.in_(document_ids)
    ).order_by(IngestionJob.created_at)).all())
    try:
        if publication.status == "BUILD_QUEUED":
            publication.status = "BUILDING"
            session.commit()
            for job in jobs:
                if job.state == "INDEX_QUEUED":
                    ingestion.transition(job, "INDEXING", f"开始构建索引发布请求 {publication.id}")
            result = management.build_index_run(required_document_ids=document_ids)
            publication.index_run_id = int(result["index_run_id"])
            publication.status = "READY_TO_PUBLISH"
            for job in jobs:
                if job.state == "INDEXING":
                    job.index_run_id = publication.index_run_id
                    ingestion.transition(
                        job, "READY_TO_PUBLISH", "全局IndexRun已完成核验",
                        run_type="INDEX_RUN", run_id=publication.index_run_id,
                    )
            session.commit()
            return True

        publication.status = "PUBLISHING"
        session.commit()
        for job in jobs:
            if job.state == "READY_TO_PUBLISH":
                ingestion.transition(job, "PUBLISH_QUEUED", f"发布请求 {publication.id} 已获管理员确认")
            if job.state == "PUBLISH_QUEUED":
                ingestion.transition(job, "PUBLISHING", "开始原子切换Platform Qdrant Alias")
        if publication.index_run_id is None:
            raise ValueError("发布请求缺少IndexRun ID")
        management.publish_index_run(publication.index_run_id)
        # 只有Alias切换和核验均成功，才写入正式发布状态。
        publication.status = "PUBLISHED"
        publication.published_at = utc_now()
        for job in jobs:
            if job.state == "PUBLISHING":
                ingestion.transition(
                    job, "PUBLISHED", "Alias切换成功，制度正式发布",
                    run_type="INDEX_RUN", run_id=publication.index_run_id,
                )
        changes = list(session.scalars(select(MetadataChangeRequest).where(
            MetadataChangeRequest.document_id.in_(document_ids),
            MetadataChangeRequest.status == "APPROVED",
        )).all())
        for change in changes:
            change.status = "PUBLISHED"
        session.commit()
        return True
    except Exception as exc:
        failed_stage = publication.status
        publication.status = "FAILED"
        publication.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
        for job in jobs:
            if job.state in {"INDEXING", "PUBLISHING"}:
                job.failed_stage = job.state
                job.retryable = True
                job.error_code = exc.__class__.__name__.upper()
                job.error_summary = str(exc)[:1000]
                ingestion.transition(job, "FAILED", f"{failed_stage}失败：{exc}")
        session.commit()
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="制度知识平台单Worker")
    parser.add_argument("--once", action="store_true", help="只推进一个任务阶段后退出")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    worker_id = f"local-worker-{os.getpid()}"
    while True:
        worked = run_once(worker_id)
        if args.once:
            return 0
        if not worked:
            time.sleep(max(args.poll_seconds, 0.5))


if __name__ == "__main__":
    raise SystemExit(main())
