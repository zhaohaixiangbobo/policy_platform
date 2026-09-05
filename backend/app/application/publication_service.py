"""文件说明：管理全局IndexRun构建请求和Alias正式发布确认。"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion_service import IngestionService, JobConflictError
from app.domain.ingestion import RETRY_TARGETS
from app.infrastructure.db.models import (
    IndexPublicationSource,
    IndexPublicationRequest,
    IngestionJob,
    MetadataChangeRequest,
    utc_now,
)
from knowledge.management import KnowledgeManagementService


EXACT_SNAPSHOT_CONTRACT = "exact_snapshot_v2"


class PublicationService:
    """一次请求冻结完整基线和本次变更，保证IndexRun来源集合精确可审计。"""

    def __init__(
        self,
        session: Session,
        ingestion: IngestionService,
        management: KnowledgeManagementService | None = None,
    ) -> None:
        self.session = session
        self.ingestion = ingestion
        self.management = management

    def create(self, document_ids: list[int], actor_user_id: str) -> IndexPublicationRequest:
        if self.management is None:
            raise RuntimeError("创建发布请求必须提供知识管理服务以冻结来源版本")
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
        changes = list(self.session.scalars(select(MetadataChangeRequest).where(
            MetadataChangeRequest.document_id.in_(normalized),
            MetadataChangeRequest.status == "APPROVED",
        ).order_by(MetadataChangeRequest.updated_at.desc())).all())
        changes_by_document: dict[int, list[MetadataChangeRequest]] = {}
        for change in changes:
            changes_by_document.setdefault(int(change.document_id), []).append(change)

        bindings: list[tuple[IngestionJob | None, MetadataChangeRequest, dict[str, int]]] = []
        missing: list[int] = []
        for document_id in normalized:
            document_changes = changes_by_document.get(document_id, [])
            if len(document_changes) > 1:
                raise JobConflictError(f"制度 {document_id} 存在多个待发布元数据修订，请先消除冲突")
            change = document_changes[0] if document_changes else None
            job = self.session.get(IngestionJob, change.job_id) if change and change.job_id else None
            if change is None:
                candidates = list(self.session.scalars(select(IngestionJob).where(
                    IngestionJob.document_id == document_id,
                    IngestionJob.state.in_(["READY_FOR_INDEX", "INDEX_QUEUED"]),
                ).order_by(IngestionJob.updated_at.desc())).all())
                if len(candidates) == 1:
                    job = candidates[0]
                    change = self.session.scalar(select(MetadataChangeRequest).where(
                        MetadataChangeRequest.job_id == job.id,
                        MetadataChangeRequest.status == "APPROVED",
                    ))
            if change is None:
                missing.append(document_id)
                continue
            if job is not None:
                if job.state == "FAILED":
                    raise JobConflictError(
                        f"制度 {document_id} 的入库任务处于失败状态，请重试原发布请求"
                    )
                if job.state not in {"READY_FOR_INDEX", "INDEX_QUEUED"}:
                    raise JobConflictError(
                        f"制度 {document_id} 的入库任务状态为 {job.state}，"
                        "请先在审核工作台完成分块审核"
                    )
            # 先给出可操作的Platform流程提示，再检查Knowledge侧精确来源。
            source = self.management.publication_source(
                document_id, int(change.metadata_revision_id)
            )
            if job is not None:
                if (job.parse_run_id, job.chunk_run_id) != (
                    source["parse_run_id"], source["chunk_run_id"]
                ):
                    raise JobConflictError(f"制度 {document_id} 的入库任务与知识侧active Run不一致")
            bindings.append((job, change, source))

        if missing:
            raise JobConflictError(f"以下制度尚未完成审核或没有待发布变更：{missing}")
        baseline = self.management.active_index_snapshot()
        frozen_sources: dict[int, dict[str, int | str | None]] = {
            int(source["document_id"]): {
                **source,
                "source_role": "BASELINE",
                "job_id": None,
            }
            for source in baseline["sources"]
        }
        for job, change, source in bindings:
            frozen_sources[int(source["document_id"])] = {
                **source,
                "metadata_revision_id": int(change.metadata_revision_id),
                "source_role": "CHANGE",
                "job_id": job.id if job else None,
            }

        request = IndexPublicationRequest(
            status="BUILD_QUEUED",
            snapshot_contract_version=EXACT_SNAPSHOT_CONTRACT,
            base_index_run_id=baseline["index_run_id"],
            source_document_ids_json=json.dumps(normalized),
            requested_by=actor_user_id,
        )
        self.session.add(request)
        self.session.flush()
        for document_id in sorted(frozen_sources):
            source = frozen_sources[document_id]
            self.session.add(IndexPublicationSource(
                publication_request_id=request.id,
                job_id=source["job_id"],
                source_role=str(source["source_role"]),
                document_id=int(source["document_id"]),
                parse_run_id=int(source["parse_run_id"]),
                chunk_run_id=int(source["chunk_run_id"]),
                metadata_revision_id=int(source["metadata_revision_id"]),
            ))
        for job, _change, _source in bindings:
            if job is not None and job.state == "READY_FOR_INDEX":
                self.ingestion.transition(
                    job, "INDEX_QUEUED", f"已加入索引发布请求 {request.id}", actor_user_id
                )
        self.session.commit()
        self.session.refresh(request)
        return request

    def bindings(self, request_id: str) -> list[IndexPublicationSource]:
        """按请求读取冻结的制度来源、知识版本和可选入库任务。"""

        return list(self.session.scalars(select(IndexPublicationSource).where(
            IndexPublicationSource.publication_request_id == request_id
        ).order_by(IndexPublicationSource.created_at)).all())

    def bound_sources(
        self, request_id: str
    ) -> list[tuple[IndexPublicationSource, IngestionJob | None]]:
        """返回精确来源及可选任务；指向不存在任务的绑定立即失败。"""

        result: list[tuple[IndexPublicationSource, IngestionJob | None]] = []
        for binding in self.bindings(request_id):
            job = self.session.get(IngestionJob, binding.job_id) if binding.job_id else None
            if binding.job_id and job is None:
                raise JobConflictError(f"发布任务绑定缺少入库任务：{binding.job_id}")
            result.append((binding, job))
        request = self._get(request_id)
        if request.snapshot_contract_version != EXACT_SNAPSHOT_CONTRACT:
            raise JobConflictError("历史发布请求不具备精确全量快照契约，仅供审计")
        requested_documents = set(self.document_ids(request))
        bound_documents = {int(binding.document_id) for binding, _job in result}
        change_documents = {
            int(binding.document_id)
            for binding, _job in result
            if binding.source_role == "CHANGE"
        }
        if not result or not requested_documents.issubset(bound_documents):
            raise JobConflictError(
                f"发布请求来源绑定不完整：requested={sorted(requested_documents)}, "
                f"bound={sorted(bound_documents)}"
            )
        if change_documents != requested_documents:
            raise JobConflictError(
                f"发布请求变更来源不一致：requested={sorted(requested_documents)}, "
                f"changes={sorted(change_documents)}"
            )
        return result

    def list(self) -> list[IndexPublicationRequest]:
        return list(self.session.scalars(
            select(IndexPublicationRequest).order_by(IndexPublicationRequest.created_at.desc())
        ).all())

    def has_complete_bindings(self, request_id: str) -> bool:
        """判断历史发布请求是否具备新编排所需的完整冻结来源。"""

        try:
            return bool(self.bound_sources(request_id))
        except JobConflictError:
            return False

    def queue_publish(self, request_id: str, actor_user_id: str) -> IndexPublicationRequest:
        request = self._get(request_id)
        if request.status != "READY_TO_PUBLISH" or request.index_run_id is None:
            raise JobConflictError("索引快照尚未完成全量核验")
        self.bound_sources(request.id)
        request.status = "PUBLISH_QUEUED"
        request.published_by = actor_user_id
        self.session.commit()
        self.session.refresh(request)
        return request

    def retry(self, request_id: str) -> IndexPublicationRequest:
        request = self._get(request_id)
        if request.status != "FAILED":
            raise JobConflictError("只有失败的发布请求可以重试")
        bound_sources = self.bound_sources(request.id)
        expected_state = "READY_TO_PUBLISH" if request.index_run_id else "INDEX_QUEUED"
        expected_failed_stage = "PUBLISHING" if request.index_run_id else "INDEXING"
        for _binding, job in bound_sources:
            if job is None:
                continue
            if job.state == "FAILED" and (
                not job.retryable
                or job.failed_stage != expected_failed_stage
                or RETRY_TARGETS.get(job.failed_stage) != expected_state
            ):
                raise JobConflictError(f"绑定任务 {job.id} 的失败阶段不能按原请求重试")
            if job.state not in {"FAILED", expected_state}:
                raise JobConflictError(f"绑定任务 {job.id} 当前状态不允许重试：{job.state}")
        for _binding, job in bound_sources:
            if job is None:
                continue
            if job.state == "FAILED":
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


def publication_dict(item: IndexPublicationRequest, *, can_retry: bool = False) -> dict:
    """输出不泄露平台内部路径的发布请求摘要。"""

    return {
        "id": item.id,
        "status": item.status,
        "snapshot_contract_version": item.snapshot_contract_version,
        "base_index_run_id": item.base_index_run_id,
        "document_ids": json.loads(item.source_document_ids_json),
        "index_run_id": item.index_run_id,
        "alias_name": item.alias_name,
        "requested_by": item.requested_by,
        "published_by": item.published_by,
        "error_summary": item.error_summary,
        "can_retry": can_retry,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "published_at": item.published_at,
    }
