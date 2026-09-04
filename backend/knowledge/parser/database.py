"""SQLite 数据访问层。

该文件创建并维护解析设计文档中定义的 Document、ParseRun、SourceBlock、
Node、Chunk、来源映射、字段候选和校验问题，所有文本均按 UTF-8 语义处理。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


def utc_now() -> str:
    """返回带时区的 ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ParserDatabase:
    """解析结果的 SQLite 仓储。"""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """将一个解析阶段包装成事务，失败时只回滚当前阶段。"""

        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS policy_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_key TEXT NOT NULL UNIQUE,
                canonical_title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS policy_document (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                document_code TEXT,
                document_type TEXT,
                issuing_org TEXT,
                addressee_text TEXT,
                authority_level TEXT,
                publish_date TEXT,
                effective_date TEXT,
                expiry_date TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                version TEXT,
                owner_department TEXT,
                confidentiality_level TEXT,
                source_file TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL DEFAULT 'docx',
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                parser_status TEXT NOT NULL,
                review_status TEXT NOT NULL,
                checksum TEXT NOT NULL UNIQUE,
                accepted_checksum TEXT,
                current_parse_run_id INTEGER,
                latest_parse_run_id INTEGER,
                active_parse_run_id INTEGER,
                latest_chunk_run_id INTEGER,
                active_chunk_run_id INTEGER,
                series_id INTEGER REFERENCES policy_series(id),
                document_version_no INTEGER NOT NULL DEFAULT 1,
                latest_metadata_revision_id INTEGER,
                approved_metadata_revision_id INTEGER,
                active_metadata_revision_id INTEGER,
                description TEXT,
                keywords TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_metadata_revision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES policy_document(id),
                parse_run_id INTEGER REFERENCES parse_run(id),
                revision_no INTEGER NOT NULL,
                parent_revision_id INTEGER REFERENCES document_metadata_revision(id),
                source_type TEXT NOT NULL,
                title TEXT,
                document_code TEXT,
                document_type TEXT,
                issuing_org TEXT,
                addressee_text TEXT,
                authority_level TEXT,
                publish_date TEXT,
                effective_date TEXT,
                expiry_date TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                version TEXT,
                owner_department TEXT,
                confidentiality_level TEXT,
                lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT',
                change_reason TEXT,
                repeal_date TEXT,
                repeal_reason TEXT,
                repeal_evidence TEXT,
                status_confirmation_note TEXT,
                content_hash TEXT NOT NULL,
                created_by TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(document_id, revision_no)
            );

            CREATE TABLE IF NOT EXISTS parse_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES policy_document(id),
                parser_version TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                current_stage TEXT,
                render_engine TEXT,
                render_engine_version TEXT,
                render_os TEXT,
                page_count INTEGER,
                pdf_path TEXT,
                pdf_checksum TEXT,
                render_source_checksum TEXT,
                tracked_change_count INTEGER NOT NULL DEFAULT 0,
                revision_view TEXT,
                accepted_docx_path TEXT,
                accepted_checksum TEXT,
                acceptance_engine TEXT,
                acceptance_engine_version TEXT,
                page_mapping_method TEXT,
                page_mapping_version TEXT,
                mapped_block_count INTEGER NOT NULL DEFAULT 0,
                unmapped_block_count INTEGER NOT NULL DEFAULT 0,
                page_mapping_coverage REAL,
                character_coverage REAL,
                block_coverage REAL,
                table_cell_coverage REAL,
                font_environment_hash TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                elapsed_seconds REAL,
                error_code TEXT,
                error_message TEXT,
                review_status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS source_block (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id) ON DELETE CASCADE,
                parent_block_id INTEGER REFERENCES source_block(id),
                temp_key TEXT NOT NULL,
                parent_temp_key TEXT,
                part_type TEXT NOT NULL,
                block_type TEXT NOT NULL,
                order_no INTEGER NOT NULL,
                raw_text TEXT NOT NULL,
                clean_text TEXT NOT NULL,
                style_name TEXT,
                numbering_id TEXT,
                numbering_level INTEGER,
                display_number TEXT,
                properties_json TEXT NOT NULL,
                source_locator_json TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                page_mapping_confidence REAL,
                page_mapping_method TEXT,
                excluded_role TEXT NOT NULL DEFAULT 'none',
                exclusion_reason TEXT,
                normalization_actions_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS policy_node (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES policy_document(id),
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id) ON DELETE CASCADE,
                parent_id INTEGER REFERENCES policy_node(id),
                temp_key TEXT NOT NULL,
                parent_temp_key TEXT,
                node_type TEXT NOT NULL,
                node_number TEXT,
                title TEXT,
                raw_text TEXT NOT NULL,
                content TEXT,
                normalized_content TEXT,
                level INTEGER NOT NULL,
                path TEXT,
                path_text TEXT,
                page_start INTEGER,
                page_end INTEGER,
                order_no INTEGER NOT NULL,
                effect_status_candidate TEXT,
                parser_confidence REAL NOT NULL,
                decision_method TEXT NOT NULL,
                rule_id TEXT,
                candidate_types TEXT,
                review_status TEXT NOT NULL,
                review_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS node_source_span (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL REFERENCES policy_node(id) ON DELETE CASCADE,
                source_block_id INTEGER NOT NULL REFERENCES source_block(id) ON DELETE CASCADE,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                mapping_type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS extracted_field (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                raw_value TEXT NOT NULL,
                normalized_value TEXT,
                source_block_id INTEGER REFERENCES source_block(id),
                source_node_id INTEGER REFERENCES policy_node(id),
                confidence REAL NOT NULL,
                decision_method TEXT NOT NULL,
                rule_id TEXT,
                review_status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS validation_issue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id) ON DELETE CASCADE,
                node_id INTEGER REFERENCES policy_node(id),
                source_block_id INTEGER REFERENCES source_block(id),
                stage TEXT NOT NULL,
                issue_code TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0,
                resolved_by TEXT,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS review_decision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id) ON DELETE CASCADE,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                old_value_json TEXT NOT NULL,
                new_value_json TEXT NOT NULL,
                comment TEXT,
                reviewed_by TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunk_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES policy_document(id),
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id),
                chunker_version TEXT NOT NULL,
                strategy TEXT NOT NULL,
                config_json TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                tokenizer_name TEXT,
                tokenizer_version TEXT,
                status TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending',
                source_scope TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                retrievable_count INTEGER NOT NULL DEFAULT 0,
                context_count INTEGER NOT NULL DEFAULT 0,
                eligible_node_count INTEGER NOT NULL DEFAULT 0,
                mapped_node_count INTEGER NOT NULL DEFAULT 0,
                eligible_node_coverage REAL,
                eligible_character_coverage REAL,
                retrievable_character_coverage REAL,
                unmapped_node_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                duplicate_body_character_count INTEGER NOT NULL DEFAULT 0,
                allowed_overlap_character_count INTEGER NOT NULL DEFAULT 0,
                validation_issue_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                elapsed_seconds REAL,
                error_code TEXT,
                error_message TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(parse_run_id, chunker_version, config_hash)
            );

            CREATE TABLE IF NOT EXISTS policy_chunk (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_run_id INTEGER NOT NULL REFERENCES chunk_run(id) ON DELETE CASCADE,
                chunk_key TEXT NOT NULL,
                primary_node_id INTEGER REFERENCES policy_node(id),
                parent_chunk_id INTEGER REFERENCES policy_chunk(id),
                chunk_type TEXT NOT NULL,
                chunk_role TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                path_text TEXT,
                title_text TEXT,
                prefix_text TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                retrieval_text TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                retrieval_char_count INTEGER NOT NULL,
                token_count INTEGER,
                page_start INTEGER,
                page_end INTEGER,
                is_retrievable INTEGER NOT NULL,
                raw_text_hash TEXT NOT NULL,
                retrieval_text_hash TEXT NOT NULL,
                template_version TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'confirmed',
                created_at TEXT NOT NULL,
                UNIQUE(chunk_run_id, chunk_index),
                UNIQUE(chunk_run_id, chunk_key)
            );

            CREATE TABLE IF NOT EXISTS chunk_source_node (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id INTEGER NOT NULL REFERENCES policy_chunk(id) ON DELETE CASCADE,
                node_id INTEGER NOT NULL REFERENCES policy_node(id),
                source_order INTEGER NOT NULL,
                contribution_role TEXT NOT NULL,
                node_char_start INTEGER,
                node_char_end INTEGER,
                chunk_char_start INTEGER,
                chunk_char_end INTEGER,
                mapping_type TEXT NOT NULL,
                source_text_hash TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chunk_validation_issue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_run_id INTEGER NOT NULL REFERENCES chunk_run(id) ON DELETE CASCADE,
                chunk_id INTEGER REFERENCES policy_chunk(id) ON DELETE CASCADE,
                node_id INTEGER REFERENCES policy_node(id),
                stage TEXT NOT NULL,
                issue_code TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0,
                resolved_by TEXT,
                resolved_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_document_checksum
                ON policy_document(checksum);
            CREATE INDEX IF NOT EXISTS idx_metadata_revision_document
                ON document_metadata_revision(document_id, lifecycle_status, revision_no);
            CREATE INDEX IF NOT EXISTS idx_parse_run_version
                ON parse_run(document_id, parser_version, config_hash);
            CREATE INDEX IF NOT EXISTS idx_source_block_order
                ON source_block(parse_run_id, part_type, order_no);
            CREATE INDEX IF NOT EXISTS idx_policy_node_tree
                ON policy_node(parse_run_id, parent_id, order_no);
            CREATE INDEX IF NOT EXISTS idx_node_source
                ON node_source_span(node_id, source_block_id);
            CREATE INDEX IF NOT EXISTS idx_validation_issue
                ON validation_issue(parse_run_id, severity, resolved);
            CREATE INDEX IF NOT EXISTS idx_review_decision_target
                ON review_decision(parse_run_id, target_type, target_id, id);
            CREATE INDEX IF NOT EXISTS idx_chunk_run_document
                ON chunk_run(document_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_chunk_run_parse
                ON chunk_run(parse_run_id, chunker_version, config_hash);
            CREATE INDEX IF NOT EXISTS idx_policy_chunk_run
                ON policy_chunk(chunk_run_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_policy_chunk_parent
                ON policy_chunk(chunk_run_id, parent_chunk_id);
            CREATE INDEX IF NOT EXISTS idx_chunk_source_chunk
                ON chunk_source_node(chunk_id, source_order);
            CREATE INDEX IF NOT EXISTS idx_chunk_source_node
                ON chunk_source_node(node_id, chunk_id);
            CREATE INDEX IF NOT EXISTS idx_chunk_validation_issue
                ON chunk_validation_issue(chunk_run_id, severity, resolved);
            """
        )
        self._migrate_schema()
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """为既有 SQLite 文件补充新增列，保持历史 ParseRun 可读。"""

        columns = {str(row["name"]) for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_schema(self) -> None:
        """执行非破坏性增量迁移，不重写既有解析结果。"""

        self._ensure_column("policy_document", "latest_parse_run_id", "INTEGER")
        self._ensure_column("policy_document", "active_parse_run_id", "INTEGER")
        self._ensure_column("policy_document", "latest_chunk_run_id", "INTEGER")
        self._ensure_column("policy_document", "active_chunk_run_id", "INTEGER")
        self._ensure_column("policy_document", "series_id", "INTEGER")
        self._ensure_column("policy_document", "document_version_no", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("policy_document", "latest_metadata_revision_id", "INTEGER")
        self._ensure_column("policy_document", "approved_metadata_revision_id", "INTEGER")
        self._ensure_column("policy_document", "active_metadata_revision_id", "INTEGER")
        self._ensure_column("parse_run", "parent_parse_run_id", "INTEGER")
        self._ensure_column("parse_run", "run_kind", "TEXT NOT NULL DEFAULT 'AUTOMATED'")
        self._ensure_column("document_metadata_revision", "status_confirmation_note", "TEXT")
        self._ensure_column("document_metadata_revision", "parse_run_id", "INTEGER")
        self.connection.execute(
            """
            UPDATE document_metadata_revision
            SET parse_run_id=(
                SELECT d.active_parse_run_id FROM policy_document d
                WHERE d.id=document_metadata_revision.document_id
            )
            WHERE parse_run_id IS NULL
            """
        )
        self._ensure_column("parse_run", "review_status", "TEXT NOT NULL DEFAULT 'pending'")
        self._ensure_column("parse_run", "reviewed_by", "TEXT")
        self._ensure_column("parse_run", "reviewed_at", "TEXT")
        self._ensure_column("source_block", "page_mapping_method", "TEXT")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_policy_document_series ON policy_document(series_id, document_version_no)"
        )
        self.connection.execute(
            """
            UPDATE policy_document
            SET latest_parse_run_id=current_parse_run_id
            WHERE latest_parse_run_id IS NULL AND current_parse_run_id IS NOT NULL
            """
        )
        self.connection.execute(
            """
            UPDATE parse_run
            SET review_status=CASE
                WHEN status='succeeded' THEN 'not_required'
                WHEN status='review_required' THEN 'pending'
                ELSE review_status
            END
            WHERE review_status IS NULL OR review_status='pending'
            """
        )
        # 历史短 Chunk 问题原先没有冗余保存 primary Node；按 Chunk 主来源非破坏性回填。
        self.connection.execute(
            """
            UPDATE chunk_validation_issue
            SET node_id=(
                SELECT pc.primary_node_id
                FROM policy_chunk pc
                WHERE pc.id=chunk_validation_issue.chunk_id
            )
            WHERE node_id IS NULL
              AND issue_code IN ('SHORT_CHUNK', 'EXTREMELY_SHORT_CHUNK')
              AND chunk_id IS NOT NULL
            """
        )
        short_rows = self.connection.execute(
            """
            SELECT cvi.id, cvi.details_json, pc.primary_node_id, pn.node_type
            FROM chunk_validation_issue cvi
            JOIN policy_chunk pc ON pc.id=cvi.chunk_id
            LEFT JOIN policy_node pn ON pn.id=pc.primary_node_id
            WHERE cvi.issue_code IN ('SHORT_CHUNK', 'EXTREMELY_SHORT_CHUNK')
            """
        ).fetchall()
        for row in short_rows:
            try:
                details = json.loads(row["details_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                details = {}
            changed = False
            if "primary_node_id" not in details:
                details["primary_node_id"] = row["primary_node_id"]
                changed = True
            if "node_type" not in details:
                details["node_type"] = row["node_type"]
                changed = True
            if changed:
                self.connection.execute(
                    "UPDATE chunk_validation_issue SET details_json=? WHERE id=?",
                    (json.dumps(details, ensure_ascii=False, sort_keys=True), int(row["id"])),
                )
        self._backfill_policy_series_and_metadata()

    def _backfill_policy_series_and_metadata(self) -> None:
        """为既有正式文件建立制度系列和首个元数据修订，不改变公开范围。"""

        documents = self.connection.execute(
            "SELECT * FROM policy_document ORDER BY id"
        ).fetchall()
        for document in documents:
            document_id = int(document["id"])
            series_id = document["series_id"]
            if series_id is None:
                now = utc_now()
                cursor = self.connection.execute(
                    """
                    INSERT INTO policy_series (
                        series_key, canonical_title, status, created_at, updated_at
                    ) VALUES (?, ?, 'ACTIVE', ?, ?)
                    """,
                    (
                        f"policy-series-{document_id}",
                        str(document["title"] or document["file_name"] or f"制度{document_id}"),
                        now,
                        now,
                    ),
                )
                series_id = int(cursor.lastrowid)
                self.connection.execute(
                    "UPDATE policy_document SET series_id=?, document_version_no=1 WHERE id=?",
                    (series_id, document_id),
                )
            if document["latest_metadata_revision_id"] is not None:
                continue

            active_source = self.connection.execute(
                """
                SELECT 1
                FROM index_profile ip
                JOIN index_run_source src ON src.index_run_id=ip.active_index_run_id
                WHERE src.document_id=?
                LIMIT 1
                """,
                (document_id,),
            ).fetchone() if self._table_exists("index_run_source") else None
            lifecycle_status = "PUBLISHED" if active_source else "DRAFT"
            now = utc_now()
            values = {
                name: document[name]
                for name in (
                    "title", "document_code", "document_type", "issuing_org",
                    "addressee_text", "authority_level", "publish_date", "effective_date",
                    "expiry_date", "status", "version", "owner_department",
                    "confidentiality_level",
                )
            }
            content_hash = self._metadata_hash(values)
            cursor = self.connection.execute(
                """
                INSERT INTO document_metadata_revision (
                    document_id, parse_run_id, revision_no, source_type, title, document_code,
                    document_type, issuing_org, addressee_text, authority_level,
                    publish_date, effective_date, expiry_date, status, version,
                    owner_department, confidentiality_level, lifecycle_status,
                    content_hash, published_at, created_at, updated_at
                ) VALUES (?, ?, 1, 'BACKFILL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document["active_parse_run_id"],
                    values["title"], values["document_code"], values["document_type"],
                    values["issuing_org"], values["addressee_text"], values["authority_level"],
                    values["publish_date"], values["effective_date"], values["expiry_date"],
                    values["status"] or "unknown", values["version"],
                    values["owner_department"], values["confidentiality_level"],
                    lifecycle_status, content_hash,
                    now if lifecycle_status == "PUBLISHED" else None, now, now,
                ),
            )
            revision_id = int(cursor.lastrowid)
            approved_id = revision_id if lifecycle_status == "PUBLISHED" else None
            active_id = revision_id if lifecycle_status == "PUBLISHED" else None
            self.connection.execute(
                """
                UPDATE policy_document
                SET latest_metadata_revision_id=?, approved_metadata_revision_id=?,
                    active_metadata_revision_id=?
                WHERE id=?
                """,
                (revision_id, approved_id, active_id, document_id),
            )

    def _table_exists(self, table: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _metadata_hash(values: dict[str, Any]) -> str:
        """计算不依赖字段顺序的元数据内容摘要。"""

        import hashlib

        payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_or_create_document(self, data: dict[str, Any]) -> int:
        row = self.connection.execute(
            "SELECT id FROM policy_document WHERE checksum = ?", (data["checksum"],)
        ).fetchone()
        now = utc_now()
        if row:
            document_id = int(row["id"])
            self.connection.execute(
                """
                UPDATE policy_document
                SET source_file=?, file_name=?, file_size=?, parser_status='queued',
                    review_status='pending', updated_at=?
                WHERE id=?
                """,
                (
                    data["source_file"],
                    data["file_name"],
                    data["file_size"],
                    now,
                    document_id,
                ),
            )
            self.connection.commit()
            return document_id

        cursor = self.connection.execute(
            """
            INSERT INTO policy_document (
                source_file, file_name, file_type, mime_type, file_size,
                parser_status, review_status, checksum, created_at, updated_at
            ) VALUES (?, ?, 'docx', ?, ?, 'queued', 'pending', ?, ?, ?)
            """,
            (
                data["source_file"],
                data["file_name"],
                data["mime_type"],
                data["file_size"],
                data["checksum"],
                now,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_parse_run(
        self, document_id: int, parser_version: str, config_hash: str
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO parse_run (
                document_id, parser_version, config_hash, status,
                current_stage, started_at
            ) VALUES (?, ?, ?, 'running', 'file_validation', ?)
            """,
            (document_id, parser_version, config_hash, utc_now()),
        )
        run_id = int(cursor.lastrowid)
        self.connection.execute(
            "UPDATE policy_document SET parser_status='running', updated_at=? WHERE id=?",
            (utc_now(), document_id),
        )
        self.connection.commit()
        return run_id

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{name}=?" for name in fields)
        self.connection.execute(
            f"UPDATE parse_run SET {columns} WHERE id=?",  # 字段名只来自内部固定调用
            (*fields.values(), run_id),
        )
        self.connection.commit()

    def update_document(self, document_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        columns = ", ".join(f"{name}=?" for name in fields)
        self.connection.execute(
            f"UPDATE policy_document SET {columns} WHERE id=?",  # 字段名只来自内部固定调用
            (*fields.values(), document_id),
        )
        self.connection.commit()

    def insert_blocks(self, run_id: int, blocks: list[dict[str, Any]]) -> dict[str, int]:
        key_to_id: dict[str, int] = {}
        with self.transaction():
            for block in blocks:
                cursor = self.connection.execute(
                    """
                    INSERT INTO source_block (
                        parse_run_id, temp_key, parent_temp_key, part_type, block_type,
                        order_no, raw_text, clean_text, style_name, numbering_id,
                        numbering_level, display_number, properties_json,
                        source_locator_json, excluded_role, exclusion_reason,
                        normalization_actions_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        block["temp_key"],
                        block.get("parent_temp_key"),
                        block["part_type"],
                        block["block_type"],
                        block["order_no"],
                        block["raw_text"],
                        block["clean_text"],
                        block.get("style_name"),
                        block.get("numbering_id"),
                        block.get("numbering_level"),
                        block.get("display_number"),
                        json.dumps(block.get("properties", {}), ensure_ascii=False),
                        json.dumps(block.get("source_locator", {}), ensure_ascii=False),
                        block.get("excluded_role", "none"),
                        block.get("exclusion_reason"),
                        json.dumps(block.get("normalization_actions", []), ensure_ascii=False),
                    ),
                )
                key_to_id[block["temp_key"]] = int(cursor.lastrowid)

            for block in blocks:
                parent_key = block.get("parent_temp_key")
                if parent_key and parent_key in key_to_id:
                    self.connection.execute(
                        "UPDATE source_block SET parent_block_id=? WHERE id=?",
                        (key_to_id[parent_key], key_to_id[block["temp_key"]]),
                    )
        return key_to_id

    def insert_nodes(
        self,
        document_id: int,
        run_id: int,
        nodes: list[dict[str, Any]],
        block_ids: dict[str, int],
    ) -> tuple[dict[str, int], dict[str, int]]:
        key_to_id: dict[str, int] = {}
        block_to_node: dict[str, int] = {}
        now = utc_now()
        with self.transaction():
            for node in nodes:
                cursor = self.connection.execute(
                    """
                    INSERT INTO policy_node (
                        document_id, parse_run_id, temp_key, parent_temp_key,
                        node_type, node_number, title, raw_text, content,
                        normalized_content, level, path, path_text, order_no,
                        effect_status_candidate, parser_confidence, decision_method,
                        rule_id, candidate_types, review_status, review_reason,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        run_id,
                        node["temp_key"],
                        node.get("parent_temp_key"),
                        node["node_type"],
                        node.get("node_number"),
                        node.get("title"),
                        node["raw_text"],
                        node.get("content"),
                        node.get("normalized_content"),
                        node["level"],
                        node.get("path"),
                        node.get("path_text"),
                        node["order_no"],
                        node.get("effect_status_candidate"),
                        node["parser_confidence"],
                        node["decision_method"],
                        node.get("rule_id"),
                        json.dumps(node.get("candidate_types", []), ensure_ascii=False),
                        node.get("review_status", "pending"),
                        node.get("review_reason"),
                        now,
                        now,
                    ),
                )
                node_id = int(cursor.lastrowid)
                key_to_id[node["temp_key"]] = node_id
                block_to_node[node["source_block_key"]] = node_id
                block_id = block_ids[node["source_block_key"]]
                self.connection.execute(
                    """
                    INSERT INTO node_source_span (
                        node_id, source_block_id, char_start, char_end, mapping_type
                    ) VALUES (?, ?, 0, ?, 'exact')
                    """,
                    (node_id, block_id, len(node["raw_text"])),
                )

            for node in nodes:
                parent_key = node.get("parent_temp_key")
                if parent_key and parent_key in key_to_id:
                    self.connection.execute(
                        "UPDATE policy_node SET parent_id=? WHERE id=?",
                        (key_to_id[parent_key], key_to_id[node["temp_key"]]),
                    )
        return key_to_id, block_to_node

    def insert_fields(
        self,
        run_id: int,
        fields: Iterable[dict[str, Any]],
        block_ids: dict[str, int],
        block_to_node: dict[str, int],
    ) -> None:
        with self.transaction():
            for field in fields:
                block_key = field.get("source_block_key")
                self.connection.execute(
                    """
                    INSERT INTO extracted_field (
                        parse_run_id, field_name, raw_value, normalized_value,
                        source_block_id, source_node_id, confidence,
                        decision_method, rule_id, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        field["field_name"],
                        field["raw_value"],
                        field.get("normalized_value"),
                        block_ids.get(block_key) if block_key else None,
                        block_to_node.get(block_key) if block_key else None,
                        field["confidence"],
                        field["decision_method"],
                        field.get("rule_id"),
                        field.get("review_status", "pending"),
                    ),
                )

    def insert_issues(
        self,
        run_id: int,
        issues: Iterable[dict[str, Any]],
        block_ids: dict[str, int] | None = None,
        node_ids: dict[str, int] | None = None,
    ) -> None:
        block_ids = block_ids or {}
        node_ids = node_ids or {}
        with self.transaction():
            for issue in issues:
                self.connection.execute(
                    """
                    INSERT INTO validation_issue (
                        parse_run_id, node_id, source_block_id, stage,
                        issue_code, severity, message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        node_ids.get(issue.get("node_key")),
                        block_ids.get(issue.get("source_block_key")),
                        issue["stage"],
                        issue["issue_code"],
                        issue["severity"],
                        issue["message"],
                        json.dumps(issue.get("details", {}), ensure_ascii=False),
                    ),
                )

    def update_block_pages(self, mappings: dict[int, tuple[int | None, int | None, float]]) -> None:
        with self.transaction():
            self.connection.executemany(
                """
                UPDATE source_block
                SET page_start=?, page_end=?, page_mapping_confidence=?,
                    page_mapping_method='pdf_text_alignment'
                WHERE id=?
                """,
                [
                    (page_start, page_end, confidence, block_id)
                    for block_id, (page_start, page_end, confidence) in mappings.items()
                ],
            )

    def inherit_child_block_pages(self, run_id: int) -> None:
        """正文文本框和图片继承宿主 Block 页码，并降低少量置信度。"""

        with self.transaction():
            self.connection.execute(
                """
                UPDATE source_block AS child
                SET page_start=(SELECT parent.page_start FROM source_block parent WHERE parent.id=child.parent_block_id),
                    page_end=(SELECT parent.page_end FROM source_block parent WHERE parent.id=child.parent_block_id),
                    page_mapping_confidence=(
                        SELECT CASE
                            WHEN parent.page_mapping_confidence IS NULL THEN NULL
                            ELSE parent.page_mapping_confidence * 0.95
                        END
                        FROM source_block parent WHERE parent.id=child.parent_block_id
                    ),
                    page_mapping_method='parent_anchor'
                WHERE child.parse_run_id=?
                  AND child.part_type='document'
                  AND child.block_type IN ('textbox', 'image')
                  AND child.parent_block_id IS NOT NULL
                  AND child.page_start IS NULL
                  AND EXISTS (
                      SELECT 1 FROM source_block parent
                      WHERE parent.id=child.parent_block_id AND parent.page_start IS NOT NULL
                  )
                """,
                (run_id,),
            )

    def update_node_pages(self, run_id: int) -> None:
        with self.transaction():
            self.connection.execute(
                """
                UPDATE policy_node
                SET page_start = (
                        SELECT MIN(sb.page_start)
                        FROM node_source_span nss
                        JOIN source_block sb ON sb.id=nss.source_block_id
                        WHERE nss.node_id=policy_node.id
                    ),
                    page_end = (
                        SELECT MAX(sb.page_end)
                        FROM node_source_span nss
                        JOIN source_block sb ON sb.id=nss.source_block_id
                        WHERE nss.node_id=policy_node.id
                    )
                WHERE parse_run_id=?
                """,
                (run_id,),
            )

    def run_summary(self, run_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT pr.*, pd.file_name, pd.title, pd.document_type,
                   (SELECT COUNT(*) FROM source_block WHERE parse_run_id=pr.id) AS block_count,
                   (SELECT COUNT(*) FROM policy_node WHERE parse_run_id=pr.id) AS node_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id) AS issue_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id AND severity='review') AS review_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id AND severity='error') AS error_count
            FROM parse_run pr
            JOIN policy_document pd ON pd.id=pr.document_id
            WHERE pr.id=?
            """,
            (run_id,),
        ).fetchone()
        return dict(row) if row else {}
