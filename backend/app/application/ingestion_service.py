"""文件说明：实现DOCX安全入库、任务查询、状态事件和受控人工重试。"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ingestion import InvalidStateTransition, assert_transition, retry_target
from app.infrastructure.db.models import IngestionArtifact, IngestionBatch, IngestionJob, IngestionJobEvent, utc_now
from knowledge.config import KnowledgePaths


class InvalidDocumentError(ValueError):
    """上传内容不满足受控制度DOCX约束。"""


class JobConflictError(RuntimeError):
    """任务版本或重复上传冲突。"""


class IngestionService:
    """Platform任务编排服务；不直接调用Parser、SQLite或Qdrant。"""

    MAX_UPLOAD_BYTES = 50 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024

    def __init__(self, session: Session, paths: KnowledgePaths) -> None:
        self.session = session
        self.paths = paths

    def create_job(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
        actor_user_id: str,
        *,
        initial_document_status: str = "effective",
        batch_id: str | None = None,
        rework_of_job_id: str | None = None,
    ) -> IngestionJob:
        if initial_document_status not in {"effective", "repealed", "expired"}:
            raise InvalidDocumentError("上传声明值必须是现行有效、已废止或已失效")
        safe_name = Path(filename).name
        if Path(safe_name).suffix.lower() != ".docx":
            raise InvalidDocumentError("仅支持DOCX制度文件")
        if content_type and content_type not in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream", "application/zip",
        }:
            raise InvalidDocumentError("文件MIME类型不是DOCX")
        self._validate_docx(content)
        digest = hashlib.sha256(content).hexdigest()
        duplicate = self.session.scalar(select(IngestionJob).where(IngestionJob.file_sha256 == digest, IngestionJob.state.notin_(["REJECTED", "CANCELLED"])).order_by(IngestionJob.created_at.desc()))
        if duplicate:
            raise JobConflictError(f"相同文件已有任务：{duplicate.id}")
        self.paths.pending_documents.mkdir(parents=True, exist_ok=True)
        batch = None
        if batch_id:
            batch = self.session.get(IngestionBatch, batch_id)
            if batch is None or batch.status != "OPEN":
                raise JobConflictError("入库批次不存在或已经封存")
            if batch.file_count >= 20:
                raise JobConflictError("单批次最多包含20个制度文件")
        if rework_of_job_id:
            source_job = self.session.get(IngestionJob, rework_of_job_id)
            if source_job is None or source_job.state not in {"REJECTED", "FAILED"}:
                raise JobConflictError("只有已驳回或失败任务可以创建返工任务")
        job = IngestionJob(
            task_name=safe_name.removesuffix(".docx"), original_filename=safe_name,
            stored_path="", file_sha256=digest, created_by=actor_user_id,
            initial_document_status=initial_document_status,
            batch_id=batch_id, rework_of_job_id=rework_of_job_id,
        )
        self.session.add(job)
        self.session.flush()
        stored_name = f"{job.id}_{self._safe_filename(safe_name)}"
        target = (self.paths.pending_documents / stored_name).resolve()
        if not target.is_relative_to(self.paths.pending_documents.resolve()):
            raise InvalidDocumentError("文件名无法安全保存")
        target.write_bytes(content)
        job.stored_path = target.relative_to(self.paths.data_root).as_posix()
        self.session.add(IngestionJobEvent(job_id=job.id, from_state=None, to_state="UPLOADED", actor_user_id=actor_user_id, reason="DOCX上传并完成同步预检"))
        self.session.add(IngestionArtifact(job_id=job.id, artifact_type="SOURCE_DOCX", relative_path=job.stored_path, sha256=digest))
        if batch is not None:
            batch.file_count += 1
        self.session.commit()
        self.session.refresh(job)
        return job

    def create_batch(self, name: str, actor_user_id: str) -> IngestionBatch:
        batch = IngestionBatch(name=name.strip(), created_by=actor_user_id)
        if not batch.name:
            raise ValueError("批次名称不能为空")
        self.session.add(batch)
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def list_batches(self) -> list[IngestionBatch]:
        return list(self.session.scalars(
            select(IngestionBatch).order_by(IngestionBatch.created_at.desc())
        ).all())

    def complete_batch(self, batch_id: str) -> IngestionBatch:
        batch = self.session.get(IngestionBatch, batch_id)
        if batch is None:
            raise LookupError("入库批次不存在")
        if batch.status != "OPEN":
            raise JobConflictError("入库批次已经封存")
        if batch.file_count == 0:
            raise JobConflictError("空批次不能封存")
        batch.status = "SEALED"
        batch.completed_at = utc_now()
        self.session.commit()
        self.session.refresh(batch)
        return batch

    def create_structure_rework(
        self,
        source_job_id: str,
        parse_run_id: int,
        actor_user_id: str,
    ) -> IngestionJob:
        """为派生ParseRun建立新任务，终态任务保持只读。"""

        source = self.session.get(IngestionJob, source_job_id)
        if source is None or source.document_id is None:
            raise LookupError("原入库任务不存在")
        job = IngestionJob(
            task_name=f"{source.task_name}（结构修正）",
            original_filename=source.original_filename,
            stored_path=source.stored_path,
            file_sha256=source.file_sha256,
            initial_document_status=source.initial_document_status,
            state="PARSE_REVIEW",
            stage_progress=35,
            document_id=source.document_id,
            parse_run_id=parse_run_id,
            created_by=actor_user_id,
            rework_of_job_id=source.id,
        )
        self.session.add(job)
        self.session.flush()
        self.session.add(IngestionJobEvent(
            job_id=job.id, from_state=None, to_state="PARSE_REVIEW",
            actor_user_id=actor_user_id,
            reason=f"由任务 {source.id} 创建人工结构修正ParseRun",
            run_type="PARSE_RUN", run_id=parse_run_id,
        ))
        self.session.commit()
        self.session.refresh(job)
        return job

    def list_jobs(self, state: str | None = None) -> tuple[list[IngestionJob], int, dict[str, int]]:
        query = select(IngestionJob)
        if state:
            query = query.where(IngestionJob.state == state)
        items = self.session.scalars(query.order_by(IngestionJob.created_at.desc())).all()
        counts = {row[0]: row[1] for row in self.session.execute(select(IngestionJob.state, func.count()).group_by(IngestionJob.state)).all()}
        total = self.session.scalar(select(func.count()).select_from(IngestionJob)) or 0
        return list(items), int(total), {str(key): int(value) for key, value in counts.items()}

    def retry(self, job_id: str, expected_version: int, actor_user_id: str, reason: str) -> IngestionJob:
        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state != "FAILED" or job.state_version != expected_version:
            raise JobConflictError("任务状态已经变化，请刷新后重试")
        target = retry_target(job.failed_stage, job.retryable)
        previous = job.state
        job.state = target
        job.state_version += 1
        job.attempt_no += 1
        job.retryable = False
        job.failed_stage = None
        job.error_code = None
        job.error_summary = None
        self.session.add(IngestionJobEvent(job_id=job.id, from_state=previous, to_state=target, actor_user_id=actor_user_id, reason=reason))
        self.session.commit()
        self.session.refresh(job)
        return job

    def queue_publish(self, job_id: str, expected_version: int, actor_user_id: str) -> IngestionJob:
        """管理员显式确认后将已核验IndexRun放入发布队列。"""

        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state != "READY_TO_PUBLISH" or job.state_version != expected_version:
            raise JobConflictError("任务并非待发布状态或版本已经变化")
        if job.index_run_id is None:
            raise JobConflictError("任务缺少已核验的IndexRun")
        self.transition(job, "PUBLISH_QUEUED", "管理员确认发布", actor_user_id)
        self.session.refresh(job)
        return job

    def transition(self, job: IngestionJob, target: str, reason: str, actor_user_id: str | None = None, run_type: str | None = None, run_id: int | None = None) -> None:
        assert_transition(job.state, target)
        previous = job.state
        job.state = target
        job.state_version += 1
        progress = {
            "UPLOADED": 5, "PREFLIGHTING": 10, "PARSE_QUEUED": 15, "PARSING": 25,
            "PARSE_REVIEW": 35, "METADATA_REVIEW": 40, "CHUNK_QUEUED": 45, "CHUNKING": 50,
            "CHUNK_REVIEW": 60, "READY_FOR_INDEX": 65, "INDEX_QUEUED": 68, "INDEXING": 78,
            "READY_TO_PUBLISH": 90, "PUBLISH_QUEUED": 92, "PUBLISHING": 96,
            "PUBLISHED": 100, "REJECTED": 100, "CANCELLED": 100,
        }
        job.stage_progress = progress.get(target, job.stage_progress)
        self.session.add(IngestionJobEvent(job_id=job.id, from_state=previous, to_state=target, actor_user_id=actor_user_id, reason=reason, run_type=run_type, run_id=run_id))
        self.session.commit()

    def _validate_docx(self, content: bytes) -> None:
        if not content or len(content) > self.MAX_UPLOAD_BYTES:
            raise InvalidDocumentError("DOCX为空或超过50MB安全上限")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise InvalidDocumentError("DOCX结构不完整")
                total = 0
                for item in archive.infolist():
                    path = PurePosixPath(item.filename)
                    if path.is_absolute() or ".." in path.parts:
                        raise InvalidDocumentError("DOCX包含不安全路径")
                    total += item.file_size
                if total > self.MAX_UNCOMPRESSED_BYTES:
                    raise InvalidDocumentError("DOCX解压规模超过安全上限")
        except zipfile.BadZipFile as exc:
            raise InvalidDocumentError("文件不是有效DOCX") from exc

    @staticmethod
    def _safe_filename(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]", "_", value)[:180]
