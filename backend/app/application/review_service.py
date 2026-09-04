"""文件说明：实现ParseRun/ChunkRun审核队列与标准PASS、警告通过、驳回结果。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion_service import IngestionService
from app.infrastructure.db.models import IngestionJob, MetadataChangeRequest, ReviewIssue, ReviewRecord
from knowledge.management import KnowledgeManagementService
from knowledge.read_service import KnowledgeReadService


class ReviewConflictError(RuntimeError):
    """审核目标状态或问题处置不满足提交条件。"""


FIELD_DISPLAY_NAMES = {
    "title": "制度名称", "document_code": "文号", "document_type": "文种",
    "issuing_org": "发布机构", "addressee_text": "主送对象", "publish_date": "发布日期",
    "effective_date": "生效日期", "expiry_date": "失效日期", "owner_department": "责任部门",
    "status": "制度状态", "version": "制度版本", "parser_profile": "解析结构类型",
}


class ReviewService:
    def __init__(self, session: Session, ingestion: IngestionService, management: KnowledgeManagementService, reader: KnowledgeReadService | None = None) -> None:
        self.session = session
        self.ingestion = ingestion
        self.management = management
        self.reader = reader

    def queue(self) -> list[IngestionJob]:
        return list(self.session.scalars(select(IngestionJob).where(IngestionJob.state.in_(["PARSE_REVIEW", "CHUNK_REVIEW"])).order_by(IngestionJob.updated_at)).all())

    def decide(self, job_id: str, outcome: str, comment: str | None, warning_acceptance: str | None, reviewer_user_id: str) -> IngestionJob:
        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state not in {"PARSE_REVIEW", "CHUNK_REVIEW"}:
            raise ReviewConflictError("任务当前不在审核节点")
        target_type = "PARSE_RUN" if job.state == "PARSE_REVIEW" else "CHUNK_RUN"
        target_id = str(job.parse_run_id if target_type == "PARSE_RUN" else job.chunk_run_id or job.id)
        open_errors = self.session.scalars(select(ReviewIssue).where(ReviewIssue.target_type == target_type, ReviewIssue.target_id == target_id, ReviewIssue.severity == "ERROR", ReviewIssue.disposition == "OPEN")).all()
        if outcome in {"PASS", "PASS_WITH_WARNING"} and open_errors:
            raise ReviewConflictError("仍有未处理的阻断问题")
        if outcome in {"PASS", "PASS_WITH_WARNING"} and self.reader:
            details = self.reader.review_detail(target_type, int(target_id))
            pending_nodes = [
                item for item in details["nodes"]
                if str(item.get("review_status", "")).lower() == "pending"
            ]
            if pending_nodes:
                raise ReviewConflictError(f"还有{len(pending_nodes)}个结构节点待确认")
            blocking = [item for item in details["issues"] if str(item.get("severity", "")).lower() == "error" and not item.get("resolved")]
            if blocking:
                raise ReviewConflictError("知识运行仍有未处理的阻断问题")
            warnings = [item for item in details["issues"] if not item.get("resolved")]
            if outcome == "PASS" and warnings:
                raise ReviewConflictError("存在未处置警告，请选择警告通过并填写接受理由")
        if outcome == "PASS_WITH_WARNING" and not (warning_acceptance or "").strip():
            raise ReviewConflictError("警告通过必须填写逐项接受理由")
        if outcome == "REJECT" and not (comment or "").strip():
            raise ReviewConflictError("驳回必须填写原因")
        self.session.add(ReviewRecord(target_type=target_type, target_id=target_id, outcome=outcome, comment=comment, warning_acceptance=warning_acceptance, reviewer_user_id=reviewer_user_id))
        self.session.flush()
        if outcome == "REJECT":
            if target_type == "CHUNK_RUN" and job.chunk_run_id is not None:
                self.management.reject_chunk_run(job.chunk_run_id, reviewer_user_id, comment)
            self.ingestion.transition(job, "REJECTED", comment or "审核驳回", reviewer_user_id)
        else:
            if target_type == "PARSE_RUN":
                if job.parse_run_id is None:
                    raise ReviewConflictError("任务缺少ParseRun ID")
                self.management.approve_parse_run(job.parse_run_id, reviewer_user_id, comment)
                if job.document_id is None:
                    raise ReviewConflictError("任务缺少Document ID")
                revision = self.management.ensure_metadata_draft(
                    job.document_id,
                    reviewer_user_id,
                    job.initial_document_status,
                )
                existing = self.session.scalar(select(MetadataChangeRequest).where(
                    MetadataChangeRequest.metadata_revision_id == int(revision["id"])
                ))
                if existing is None:
                    self.session.add(MetadataChangeRequest(
                        document_id=job.document_id,
                        metadata_revision_id=int(revision["id"]),
                        job_id=job.id,
                        request_type="INITIAL",
                        created_by=reviewer_user_id,
                    ))
            else:
                if job.chunk_run_id is None:
                    raise ReviewConflictError("任务缺少ChunkRun ID")
                self.management.approve_chunk_run(job.chunk_run_id, reviewer_user_id, comment)
            next_state = "METADATA_REVIEW" if job.state == "PARSE_REVIEW" else "READY_FOR_INDEX"
            self.ingestion.transition(job, next_state, f"审核结果：{outcome}", reviewer_user_id)
        return job

    def decide_item(self, job_id: str, target_type: str, target_id: int, action: str, comment: str | None, corrected_value: str | None, reviewer_user_id: str) -> dict:
        """处理知识运行中的单个字段、Node或质量问题。"""

        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state == "PARSE_REVIEW" and job.parse_run_id is not None:
            if target_type not in {"issue", "field", "node"}:
                raise ReviewConflictError("ParseRun审核对象类型非法")
            return self.management.decide_parse_item(job.parse_run_id, target_type, target_id, action, reviewer_user_id, comment, corrected_value)
        if job.state == "CHUNK_REVIEW" and job.chunk_run_id is not None:
            if target_type not in {"chunk_issue", "chunk"}:
                raise ReviewConflictError("ChunkRun审核对象类型非法")
            return self.management.decide_chunk_item(job.chunk_run_id, target_type, target_id, action, reviewer_user_id, comment)
        raise ReviewConflictError("任务当前不在审核节点")
