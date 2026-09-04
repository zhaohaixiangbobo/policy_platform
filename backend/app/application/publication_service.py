"""文件说明：管理全局IndexRun构建请求和Alias正式发布确认。"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion_service import IngestionService, JobConflictError
from app.infrastructure.db.models import IndexPublicationRequest, IngestionJob, MetadataChangeRequest, utc_now


class PublicationService:
    """一次请求冻结若干变更，实际IndexRun仍包含完整可发布知识快照。"""

    def __init__(self, session: Session, ingestion: IngestionService) -> None:
        self.session = session
        self.ingestion = ingestion

    def create(self, document_ids: list[int], actor_user_id: str) -> IndexPublicationRequest:
        normalized = sorted(set(int(value) for value in document_ids))
        if not normalized or len(normalized) > 20:
            raise ValueError("一次发布必须选择1至20个制度文件")
        active = self.session.scalar(select(IndexPublicationRequest).where(
            IndexPublicationRequest.status.in_([
                "BUILD_QUEUED", "BUILDING", "READY_TO_PUBLISH", "PUBLISH_QUEUED", "PUBLISHING"
            ])
        ))
        if active:
            raise JobConflictError(f"已有未完成的索引发布请求：{active.id}")
        request = IndexPublicationRequest(
            status="BUILD_QUEUED",
            source_document_ids_json=json.dumps(normalized),
            requested_by=actor_user_id,
        )
        self.session.add(request)
        self.session.flush()
        jobs = list(self.session.scalars(select(IngestionJob).where(
            IngestionJob.document_id.in_(normalized),
            IngestionJob.state == "READY_FOR_INDEX",
        )).all())
        covered = {int(job.document_id) for job in jobs if job.document_id is not None}
        # 已发布制度的元数据修订没有新入库Job，由MetadataChangeRequest提供发布资格。
        changed = {
            int(item.document_id)
            for item in self.session.scalars(select(MetadataChangeRequest).where(
                MetadataChangeRequest.document_id.in_(normalized),
                MetadataChangeRequest.status == "APPROVED",
            )).all()
        }
        missing = sorted(set(normalized) - covered - changed)
        if missing:
            raise JobConflictError(f"以下制度尚未完成审核或没有待发布变更：{missing}")
        for job in jobs:
            self.ingestion.transition(
                job, "INDEX_QUEUED", f"已加入索引发布请求 {request.id}", actor_user_id
            )
        self.session.commit()
        self.session.refresh(request)
        return request

    def list(self) -> list[IndexPublicationRequest]:
        return list(self.session.scalars(
            select(IndexPublicationRequest).order_by(IndexPublicationRequest.created_at.desc())
        ).all())

    def queue_publish(self, request_id: str, actor_user_id: str) -> IndexPublicationRequest:
        request = self._get(request_id)
        if request.status != "READY_TO_PUBLISH" or request.index_run_id is None:
            raise JobConflictError("索引快照尚未完成全量核验")
        request.status = "PUBLISH_QUEUED"
        request.published_by = actor_user_id
        self.session.commit()
        self.session.refresh(request)
        return request

    def retry(self, request_id: str) -> IndexPublicationRequest:
        request = self._get(request_id)
        if request.status != "FAILED":
            raise JobConflictError("只有失败的发布请求可以重试")
        document_ids = self.document_ids(request)
        jobs = list(self.session.scalars(select(IngestionJob).where(
            IngestionJob.document_id.in_(document_ids), IngestionJob.state == "FAILED"
        )).all())
        for job in jobs:
            self.ingestion.retry(job.id, job.state_version, request.requested_by, "重试索引发布请求")
        request.status = "READY_TO_PUBLISH" if request.index_run_id else "BUILD_QUEUED"
        request.error_summary = None
        self.session.commit()
        self.session.refresh(request)
        return request

    def document_ids(self, request: IndexPublicationRequest) -> list[int]:
        return [int(value) for value in json.loads(request.source_document_ids_json)]

    def _get(self, request_id: str) -> IndexPublicationRequest:
        request = self.session.get(IndexPublicationRequest, request_id)
        if request is None:
            raise LookupError("索引发布请求不存在")
        return request


def publication_dict(item: IndexPublicationRequest) -> dict:
    """输出不泄露平台内部路径的发布请求摘要。"""

    return {
        "id": item.id,
        "status": item.status,
        "document_ids": json.loads(item.source_document_ids_json),
        "index_run_id": item.index_run_id,
        "alias_name": item.alias_name,
        "requested_by": item.requested_by,
        "published_by": item.published_by,
        "error_summary": item.error_summary,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "published_at": item.published_at,
    }
