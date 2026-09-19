"""文件说明：实现ParseRun/ChunkRun审核队列与标准PASS、警告通过、驳回结果。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.application.ingestion_service import IngestionService
from app.application.metadata_service import MetadataApplicationService
from app.infrastructure.db.models import IngestionJob, MetadataChangeRequest, ReviewIssue, ReviewRecord
from knowledge.management import KnowledgeManagementService
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError
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

    def search_queue(
        self,
        *,
        include_history: bool,
        processing_status: str | None,
        target_type: str | None,
        keyword: str | None,
        review_state: str | None,
        sort_by: str,
        page: int,
        page_size: int,
    ) -> dict:
        """聚合两库审核摘要，并在服务端完成搜索、筛选、排序和分页。"""

        if self.reader is None:
            raise RuntimeError("审核队列查询必须提供Knowledge读服务")
        jobs = (
            list(self.session.scalars(select(IngestionJob).order_by(IngestionJob.updated_at.desc())).all())
            if include_history else self.queue()
        )
        items: list[dict] = []
        for job in jobs:
            targets: list[tuple[str, int]] = []
            if include_history:
                if job.parse_run_id is not None:
                    targets.append(("PARSE_RUN", job.parse_run_id))
                if job.chunk_run_id is not None:
                    targets.append(("CHUNK_RUN", job.chunk_run_id))
            else:
                run_type = "PARSE_RUN" if job.state == "PARSE_REVIEW" else "CHUNK_RUN"
                run_id = job.parse_run_id if run_type == "PARSE_RUN" else job.chunk_run_id
                if run_id is not None:
                    targets.append((run_type, run_id))

            for run_type, run_id in targets:
                detail = self.reader.review_detail(run_type, run_id)
                pending_count = sum(1 for item in detail["issues"] if not item.get("resolved"))
                review_objects = [*detail["nodes"], *detail["chunks"]]
                pending_count += sum(
                    1 for item in review_objects
                    if str(item.get("review_status", "")).lower() == "pending"
                )
                run_status = str(detail["run"].get("status") or "").lower()
                run_review_status = str(detail["run"].get("review_status") or "pending").lower()
                latest_review = self.session.scalar(select(ReviewRecord).where(
                    ReviewRecord.target_type == run_type,
                    ReviewRecord.target_id == str(run_id),
                ).order_by(ReviewRecord.created_at.desc()))
                processed = (
                    latest_review is not None
                    or run_review_status in {"approved", "rejected"}
                    or run_status == "failed"
                )
                outcome = latest_review.outcome if latest_review else (
                    "REJECT" if run_review_status == "rejected"
                    else "PASS" if run_review_status == "approved"
                    else None
                )
                display_state = (
                    "FAILED" if run_status == "failed"
                    else outcome if outcome
                    else "ACTION_REQUIRED" if pending_count else "READY_TO_SUBMIT"
                )
                document_title = str(detail["run"].get("document_title") or job.task_name)
                document_code = detail["run"].get("document_code")
                items.append({
                    "target_type": run_type,
                    "target_id": str(run_id),
                    "job_id": job.id,
                    "document_id": job.document_id,
                    "title": document_title,
                    "document_code": str(document_code) if document_code else None,
                    "state": job.state,
                    "issue_count": pending_count,
                    "review_status": run_review_status,
                    "processing_status": "PROCESSED" if processed else "PENDING",
                    "review_outcome": outcome,
                    "display_state": display_state,
                    "created_at": job.created_at,
                    "updated_at": latest_review.created_at if latest_review else job.updated_at,
                    "_search_text": " ".join(filter(None, [
                        document_title, str(document_code or ""), job.task_name,
                        str(run_id), job.id,
                    ])).lower(),
                })

        normalized_keyword = (keyword or "").strip().lower()
        searched = [item for item in items if not normalized_keyword or normalized_keyword in item["_search_text"]]
        counts = {
            "pending_parse": sum(item["processing_status"] == "PENDING" and item["target_type"] == "PARSE_RUN" for item in searched),
            "pending_chunk": sum(item["processing_status"] == "PENDING" and item["target_type"] == "CHUNK_RUN" for item in searched),
            "processed_parse": sum(item["processing_status"] == "PROCESSED" and item["target_type"] == "PARSE_RUN" for item in searched),
            "processed_chunk": sum(item["processing_status"] == "PROCESSED" and item["target_type"] == "CHUNK_RUN" for item in searched),
        }
        filtered = [
            item for item in searched
            if (processing_status is None or item["processing_status"] == processing_status)
            and (target_type is None or item["target_type"] == target_type)
            and (review_state is None or item["display_state"] == review_state)
        ]
        if sort_by == "OLDEST_PENDING":
            filtered.sort(key=lambda item: (item["updated_at"], item["target_id"]))
        elif sort_by == "TITLE_ASC":
            filtered.sort(key=lambda item: (item["title"], item["target_id"]))
        else:
            filtered.sort(key=lambda item: (item["updated_at"], item["target_id"]), reverse=True)
        total = len(filtered)
        start = (page - 1) * page_size
        page_items = filtered[start:start + page_size]
        for item in page_items:
            item.pop("_search_text", None)
        return {
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "counts": counts,
        }

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
                existing_change = self.session.scalar(select(MetadataChangeRequest).where(
                    MetadataChangeRequest.document_id == job.document_id,
                    MetadataChangeRequest.status.in_(["DRAFT", "PENDING_REVIEW", "APPROVED"]),
                    or_(
                        MetadataChangeRequest.job_id.is_(None),
                        MetadataChangeRequest.job_id != job.id,
                    ),
                ))
                if existing_change is not None:
                    raise ReviewConflictError(
                        "制度已有未完成元数据修订，请先完成或撤回后再批准新的ParseRun"
                    )
                self.management.approve_parse_run(job.parse_run_id, reviewer_user_id, comment)
                if job.document_id is None:
                    raise ReviewConflictError("任务缺少Document ID")
                revision = self.management.ensure_metadata_draft(
                    job.document_id,
                    reviewer_user_id,
                    job.initial_document_status,
                )
                with KnowledgeMetadataService(self.management.paths.database_path) as knowledge:
                    try:
                        MetadataApplicationService(
                            self.session, knowledge, self.ingestion
                        ).register_initial(
                            job.document_id,
                            int(revision["id"]),
                            job.id,
                            reviewer_user_id,
                        )
                    except MetadataConflictError as exc:
                        raise ReviewConflictError(str(exc)) from exc
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

    def decide_items(self, job_id: str, target_type: str, target_ids: list[int], action: str, comment: str | None, reviewer_user_id: str) -> dict:
        """批量操作只处理当前运行内可安全确认的同类对象。"""

        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state == "PARSE_REVIEW" and job.parse_run_id is not None:
            if target_type not in {"node", "issue"}:
                raise ReviewConflictError("ParseRun批量对象类型非法")
            return self.management.decide_parse_items(
                job.parse_run_id, target_type, target_ids, action, reviewer_user_id, comment
            )
        if job.state == "CHUNK_REVIEW" and job.chunk_run_id is not None:
            if target_type != "chunk_issue" or action != "ignore":
                raise ReviewConflictError("ChunkRun批量操作只支持接受普通问题")
            return self.management.decide_chunk_items(
                job.chunk_run_id, target_ids, reviewer_user_id, comment
            )
        raise ReviewConflictError("任务当前不在审核节点")

    def decide_article_title(self, job_id: str, node_id: int, mode: str, title: str | None, comment: str | None, reviewer_user_id: str) -> dict:
        """只允许在当前ParseRun审核阶段处置启发式条标题。"""

        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job.state != "PARSE_REVIEW" or job.parse_run_id is None:
            raise ReviewConflictError("任务当前不在ParseRun审核节点")
        return self.management.decide_parse_article_title(
            job.parse_run_id, node_id, mode, reviewer_user_id, title, comment
        )
