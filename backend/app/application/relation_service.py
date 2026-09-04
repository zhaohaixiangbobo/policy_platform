"""文件说明：实现制度关系草稿、送审、人工确认和证据失效复核。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.evidence_binding_service import EvidenceBindingService
from app.infrastructure.db.models import EvidenceReference, PolicyRelation, ReviewRecord, utc_now


RELATION_TYPES = {"CITES", "SUPERSEDES", "REPEALS", "RELATED_TOPIC", "CONFLICTS_WITH"}


class RelationConflictError(RuntimeError):
    """关系生命周期、版本或证据不满足操作条件。"""


class RelationService:
    def __init__(self, session: Session, evidence: EvidenceBindingService) -> None:
        self.session = session
        self.evidence = evidence

    def list(self) -> list[PolicyRelation]:
        items = list(self.session.scalars(select(PolicyRelation).order_by(PolicyRelation.updated_at.desc())).all())
        for item in items:
            references = self.evidence.list(["POLICY_RELATION"], item.id)
            if item.status == "CONFIRMED" and any(ref.validation_status != "VALID" for ref in references):
                item.status = "NEEDS_REVIEW"
        self.session.commit()
        return items

    def create(
        self,
        relation_type: str,
        source_document_id: int,
        source_parse_run_id: int,
        target_document_id: int,
        target_parse_run_id: int,
        rationale: str | None,
        valid_from: datetime | None,
        valid_to: datetime | None,
        actor_user_id: str,
    ) -> PolicyRelation:
        if relation_type not in RELATION_TYPES:
            raise ValueError("关系类型不在受控枚举中")
        if source_document_id == target_document_id:
            raise ValueError("源制度和目标制度不能相同")
        if valid_from and valid_to and valid_from > valid_to:
            raise ValueError("关系有效期起始时间不能晚于结束时间")
        for document_id, parse_run_id in (
            (source_document_id, source_parse_run_id),
            (target_document_id, target_parse_run_id),
        ):
            result = self.evidence.validator.validate_document_version(document_id, parse_run_id)
            if result.status != "VALID":
                raise ValueError(f"制度版本无效：{result.reason}")
        item = PolicyRelation(
            relation_type=relation_type,
            source_document_id=source_document_id,
            source_parse_run_id=source_parse_run_id,
            target_document_id=target_document_id,
            target_parse_run_id=target_parse_run_id,
            rationale=rationale,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=actor_user_id,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def submit(self, relation_id: str) -> PolicyRelation:
        item = self._get(relation_id)
        if item.status not in {"DRAFT", "NEEDS_REVIEW"}:
            raise RelationConflictError("仅草稿或待复核关系可提交审核")
        references = self.evidence.list(["POLICY_RELATION"], item.id)
        if not references:
            raise RelationConflictError("关系至少需要一条制度证据")
        if any(reference.validation_status != "VALID" for reference in references):
            raise RelationConflictError("关系存在失效制度证据")
        item.status = "PENDING_REVIEW"
        self.session.commit()
        return item

    def review(self, relation_id: str, approved: bool, comment: str | None, reviewer_user_id: str) -> PolicyRelation:
        item = self._get(relation_id)
        if item.status != "PENDING_REVIEW":
            raise RelationConflictError("关系当前不在待审核状态")
        references = self.evidence.list(["POLICY_RELATION"], item.id)
        if approved and any(reference.validation_status != "VALID" for reference in references):
            raise RelationConflictError("关系存在失效制度证据")
        item.status = "CONFIRMED" if approved else "REJECTED"
        item.reviewed_by = reviewer_user_id
        item.reviewed_at = utc_now()
        self.session.add(ReviewRecord(
            target_type="POLICY_RELATION",
            target_id=item.id,
            outcome="PASS" if approved else "REJECT",
            comment=comment,
            reviewer_user_id=reviewer_user_id,
        ))
        self.session.commit()
        return item

    def _get(self, relation_id: str) -> PolicyRelation:
        item = self.session.get(PolicyRelation, relation_id)
        if item is None:
            raise LookupError("制度关系不存在")
        return item
