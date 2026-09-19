"""文件说明：编排Platform元数据审核任务与Knowledge元数据修订生命周期。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion_service import IngestionService
from app.infrastructure.db.models import IngestionJob, MetadataChangeRequest, ReviewRecord
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError


class MetadataApplicationService:
    """维持跨库ID映射和平台审核审计，公开发布仍由IndexRun控制。"""

    def __init__(
        self,
        session: Session,
        knowledge: KnowledgeMetadataService,
        ingestion: IngestionService,
    ) -> None:
        self.session = session
        self.knowledge = knowledge
        self.ingestion = ingestion

    def list(self) -> list[dict]:
        """保留内部完整列表能力；管理接口使用 search 做筛选和分页。"""

        requests = {
            item.metadata_revision_id: item
            for item in self.session.scalars(select(MetadataChangeRequest)).all()
        }
        result: list[dict] = []
        for item in self.knowledge.list_documents():
            latest_request = requests.get(item.get("latest_metadata_revision_id"))
            active_request = requests.get(item.get("active_metadata_revision_id"))
            # 撤回只保留在修订历史；主列表回到active快照。驳回仍需显示，便于继续治理。
            request = (
                latest_request
                if latest_request is not None
                and latest_request.status in {"DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"}
                else active_request or latest_request
            )
            result.append({
                **item,
                "request_id": request.id if request else None,
                "request_type": request.request_type if request else None,
                "request_status": request.status if request else item.get("metadata_status"),
                "job_id": request.job_id if request else None,
            })
        return result

    def search(
        self,
        *,
        keyword: str | None,
        metadata_status: str | None,
        sort_by: str,
        page: int,
        page_size: int,
    ) -> dict:
        """跨Platform审核状态和Knowledge元数据进行轻量治理检索。"""

        rows = self.list()
        term = (keyword or "").strip().casefold()
        if term:
            searchable_fields = (
                "title", "file_name", "document_code", "issuing_org",
                "owner_department", "canonical_title",
            )
            rows = [
                row for row in rows
                if any(term in str(row.get(field) or "").casefold() for field in searchable_fields)
            ]
        if metadata_status == "ACTION_REQUIRED":
            rows = [row for row in rows if row.get("request_status") in {"DRAFT", "PENDING_REVIEW", "REJECTED"}]
        elif metadata_status:
            rows = [row for row in rows if row.get("request_status") == metadata_status]

        if sort_by == "TITLE_ASC":
            rows.sort(key=lambda row: str(row.get("title") or row.get("file_name") or "").casefold())
        elif sort_by == "PUBLISH_DATE_DESC":
            rows.sort(key=lambda row: (str(row.get("publish_date") or ""), int(row["id"])), reverse=True)
        elif sort_by == "UPDATED_DESC":
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), int(row["id"])), reverse=True)
        else:
            priority = {"PENDING_REVIEW": 0, "DRAFT": 1, "REJECTED": 2, "APPROVED": 3, "WITHDRAWN": 4, "PUBLISHED": 5}
            rows.sort(key=lambda row: (
                priority.get(str(row.get("request_status")), 5),
                -int(row["id"]),
            ))
        total = len(rows)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size}

    def detail(self, document_id: int) -> dict:
        detail = self.knowledge.detail(document_id)
        revision_ids = [int(item["id"]) for item in detail["revisions"]]
        requests = list(self.session.scalars(
            select(MetadataChangeRequest).where(
                MetadataChangeRequest.metadata_revision_id.in_(revision_ids)
            )
        ).all()) if revision_ids else []
        detail["requests"] = [self._request_dict(item) for item in requests]
        return detail

    def create_draft(
        self,
        document_id: int,
        actor_user_id: str,
        request_type: str,
        change_reason: str | None,
    ) -> dict:
        open_requests = self._open_requests(document_id)
        if open_requests:
            current = open_requests[0]
            can_reuse_draft = (
                len(open_requests) == 1
                and current.status == "DRAFT"
                and current.request_type == request_type
            )
            if not can_reuse_draft:
                raise MetadataConflictError(
                    f"制度已有未完成的元数据修订 {current.metadata_revision_id}（{current.status}），"
                    "请先完成或撤回该修订"
                )
        source_types = {
            "CORRECTION": "MANUAL_CORRECTION",
            "REPEAL": "REPEAL",
            "EXPIRY": "EXPIRY",
        }
        if request_type not in source_types:
            raise ValueError("人工创建只支持元数据修订、制度废止或制度失效")
        revision = self.knowledge.ensure_draft(
            document_id,
            actor_user_id,
            source_type=source_types[request_type],
            change_reason=change_reason,
        )
        request = self._ensure_request(
            document_id, int(revision["id"]), actor_user_id, request_type, None
        )
        self.session.commit()
        return {"revision": revision, "request": self._request_dict(request)}

    def register_initial(
        self,
        document_id: int,
        revision_id: int,
        job_id: str,
        actor_user_id: str,
    ) -> MetadataChangeRequest:
        conflicts = self._open_requests(document_id, exclude_revision_id=revision_id)
        if conflicts:
            raise MetadataConflictError(
                "制度已有未完成的元数据修订，不能登记新的首次入库审核任务"
            )
        request = self._ensure_request(
            document_id, revision_id, actor_user_id, "INITIAL", job_id
        )
        self.session.flush()
        return request

    def update(self, document_id: int, revision_id: int, values: dict) -> dict:
        return self.knowledge.update_draft(document_id, revision_id, values)

    def submit(self, document_id: int, revision_id: int, actor_user_id: str) -> dict:
        request = self._request(revision_id)
        if request is None:
            request = self._ensure_request(
                document_id, revision_id, actor_user_id, "CORRECTION", None
            )
        conflicts = self._open_requests(document_id, exclude_revision_id=revision_id)
        if conflicts:
            raise MetadataConflictError("同一制度存在其他未完成元数据修订，请先处理冲突")
        revision = self.knowledge.submit(document_id, revision_id)
        request.status = "PENDING_REVIEW"
        self.session.commit()
        return {"revision": revision, "request": self._request_dict(request)}

    def review(
        self,
        document_id: int,
        revision_id: int,
        approved: bool,
        reviewer_user_id: str,
        comment: str | None,
    ) -> dict:
        request = self._request(revision_id)
        if request is None:
            raise MetadataConflictError("Platform元数据审核任务不存在")
        if approved:
            conflicts = list(self.session.scalars(select(MetadataChangeRequest).where(
                MetadataChangeRequest.document_id == document_id,
                MetadataChangeRequest.metadata_revision_id != revision_id,
                MetadataChangeRequest.status == "APPROVED",
            )).all())
            if conflicts:
                raise MetadataConflictError("同一制度已有审核通过待发布修订，请先发布或撤回")
        revision = self.knowledge.review(
            document_id, revision_id, approved, reviewer_user_id, comment
        )
        request.status = "APPROVED" if approved else "REJECTED"
        request.open_slot = "OPEN" if approved else None
        request.reviewed_by = reviewer_user_id
        request.review_comment = comment
        self.session.add(ReviewRecord(
            target_type="METADATA_REVISION",
            target_id=str(revision_id),
            outcome="PASS" if approved else "REJECT",
            comment=comment,
            reviewer_user_id=reviewer_user_id,
        ))
        if approved and request.job_id:
            job = self.session.get(IngestionJob, request.job_id)
            if job and job.state == "METADATA_REVIEW":
                self.ingestion.transition(
                    job,
                    "CHUNK_QUEUED",
                    "制度元数据已审核，进入分块队列",
                    reviewer_user_id,
                    run_type="METADATA_REVISION",
                    run_id=revision_id,
                )
        self.session.commit()
        return {"revision": revision, "request": self._request_dict(request)}

    def withdraw(
        self,
        document_id: int,
        revision_id: int,
        actor_user_id: str,
        reason: str,
    ) -> dict:
        """撤回未发布人工修订，并在Platform侧保留完整审计。"""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("撤回原因不能为空")
        request = self._request(revision_id)
        if request is None or int(request.document_id) != document_id:
            raise LookupError("Platform元数据变更请求不存在")
        if request.request_type == "INITIAL" or request.job_id is not None:
            raise MetadataConflictError("首次入库元数据不能撤回，请在审核流程中处理")
        if request.status == "WITHDRAWN":
            revision = self.knowledge.withdraw(document_id, revision_id)
            return {"revision": revision, "request": self._request_dict(request)}
        if request.status not in {"DRAFT", "PENDING_REVIEW", "APPROVED"}:
            raise MetadataConflictError("只有尚未发布的人工元数据修订可以撤回")

        revision = self.knowledge.withdraw(document_id, revision_id)
        request.status = "WITHDRAWN"
        request.open_slot = None
        self.session.add(ReviewRecord(
            target_type="METADATA_REVISION",
            target_id=str(revision_id),
            outcome="WITHDRAWN",
            comment=normalized_reason,
            reviewer_user_id=actor_user_id,
        ))
        self.session.commit()
        return {"revision": revision, "request": self._request_dict(request)}

    def _request(self, revision_id: int) -> MetadataChangeRequest | None:
        return self.session.scalar(select(MetadataChangeRequest).where(
            MetadataChangeRequest.metadata_revision_id == revision_id
        ))

    def _open_requests(
        self,
        document_id: int,
        *,
        exclude_revision_id: int | None = None,
    ) -> list[MetadataChangeRequest]:
        """返回同一制度仍占用唯一变更槽位的请求。"""

        statement = select(MetadataChangeRequest).where(
            MetadataChangeRequest.document_id == document_id,
            MetadataChangeRequest.status.in_(["DRAFT", "PENDING_REVIEW", "APPROVED"]),
        )
        if exclude_revision_id is not None:
            statement = statement.where(
                MetadataChangeRequest.metadata_revision_id != exclude_revision_id
            )
        return list(self.session.scalars(
            statement.order_by(MetadataChangeRequest.updated_at.desc())
        ).all())

    def _ensure_request(
        self,
        document_id: int,
        revision_id: int,
        actor_user_id: str,
        request_type: str,
        job_id: str | None,
    ) -> MetadataChangeRequest:
        request = self._request(revision_id)
        if request is None:
            request = MetadataChangeRequest(
                document_id=document_id,
                metadata_revision_id=revision_id,
                job_id=job_id,
                request_type=request_type,
                open_slot="OPEN",
                created_by=actor_user_id,
            )
            self.session.add(request)
        else:
            if request.request_type != request_type:
                raise MetadataConflictError(
                    f"元数据修订已绑定 {request.request_type} 请求，不能改作 {request_type}"
                )
            if job_id and request.job_id not in {None, job_id}:
                raise MetadataConflictError("元数据修订已经绑定其他入库任务")
            if job_id and request.job_id is None:
                request.job_id = job_id
        return request

    @staticmethod
    def _request_dict(item: MetadataChangeRequest) -> dict:
        return {
            "id": item.id,
            "document_id": item.document_id,
            "metadata_revision_id": item.metadata_revision_id,
            "job_id": item.job_id,
            "request_type": item.request_type,
            "status": item.status,
            "open_slot": item.open_slot,
            "created_by": item.created_by,
            "reviewed_by": item.reviewed_by,
            "review_comment": item.review_comment,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
