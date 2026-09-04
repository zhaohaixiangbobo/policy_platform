"""文件说明：统一创建、读取、删除和复核关系/流程的版本化证据快照。"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.evidence_reference_validator import EvidenceReferenceValidator
from app.infrastructure.db.models import EvidenceReference, utc_now


class EvidenceBindingService:
    """所有跨库证据绑定均在此处完成即时有效性检查。"""

    def __init__(self, session: Session, validator: EvidenceReferenceValidator) -> None:
        self.session = session
        self.validator = validator

    def list(self, owner_types: list[str], owner_prefix: str) -> list[EvidenceReference]:
        items = list(
            self.session.scalars(
                select(EvidenceReference).where(
                    EvidenceReference.owner_type.in_(owner_types),
                    EvidenceReference.owner_id.like(f"{owner_prefix}%"),
                ).order_by(EvidenceReference.created_at)
            ).all()
        )
        for item in items:
            self._validate(item)
        self.session.commit()
        return items

    def bind(
        self,
        *,
        owner_type: str,
        owner_id: str,
        document_id: int,
        parse_run_id: int,
        primary_node_id: int,
        page_start: int | None,
        page_end: int | None,
        quote_snapshot: str,
        actor_user_id: str,
    ) -> EvidenceReference:
        quote = quote_snapshot.strip()
        if not quote:
            raise ValueError("证据原文不能为空")
        digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        result = self.validator.validate(document_id, parse_run_id, primary_node_id, quote, digest)
        if result.status != "VALID":
            raise ValueError(f"制度证据无效：{result.reason}")
        duplicate = self.session.scalar(
            select(EvidenceReference).where(
                EvidenceReference.owner_type == owner_type,
                EvidenceReference.owner_id == owner_id,
                EvidenceReference.document_id == document_id,
                EvidenceReference.parse_run_id == parse_run_id,
                EvidenceReference.primary_node_id == primary_node_id,
                EvidenceReference.snapshot_hash == digest,
            )
        )
        if duplicate:
            return duplicate
        item = EvidenceReference(
            owner_type=owner_type,
            owner_id=owner_id,
            document_id=document_id,
            parse_run_id=parse_run_id,
            primary_node_id=primary_node_id,
            page_start=page_start,
            page_end=page_end,
            quote_snapshot=quote,
            snapshot_hash=digest,
            validation_status="VALID",
            validated_at=utc_now(),
            created_by=actor_user_id,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def delete(self, reference_id: str, owner_prefix: str) -> None:
        item = self.session.get(EvidenceReference, reference_id)
        if item is None or not item.owner_id.startswith(owner_prefix):
            raise LookupError("证据绑定不存在")
        self.session.delete(item)
        self.session.commit()

    def _validate(self, item: EvidenceReference) -> None:
        result = self.validator.validate(
            item.document_id,
            item.parse_run_id,
            item.primary_node_id,
            item.quote_snapshot,
            item.snapshot_hash,
        )
        item.validation_status = result.status
        item.validated_at = utc_now()
