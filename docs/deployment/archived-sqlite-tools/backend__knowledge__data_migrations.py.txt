"""文件说明：提供显式、带版本记录的知识库业务数据迁移，不在数据库构造时自动执行。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge.parser.database import ParserDatabase, utc_now


HISTORICAL_METADATA_MIGRATION = "20260904_historical_published_metadata_v1"
METADATA_FIELDS = (
    "title", "document_code", "document_type", "issuing_org", "addressee_text",
    "authority_level", "publish_date", "effective_date", "expiry_date", "status",
    "version", "owner_department", "confidentiality_level",
)


def _content_hash(values: dict[str, Any]) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def migrate_historical_published_metadata(database_path: Path) -> dict[str, Any]:
    """只为active IndexRun中的历史正式文档补齐系列和首份已发布元数据。"""

    with ParserDatabase(database_path) as database:
        database.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_data_migration (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
            """
        )
        existing = database.connection.execute(
            "SELECT details_json FROM knowledge_data_migration WHERE version=?",
            (HISTORICAL_METADATA_MIGRATION,),
        ).fetchone()
        if existing:
            return {"version": HISTORICAL_METADATA_MIGRATION, "applied": False, "details": json.loads(existing[0])}

        has_index_source = database.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_run_source'"
        ).fetchone()
        documents = database.connection.execute(
            """
            SELECT DISTINCT d.*
            FROM policy_document d
            JOIN index_profile ip ON ip.active_index_run_id IS NOT NULL
            JOIN index_run_source src
              ON src.index_run_id=ip.active_index_run_id AND src.document_id=d.id
            WHERE d.latest_metadata_revision_id IS NULL
            ORDER BY d.id
            """
        ).fetchall() if has_index_source else []

        migrated_ids: list[int] = []
        with database.transaction():
            for document in documents:
                document_id = int(document["id"])
                if document["active_parse_run_id"] is None:
                    raise RuntimeError(f"历史正式制度 {document_id} 缺少active ParseRun")
                database.ensure_document_series(document_id)
                values = {name: document[name] for name in METADATA_FIELDS}
                values["status"] = values["status"] or "unknown"
                now = utc_now()
                cursor = database.connection.execute(
                    """
                    INSERT INTO document_metadata_revision (
                        document_id,parse_run_id,revision_no,source_type,title,document_code,
                        document_type,issuing_org,addressee_text,authority_level,publish_date,
                        effective_date,expiry_date,status,version,owner_department,
                        confidentiality_level,lifecycle_status,content_hash,published_at,
                        created_at,updated_at
                    ) VALUES (?,?,1,'BACKFILL',?,?,?,?,?,?,?,?,?,?,?,?,?,'PUBLISHED',?,?,?,?)
                    """,
                    (
                        document_id, int(document["active_parse_run_id"]),
                        *(values[name] for name in METADATA_FIELDS),
                        _content_hash(values), now, now, now,
                    ),
                )
                revision_id = int(cursor.lastrowid)
                database.connection.execute(
                    """
                    UPDATE policy_document
                    SET latest_metadata_revision_id=?,approved_metadata_revision_id=?,
                        active_metadata_revision_id=? WHERE id=?
                    """,
                    (revision_id, revision_id, revision_id, document_id),
                )
                database.connection.execute(
                    """
                    UPDATE index_run_source
                    SET metadata_revision_id=?
                    WHERE document_id=? AND index_run_id IN (
                        SELECT active_index_run_id FROM index_profile
                        WHERE active_index_run_id IS NOT NULL
                    )
                    """,
                    (revision_id, document_id),
                )
                migrated_ids.append(document_id)
            details = {"migrated_document_ids": migrated_ids, "count": len(migrated_ids)}
            database.connection.execute(
                "INSERT INTO knowledge_data_migration(version,applied_at,details_json) VALUES (?,?,?)",
                (HISTORICAL_METADATA_MIGRATION, utc_now(), json.dumps(details, ensure_ascii=False)),
            )
        return {"version": HISTORICAL_METADATA_MIGRATION, "applied": True, "details": details}
