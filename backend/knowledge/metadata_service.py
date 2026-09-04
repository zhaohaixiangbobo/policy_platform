"""文件说明：管理制度系列、正式文件版本和可审计元数据修订。

本服务只写 policy-platform 自有知识库。元数据在 Alias 成功切换前保持候选状态，
公开读取始终使用 active IndexRun 冻结的 metadata_revision_id。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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

    def __init__(self, database_path: Path) -> None:
        self.db = ParserDatabase(database_path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "KnowledgeMetadataService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            """
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
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_series(self) -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            """
            SELECT s.*, COUNT(d.id) AS document_count
            FROM policy_series s
            LEFT JOIN policy_document d ON d.series_id=s.id
            GROUP BY s.id ORDER BY s.updated_at DESC, s.id DESC
            """
        ).fetchall()
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
                cursor = self.db.connection.execute(
                    """
                    INSERT INTO policy_series (series_key, canonical_title, status, created_at, updated_at)
                    VALUES (?, ?, 'ACTIVE', ?, ?)
                    """,
                    (f"policy-series-{document_id}-{now}", title, now, now),
                )
                target_series_id = int(cursor.lastrowid)
            else:
                target = self.db.connection.execute(
                    "SELECT * FROM policy_series WHERE id=?", (series_id,)
                ).fetchone()
                if target is None:
                    raise LookupError("制度系列不存在")
                target_series_id = int(series_id)
                if canonical_title and canonical_title.strip() != str(target["canonical_title"]):
                    self.db.connection.execute(
                        "UPDATE policy_series SET canonical_title=?, updated_at=? WHERE id=?",
                        (canonical_title.strip(), now, target_series_id),
                    )
            version_no = int(self.db.connection.execute(
                """
                SELECT COALESCE(MAX(document_version_no), 0) + 1
                FROM policy_document WHERE series_id=? AND id!=?
                """,
                (target_series_id, document_id),
            ).fetchone()[0])
            self.db.connection.execute(
                """
                UPDATE policy_document
                SET series_id=?, document_version_no=?, updated_at=? WHERE id=?
                """,
                (target_series_id, version_no, now, document_id),
            )
        return self._document(document_id)

    def detail(self, document_id: int) -> dict[str, Any]:
        document = self._document(document_id)
        revisions = self.db.connection.execute(
            """
            SELECT * FROM document_metadata_revision
            WHERE document_id=? ORDER BY revision_no DESC
            """,
            (document_id,),
        ).fetchall()
        candidates = self.db.connection.execute(
            """
            SELECT ef.*, sb.page_start, sb.page_end
            FROM extracted_field ef
            LEFT JOIN source_block sb ON sb.id=ef.source_block_id
            WHERE ef.parse_run_id=(
                SELECT latest_parse_run_id FROM policy_document WHERE id=?
            )
            ORDER BY ef.field_name, ef.confidence DESC, ef.id
            """,
            (document_id,),
        ).fetchall()
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
                        self.db.connection.execute(
                            """
                            UPDATE document_metadata_revision
                            SET status=?, source_type=?, change_reason=?, content_hash=?, updated_at=?
                            WHERE id=?
                            """,
                            (
                                initial_document_status,
                                source_type,
                                change_reason,
                                self._content_hash(values),
                                now,
                                int(latest_id),
                            ),
                        )
                    return self._revision(int(latest_id))
                return latest
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
        next_no = int(self.db.connection.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM document_metadata_revision WHERE document_id=?",
            (document_id,),
        ).fetchone()[0])
        now = utc_now()
        parse_run_id = document.get("active_parse_run_id")
        content_hash = self._content_hash(values)
        with self.db.transaction():
            cursor = self.db.connection.execute(
                """
                INSERT INTO document_metadata_revision (
                    document_id, parse_run_id, revision_no, parent_revision_id, source_type,
                    title, document_code, document_type, issuing_org, addressee_text,
                    authority_level, publish_date, effective_date, expiry_date, status,
                    version, owner_department, confidentiality_level, lifecycle_status,
                    change_reason, content_hash, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'DRAFT', ?, ?, ?, ?, ?)
                """,
                (
                    document_id, parse_run_id, next_no, parent_revision_id, source_type,
                    *(values[field] for field in METADATA_FIELDS),
                    change_reason, content_hash, actor_user_id, now, now,
                ),
            )
            revision_id = int(cursor.lastrowid)
            self.db.connection.execute(
                "UPDATE policy_document SET latest_metadata_revision_id=?, updated_at=? WHERE id=?",
                (revision_id, now, document_id),
            )
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
        metadata = {field: merged.get(field) for field in METADATA_FIELDS}
        assignments = [f"{field}=?" for field in values]
        now = utc_now()
        assignments.extend(["content_hash=?", "updated_at=?"])
        with self.db.transaction():
            self.db.connection.execute(
                f"UPDATE document_metadata_revision SET {', '.join(assignments)} WHERE id=?",
                (*values.values(), self._content_hash(metadata), now, revision_id),
            )
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
        with self.db.transaction():
            self.db.connection.execute(
                """
                UPDATE document_metadata_revision
                SET lifecycle_status=?, reviewed_by=?, reviewed_at=?,
                    change_reason=COALESCE(?, change_reason), updated_at=?
                WHERE id=?
                """,
                (target, reviewer_user_id, now, comment, now, revision_id),
            )
            if approved:
                self.db.connection.execute(
                    """
                    UPDATE policy_document
                    SET approved_metadata_revision_id=?, updated_at=? WHERE id=?
                    """,
                    (revision_id, now, document_id),
                )
        return self._revision(revision_id)

    def _set_lifecycle(self, revision_id: int, lifecycle_status: str) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction():
            self.db.connection.execute(
                "UPDATE document_metadata_revision SET lifecycle_status=?, updated_at=? WHERE id=?",
                (lifecycle_status, now, revision_id),
            )
        return self._revision(revision_id)

    def _document(self, document_id: int) -> dict[str, Any]:
        row = self.db.connection.execute(
            """
            SELECT d.*, s.series_key, s.canonical_title
            FROM policy_document d
            LEFT JOIN policy_series s ON s.id=d.series_id
            WHERE d.id=?
            """,
            (document_id,),
        ).fetchone()
        if row is None:
            raise LookupError("制度文件不存在")
        return dict(row)

    def _revision(self, revision_id: int) -> dict[str, Any]:
        row = self.db.connection.execute(
            "SELECT * FROM document_metadata_revision WHERE id=?", (revision_id,)
        ).fetchone()
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
