"""文件说明：管理制度系列、正式文件版本和可审计元数据修订。

本服务只写 policy-platform 自有知识库。元数据在 Alias 成功切换前保持候选状态，
公开读取始终使用 active IndexRun 冻结的 metadata_revision_id。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from knowledge.metadata_rules import required_status_for_source, status_transition_error
from knowledge.parser.database import ParserDatabase, utc_now


METADATA_FIELDS = (
    "title", "document_code", "document_type", "issuing_org", "addressee_text",
    "authority_level", "publish_date", "effective_date", "expiry_date", "status",
    "version", "owner_department", "confidentiality_level",
)
REVISION_EDIT_FIELDS = frozenset((*METADATA_FIELDS, "change_reason", "repeal_date", "repeal_reason", "repeal_evidence", "status_confirmation_note"))


class MetadataConflictError(RuntimeError):
    """元数据修订状态或内容不满足操作要求。"""


class KnowledgeMetadataService:
    """制度系列及元数据修订仓储服务。"""

    def __init__(self, database_url: str) -> None:
        self.db = ParserDatabase(database_url)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "KnowledgeMetadataService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self.db.repository.run(sql_text("""
            SELECT d.id, d.file_name, d.series_id, d.document_version_no,
                   d.active_parse_run_id, d.active_chunk_run_id,
                   s.series_key, s.canonical_title,
                   latest.id AS latest_metadata_revision_id,
                   latest.title, latest.document_code, latest.issuing_org,
                   latest.owner_department, latest.publish_date, latest.status,
                   latest.lifecycle_status AS metadata_status,
                   d.approved_metadata_revision_id, d.active_metadata_revision_id,
                   d.updated_at
            FROM policy_document d
            JOIN policy_series s ON s.id=d.series_id
            LEFT JOIN document_metadata_revision latest ON latest.id=d.latest_metadata_revision_id
            ORDER BY d.updated_at DESC, d.id DESC
            """)).mappings().fetchall()
        return [dict(row) for row in rows]

    def list_series(self) -> list[dict[str, Any]]:
        rows = self.db.repository.run(sql_text("""
            SELECT s.*, COUNT(d.id) AS document_count
            FROM policy_series s
            LEFT JOIN policy_document d ON d.series_id=s.id
            GROUP BY s.id ORDER BY s.updated_at DESC, s.id DESC
            """)).mappings().fetchall()
        return [dict(row) for row in rows]

    def assign_series(
        self,
        document_id: int,
        *,
        series_id: int | None,
        canonical_title: str | None,
    ) -> dict[str, Any]:
        """把具体正式文件版本归入既有制度系列，或建立新的系列。"""

        document = self._document(document_id)
        now = utc_now()
        with self.db.transaction():
            if series_id is None:
                title = str(canonical_title or document.get("title") or document.get("file_name") or "").strip()
                if not title:
                    raise ValueError("新制度系列名称不能为空")
                cursor = self.db.repository.run(sql_text("""
                    INSERT INTO policy_series (series_key, canonical_title, status, created_at, updated_at)
                    VALUES (:p0, :p1, 'ACTIVE', :p2, :p3) RETURNING id"""), {'p0': f"policy-series-{document_id}-{now}", 'p1': title, 'p2': now, 'p3': now})
                target_series_id = int(cursor.scalar_one())
            else:
                target = self.db.repository.run(sql_text('SELECT * FROM policy_series WHERE id=:p0'), {'p0': series_id}).mappings().fetchone()
                if target is None:
                    raise LookupError("制度系列不存在")
                target_series_id = int(series_id)
                if canonical_title and canonical_title.strip() != str(target["canonical_title"]):
                    self.db.repository.run(sql_text('UPDATE policy_series SET canonical_title=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': canonical_title.strip(), 'p1': now, 'p2': target_series_id})
            version_no = int(self.db.repository.run(sql_text("""
                SELECT COALESCE(MAX(document_version_no), 0) + 1
                FROM policy_document WHERE series_id=:p0 AND id!=:p1
                """), {'p0': target_series_id, 'p1': document_id}).scalar_one())
            self.db.repository.run(sql_text("""
                UPDATE policy_document
                SET series_id=:p0, document_version_no=:p1, updated_at=:p2 WHERE id=:p3
                """), {'p0': target_series_id, 'p1': version_no, 'p2': now, 'p3': document_id})
        return self._document(document_id)

    def detail(self, document_id: int) -> dict[str, Any]:
        document = self._document(document_id)
        revisions = self.db.repository.run(sql_text("""
            SELECT * FROM document_metadata_revision
            WHERE document_id=:p0 ORDER BY revision_no DESC
            """), {'p0': document_id}).mappings().fetchall()
        candidates = self.db.repository.run(sql_text("""
            SELECT ef.*, sb.page_start, sb.page_end
            FROM extracted_field ef
            LEFT JOIN source_block sb ON sb.id=ef.source_block_id
            WHERE ef.parse_run_id=(
                SELECT latest_parse_run_id FROM policy_document WHERE id=:p0
            )
            ORDER BY ef.field_name, ef.confidence DESC, ef.id
            """), {'p0': document_id}).mappings().fetchall()
        return {
            "document": document,
            "revisions": [dict(row) for row in revisions],
            "candidates": [dict(row) for row in candidates],
        }

    def ensure_draft(
        self,
        document_id: int,
        actor_user_id: str,
        *,
        source_type: str = "MANUAL_CORRECTION",
        change_reason: str | None = None,
        initial_document_status: str | None = None,
    ) -> dict[str, Any]:
        """返回现有草稿，或从当前有效/最新元数据复制新修订。"""

        document = self._document(document_id)
        active_parse_run_id = document.get("active_parse_run_id")
        if active_parse_run_id is None:
            raise MetadataConflictError("制度尚无已批准的active ParseRun，不能创建元数据草稿")
        if source_type in {"MANUAL_CORRECTION", "REPEAL", "EXPIRY"} and not (
            document.get("approved_metadata_revision_id")
            or document.get("active_metadata_revision_id")
        ):
            raise MetadataConflictError("制度尚无已批准元数据，不能创建修订或登记废止")
        if source_type in {"REPEAL", "EXPIRY"}:
            active_revision_id = document.get("active_metadata_revision_id")
            if active_revision_id is None:
                raise MetadataConflictError("制度尚未正式发布，不能登记废止或失效")
            active_revision = self._revision(int(active_revision_id))
            if str(active_revision.get("status") or "").lower() != "effective":
                raise MetadataConflictError("只有现行有效制度可以登记废止或失效")
        latest_id = document.get("latest_metadata_revision_id")
        if latest_id:
            latest = self._revision(int(latest_id))
            if latest["lifecycle_status"] == "DRAFT":
                if (
                    initial_document_status is not None
                    and not document.get("approved_metadata_revision_id")
                    and not document.get("active_metadata_revision_id")
                    and latest.get("source_type") == "BACKFILL"
                ):
                    if initial_document_status not in {"effective", "repealed", "expired"}:
                        raise ValueError("上传声明值不是受支持的制度状态")
                    values = {field: latest.get(field) for field in METADATA_FIELDS}
                    values["status"] = initial_document_status
                    now = utc_now()
                    with self.db.transaction():
                        self.db.repository.run(sql_text("""
                            UPDATE document_metadata_revision
                            SET parse_run_id=:p0,status=:p1,source_type=:p2,change_reason=:p3,content_hash=:p4,updated_at=:p5
                            WHERE id=:p6
                            """), {'p0': int(active_parse_run_id), 'p1': initial_document_status, 'p2': source_type, 'p3': change_reason, 'p4': self._content_hash(values), 'p5': now, 'p6': int(latest_id)})
                    return self._revision(int(latest_id))
                same_initial = (
                    initial_document_status is not None
                    and latest.get("source_type") == "PARSE_EXTRACTED"
                    and int(latest.get("parse_run_id") or 0) == int(active_parse_run_id)
                )
                if same_initial or (
                    initial_document_status is None and latest.get("source_type") == source_type
                ):
                    required_status = required_status_for_source(source_type)
                    draft_updates: dict[str, Any] = {}
                    if (
                        required_status is not None
                        and str(latest.get("status") or "").lower() != required_status
                    ):
                        draft_updates["status"] = required_status
                    if source_type == "REPEAL" and not latest.get("repeal_date"):
                        draft_updates["repeal_date"] = date.today().isoformat()
                    if draft_updates:
                        # 旧版本创建的错误草稿仍可在提交前按新契约安全归正。
                        return self.update_draft(document_id, int(latest_id), draft_updates)
                    return latest
                raise MetadataConflictError(
                    f"当前存在待处理的 {latest.get('source_type')} 草稿，不能创建 {source_type} 修订"
                )
        base_id = document.get("approved_metadata_revision_id") or document.get("active_metadata_revision_id") or latest_id
        if base_id:
            base = self._revision(int(base_id))
            values = {field: base.get(field) for field in METADATA_FIELDS}
            parent_revision_id = int(base["id"])
        else:
            values = {field: document.get(field) for field in METADATA_FIELDS}
            parent_revision_id = None
            if initial_document_status is not None:
                if initial_document_status not in {"effective", "repealed", "expired"}:
                    raise ValueError("上传声明值不是受支持的制度状态")
                # 仅首份 INITIAL 草稿采用上传声明，后续修订始终继承已审核元数据。
                values["status"] = initial_document_status
        required_status = required_status_for_source(source_type)
        if required_status is not None:
            # 生命周期动作在创建草稿时即写入确定状态，不继承原制度的effective。
            values["status"] = required_status
        repeal_date = date.today().isoformat() if source_type == "REPEAL" else None
        next_no = int(self.db.repository.run(sql_text('SELECT COALESCE(MAX(revision_no), 0) + 1 FROM document_metadata_revision WHERE document_id=:p0'), {'p0': document_id}).scalar_one())
        now = utc_now()
        parse_run_id = int(active_parse_run_id)
        content_hash = self._content_hash(values)
        with self.db.transaction():
            cursor = self.db.repository.run(sql_text("""
                INSERT INTO document_metadata_revision (
                    document_id, parse_run_id, revision_no, parent_revision_id, source_type,
                    title, document_code, document_type, issuing_org, addressee_text,
                    authority_level, publish_date, effective_date, expiry_date, status,
                    version, owner_department, confidentiality_level, lifecycle_status,
                    change_reason, repeal_date, content_hash, created_by, created_at, updated_at
                ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14, :p15, :p16, :p17,
                          'DRAFT', :p18, :p19, :p20, :p21, :p22, :p23) RETURNING id"""), dict(zip(('p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13', 'p14', 'p15', 'p16', 'p17', 'p18', 'p19', 'p20', 'p21', 'p22', 'p23'), (
                    document_id, parse_run_id, next_no, parent_revision_id, source_type,
                    *(values[field] for field in METADATA_FIELDS),
                    change_reason, repeal_date, content_hash, actor_user_id, now, now,
                ), strict=True)))
            revision_id = int(cursor.scalar_one())
            self.db.repository.run(sql_text('UPDATE policy_document SET latest_metadata_revision_id=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': revision_id, 'p1': now, 'p2': document_id})
        return self._revision(revision_id)

    def update_draft(self, document_id: int, revision_id: int, values: dict[str, Any]) -> dict[str, Any]:
        revision = self._owned_revision(document_id, revision_id)
        if revision["lifecycle_status"] != "DRAFT":
            raise MetadataConflictError("只有草稿元数据可以修改")
        unknown = set(values) - REVISION_EDIT_FIELDS
        if unknown:
            raise ValueError(f"包含不支持的元数据字段：{sorted(unknown)}")
        merged = dict(revision)
        merged.update(values)
        transition_error = status_transition_error(
            str(revision.get("source_type") or ""), merged.get("status")
        )
        if transition_error:
            raise MetadataConflictError(transition_error)
        if revision.get("source_type") == "MANUAL_CORRECTION" and "status" in values:
            parent_id = revision.get("parent_revision_id")
            parent_status = (
                str(self._revision(int(parent_id)).get("status") or "unknown").lower()
                if parent_id is not None
                else str(revision.get("status") or "unknown").lower()
            )
            if str(merged.get("status") or "unknown").lower() != parent_status:
                raise MetadataConflictError("制度效力状态必须通过登记废止或登记失效流程变更")
        metadata = {field: merged.get(field) for field in METADATA_FIELDS}
        now = utc_now()
        with self.db.transaction():
            table = knowledge_metadata.tables["document_metadata_revision"]
            self.db.repository.run(update(table).where(table.c.id == revision_id).values(**values, content_hash=self._content_hash(metadata), updated_at=now))
        return self._revision(revision_id)

    def submit(self, document_id: int, revision_id: int) -> dict[str, Any]:
        revision = self._owned_revision(document_id, revision_id)
        if revision["lifecycle_status"] != "DRAFT":
            raise MetadataConflictError("只有草稿可以提交审核")
        missing = [
            label for field, label in (
                ("title", "制度名称"), ("issuing_org", "发布机构"),
                ("owner_department", "责任部门"), ("publish_date", "发布日期"),
            ) if not str(revision.get(field) or "").strip()
        ]
        if missing:
            raise MetadataConflictError(f"以下元数据尚未确认：{'、'.join(missing)}")
        status = str(revision.get("status") or "unknown").strip().lower()
        if status == "unknown" and not str(revision.get("status_confirmation_note") or "").strip():
            raise MetadataConflictError("制度状态为待确认时必须填写保留原因")
        self._validate_lifecycle_revision(revision, require_details=True)
        return self._set_lifecycle(revision_id, "PENDING_REVIEW")

    def review(
        self,
        document_id: int,
        revision_id: int,
        approved: bool,
        reviewer_user_id: str,
        comment: str | None,
    ) -> dict[str, Any]:
        revision = self._owned_revision(document_id, revision_id)
        if revision["lifecycle_status"] != "PENDING_REVIEW":
            raise MetadataConflictError("元数据修订当前不在待审核状态")
        now = utc_now()
        target = "APPROVED" if approved else "REJECTED"
        if not approved and not str(comment or "").strip():
            raise MetadataConflictError("驳回元数据必须填写原因")
        if approved:
            self._validate_lifecycle_revision(revision, require_details=True)
        with self.db.transaction():
            self.db.repository.run(sql_text("""
                UPDATE document_metadata_revision
                SET lifecycle_status=:p0, reviewed_by=:p1, reviewed_at=:p2,
                    change_reason=COALESCE(:p3, change_reason), updated_at=:p4
                WHERE id=:p5
                """), {'p0': target, 'p1': reviewer_user_id, 'p2': now, 'p3': comment, 'p4': now, 'p5': revision_id})
            if approved:
                self.db.repository.run(sql_text("""
                    UPDATE policy_document
                    SET approved_metadata_revision_id=:p0, updated_at=:p1 WHERE id=:p2
                    """), {'p0': revision_id, 'p1': now, 'p2': document_id})
        return self._revision(revision_id)

    def withdraw(self, document_id: int, revision_id: int) -> dict[str, Any]:
        """撤回尚未发布的人工修订，并恢复稳定的已批准指针。"""

        revision = self._owned_revision(document_id, revision_id)
        lifecycle_status = str(revision.get("lifecycle_status") or "")
        if lifecycle_status == "WITHDRAWN":
            return revision
        if lifecycle_status not in {"DRAFT", "PENDING_REVIEW", "APPROVED"}:
            raise MetadataConflictError("只有尚未发布的元数据修订可以撤回")
        if str(revision.get("source_type") or "") == "PARSE_EXTRACTED":
            raise MetadataConflictError("首次入库元数据不能撤回，请在审核流程中驳回")

        document = self._document(document_id)
        approved_id = document.get("approved_metadata_revision_id")
        fallback_approved_id = document.get("active_metadata_revision_id")
        now = utc_now()
        with self.db.transaction():
            self.db.repository.run(sql_text("""
                UPDATE document_metadata_revision
                SET lifecycle_status='WITHDRAWN', updated_at=:p0
                WHERE id=:p1
                """), {'p0': now, 'p1': revision_id})
            if approved_id is not None and int(approved_id) == revision_id:
                self.db.repository.run(sql_text("""
                    UPDATE policy_document
                    SET approved_metadata_revision_id=:p0, updated_at=:p1 WHERE id=:p2
                    """), {'p0': fallback_approved_id, 'p1': now, 'p2': document_id})
        return self._revision(revision_id)

    @staticmethod
    def _validate_lifecycle_revision(
        revision: dict[str, Any], *, require_details: bool
    ) -> None:
        """保证废止和失效修订在提交、审核时仍满足完整业务契约。"""

        source_type = str(revision.get("source_type") or "")
        transition_error = status_transition_error(source_type, revision.get("status"))
        if transition_error:
            raise MetadataConflictError(transition_error)
        if not require_details:
            return
        if source_type == "REPEAL":
            missing = [
                label
                for field, label in (
                    ("repeal_date", "废止日期"),
                    ("repeal_reason", "废止原因"),
                    ("repeal_evidence", "废止依据"),
                )
                if not str(revision.get(field) or "").strip()
            ]
            if missing:
                raise MetadataConflictError(f"登记废止尚缺少：{'、'.join(missing)}")
            KnowledgeMetadataService._validate_iso_date(
                revision.get("repeal_date"), "废止日期"
            )
        elif source_type == "EXPIRY":
            missing = [
                label
                for field, label in (
                    ("expiry_date", "失效日期"),
                    ("change_reason", "失效说明"),
                )
                if not str(revision.get(field) or "").strip()
            ]
            if missing:
                raise MetadataConflictError(f"登记失效尚缺少：{'、'.join(missing)}")
            KnowledgeMetadataService._validate_iso_date(
                revision.get("expiry_date"), "失效日期"
            )

    @staticmethod
    def _validate_iso_date(value: Any, label: str) -> None:
        """审核边界统一接受 YYYY-MM-DD，避免浏览器以外的调用写入任意文本。"""

        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise MetadataConflictError(f"{label}必须是YYYY-MM-DD格式") from exc

    def _set_lifecycle(self, revision_id: int, lifecycle_status: str) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction():
            self.db.repository.run(sql_text('UPDATE document_metadata_revision SET lifecycle_status=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': lifecycle_status, 'p1': now, 'p2': revision_id})
        return self._revision(revision_id)

    def _document(self, document_id: int) -> dict[str, Any]:
        row = self.db.repository.run(sql_text("""
            SELECT d.*, s.series_key, s.canonical_title
            FROM policy_document d
            LEFT JOIN policy_series s ON s.id=d.series_id
            WHERE d.id=:p0
            """), {'p0': document_id}).mappings().fetchone()
        if row is None:
            raise LookupError("制度文件不存在")
        return dict(row)

    def _revision(self, revision_id: int) -> dict[str, Any]:
        row = self.db.repository.run(sql_text('SELECT * FROM document_metadata_revision WHERE id=:p0'), {'p0': revision_id}).mappings().fetchone()
        if row is None:
            raise LookupError("元数据修订不存在")
        return dict(row)

    def _owned_revision(self, document_id: int, revision_id: int) -> dict[str, Any]:
        revision = self._revision(revision_id)
        if int(revision["document_id"]) != document_id:
            raise MetadataConflictError("元数据修订不属于该制度文件")
        return revision

    @staticmethod
    def _content_hash(values: dict[str, Any]) -> str:
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
