"""文件说明：实现流程草稿、送审、固定审核人审核、管理员发布和历史修订只读规则。"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import EvidenceReference, PolicyProcess, ProcessRevision, utc_now
from app.application.evidence_reference_validator import EvidenceReferenceValidator
from app.application.evidence_binding_service import EvidenceBindingService


class ProcessConflictError(RuntimeError):
    """流程生命周期或审核身份不满足操作条件。"""


class ProcessService:
    def __init__(self, session: Session, evidence_validator: EvidenceReferenceValidator | None = None) -> None:
        self.session = session
        self.evidence_validator = evidence_validator
        self.evidence = EvidenceBindingService(session, evidence_validator) if evidence_validator else None

    def list(self) -> list[tuple[PolicyProcess, ProcessRevision]]:
        rows: list[tuple[PolicyProcess, ProcessRevision]] = []
        for process in self.session.scalars(select(PolicyProcess).order_by(PolicyProcess.updated_at.desc())).all():
            revision = self.session.get(ProcessRevision, process.current_revision_id) if process.current_revision_id else None
            if revision:
                rows.append((process, revision))
        return rows

    def create(self, name: str, description: str | None, actor_user_id: str) -> tuple[PolicyProcess, ProcessRevision]:
        process = PolicyProcess(name=name.strip(), description=description, created_by=actor_user_id)
        self.session.add(process)
        self.session.flush()
        revision = ProcessRevision(process_id=process.id, revision_no=1, created_by=actor_user_id)
        self.session.add(revision)
        self.session.flush()
        process.current_revision_id = revision.id
        self.session.commit()
        return process, revision

    def update_graph(self, process_id: str, graph: dict, change_summary: str | None, actor_user_id: str) -> tuple[PolicyProcess, ProcessRevision]:
        process, revision = self._current(process_id)
        if revision.status == "PUBLISHED":
            next_no = int(self.session.scalar(select(func.max(ProcessRevision.revision_no)).where(ProcessRevision.process_id == process.id)) or 0) + 1
            revision = ProcessRevision(process_id=process.id, revision_no=next_no, created_by=actor_user_id, graph_json=json.dumps(graph, ensure_ascii=False), change_summary=change_summary)
            self.session.add(revision)
            self.session.flush()
            process.current_revision_id = revision.id
        elif revision.status == "DRAFT":
            revision.graph_json = json.dumps(graph, ensure_ascii=False)
            revision.change_summary = change_summary
        else:
            raise ProcessConflictError("仅草稿可编辑；已发布流程修改时会创建新修订")
        process.updated_at = utc_now()
        self.session.commit()
        return process, revision

    def submit(self, process_id: str) -> tuple[PolicyProcess, ProcessRevision]:
        process, revision = self._current(process_id)
        if revision.status != "DRAFT":
            raise ProcessConflictError("仅草稿可以提交审核")
        graph = json.loads(revision.graph_json)
        if not graph.get("nodes"):
            raise ProcessConflictError("流程至少需要一个节点")
        self._validate_evidence(revision)
        revision.status = "PENDING_REVIEW"
        self.session.commit()
        return process, revision

    def review(self, process_id: str, actor_user_id: str, fixed_reviewer_user_id: str | None, approved: bool) -> tuple[PolicyProcess, ProcessRevision]:
        process, revision = self._current(process_id)
        if revision.status != "PENDING_REVIEW":
            raise ProcessConflictError("流程当前不在待审核状态")
        if not fixed_reviewer_user_id or actor_user_id != fixed_reviewer_user_id:
            raise ProcessConflictError("当前用户不是固定流程审核管理员")
        revision.status = "APPROVED" if approved else "DRAFT"
        revision.reviewed_by = actor_user_id
        revision.reviewed_at = utc_now()
        self.session.commit()
        return process, revision

    def publish(self, process_id: str, actor_user_id: str) -> tuple[PolicyProcess, ProcessRevision]:
        process, revision = self._current(process_id)
        if revision.status != "APPROVED":
            raise ProcessConflictError("仅已审核流程可以发布")
        self._validate_evidence(revision)
        revision.status = "PUBLISHED"
        revision.published_by = actor_user_id
        revision.published_at = utc_now()
        process.published_revision_id = revision.id
        self.session.commit()
        return process, revision

    def list_evidence(self, process_id: str) -> list[EvidenceReference]:
        """详情打开时统一执行证据失效检查。"""

        _process, revision = self._current(process_id)
        if not self.evidence:
            return []
        return self.evidence.list(["PROCESS_NODE", "PROCESS_EDGE"], f"{revision.id}:")

    def bind_evidence(
        self,
        process_id: str,
        owner_kind: str,
        cell_id: str,
        payload: dict,
        actor_user_id: str,
    ) -> EvidenceReference:
        _process, revision = self._current(process_id)
        if revision.status != "DRAFT":
            raise ProcessConflictError("仅草稿修订可绑定制度证据")
        graph = json.loads(revision.graph_json)
        collection = graph.get("nodes", []) if owner_kind == "NODE" else graph.get("edges", [])
        if cell_id not in {str(item.get("id")) for item in collection if isinstance(item, dict)}:
            raise ProcessConflictError("流程图中不存在指定节点或连线")
        if not self.evidence:
            raise ProcessConflictError("证据验证服务不可用")
        return self.evidence.bind(
            owner_type="PROCESS_NODE" if owner_kind == "NODE" else "PROCESS_EDGE",
            owner_id=f"{revision.id}:{cell_id}",
            actor_user_id=actor_user_id,
            **payload,
        )

    def delete_evidence(self, process_id: str, reference_id: str) -> None:
        _process, revision = self._current(process_id)
        if revision.status != "DRAFT":
            raise ProcessConflictError("仅草稿修订可删除制度证据")
        if not self.evidence:
            raise ProcessConflictError("证据验证服务不可用")
        self.evidence.delete(reference_id, f"{revision.id}:")

    def _current(self, process_id: str) -> tuple[PolicyProcess, ProcessRevision]:
        process = self.session.get(PolicyProcess, process_id)
        if process is None or not process.current_revision_id:
            raise LookupError("流程不存在")
        revision = self.session.get(ProcessRevision, process.current_revision_id)
        if revision is None:
            raise LookupError("流程修订不存在")
        return process, revision

    def _validate_evidence(self, revision: ProcessRevision) -> None:
        """送审和发布前复用同一跨库证据有效性规则。"""

        if not self.evidence_validator:
            return
        references = self.session.scalars(select(EvidenceReference).where(EvidenceReference.owner_type.in_(["PROCESS_NODE", "PROCESS_EDGE"]), EvidenceReference.owner_id.like(f"{revision.id}:%"))).all()
        invalid: list[str] = []
        for reference in references:
            result = self.evidence_validator.validate(reference.document_id, reference.parse_run_id, reference.primary_node_id, reference.quote_snapshot, reference.snapshot_hash)
            reference.validation_status = result.status
            reference.validated_at = utc_now()
            if result.status != "VALID":
                invalid.append(f"{reference.id}:{result.status}")
        if invalid:
            self.session.commit()
            raise ProcessConflictError(f"存在失效制度证据：{', '.join(invalid)}")
