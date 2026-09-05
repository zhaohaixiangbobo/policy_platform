"""索引层 SQLite 数据访问。

该文件只新增 index_profile、index_run、index_run_source 和 chunk_index_record，
通过外键读取既有 active ChunkRun，不修改解析与 Chunk 表的字段或生命周期。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .config import canonical_json, sha256_text


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IndexDatabase:
    """索引控制面仓储。"""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"SQLite 数据库不存在：{self.path}")
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "IndexDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_name TEXT NOT NULL UNIQUE,
                alias_name TEXT NOT NULL UNIQUE,
                latest_index_run_id INTEGER,
                active_index_run_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS index_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES index_profile(id),
                source_manifest_hash TEXT NOT NULL,
                embedding_provider TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_model_revision TEXT NOT NULL,
                embedding_contract_json TEXT NOT NULL,
                embedding_contract_hash TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                distance_metric TEXT NOT NULL,
                vector_name TEXT NOT NULL,
                collection_name TEXT NOT NULL UNIQUE,
                alias_name TEXT NOT NULL,
                point_schema_version TEXT NOT NULL,
                config_json TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                indexer_version TEXT NOT NULL,
                status TEXT NOT NULL,
                activation_status TEXT NOT NULL,
                expected_count INTEGER NOT NULL DEFAULT 0,
                indexed_count INTEGER NOT NULL DEFAULT 0,
                verified_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(profile_id, source_manifest_hash, embedding_contract_hash, config_hash)
            );

            CREATE TABLE IF NOT EXISTS index_run_source (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_run_id INTEGER NOT NULL REFERENCES index_run(id) ON DELETE CASCADE,
                document_id INTEGER NOT NULL REFERENCES policy_document(id),
                parse_run_id INTEGER NOT NULL REFERENCES parse_run(id),
                chunk_run_id INTEGER NOT NULL REFERENCES chunk_run(id),
                metadata_revision_id INTEGER REFERENCES document_metadata_revision(id),
                retrievable_count INTEGER NOT NULL,
                source_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(index_run_id, document_id),
                UNIQUE(index_run_id, chunk_run_id)
            );

            CREATE TABLE IF NOT EXISTS chunk_index_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_run_id INTEGER NOT NULL REFERENCES index_run(id) ON DELETE CASCADE,
                chunk_id INTEGER NOT NULL REFERENCES policy_chunk(id),
                point_id TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                embedding_input_hash TEXT NOT NULL,
                embedding_contract_hash TEXT NOT NULL,
                vector_dimension INTEGER,
                vector_norm REAL,
                payload_hash TEXT,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                error_stage TEXT,
                error_code TEXT,
                error_message TEXT,
                indexed_at TEXT,
                verified_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(index_run_id, chunk_id),
                UNIQUE(index_run_id, point_id)
            );

            CREATE INDEX IF NOT EXISTS idx_index_run_profile_status
                ON index_run(profile_id, status, activation_status, id);
            CREATE INDEX IF NOT EXISTS idx_index_source_chunk_run
                ON index_run_source(chunk_run_id, index_run_id);
            CREATE INDEX IF NOT EXISTS idx_chunk_index_record_status
                ON chunk_index_record(index_run_id, status, id);
            CREATE INDEX IF NOT EXISTS idx_chunk_index_record_chunk
                ON chunk_index_record(chunk_id, index_run_id);
            """
        )
        self._migrate_schema()
        self.connection.commit()

    def _migrate_schema(self) -> None:
        """补充V2冻结元数据修订，并回填已发布历史IndexRun。"""

        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(index_run_source)")
        }
        if "metadata_revision_id" not in columns:
            self.connection.execute(
                "ALTER TABLE index_run_source ADD COLUMN metadata_revision_id INTEGER"
            )
        self.connection.execute(
            """
            UPDATE index_run_source
            SET metadata_revision_id=(
                SELECT d.active_metadata_revision_id
                FROM policy_document d
                WHERE d.id=index_run_source.document_id
            )
            WHERE metadata_revision_id IS NULL
            """
        )

    def get_or_create_profile(self, profile_name: str, alias_name: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM index_profile WHERE profile_name=?", (profile_name,)
        ).fetchone()
        if row is not None:
            if str(row["alias_name"]) != alias_name:
                raise ValueError(
                    f"索引配置 {profile_name} 已绑定 alias={row['alias_name']}，不能静默改为 {alias_name}"
                )
            return dict(row)

        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO index_profile (profile_name, alias_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (profile_name, alias_name, now, now),
        )
        self.connection.commit()
        return dict(
            self.connection.execute(
                "SELECT * FROM index_profile WHERE id=?", (int(cursor.lastrowid),)
            ).fetchone()
        )

    def freeze_active_sources(
        self, required_document_ids: Sequence[int] | None = None
    ) -> list[dict[str, Any]]:
        """冻结当前全部正式 active ChunkRun，并计算每份文档来源摘要。"""

        rows = self.connection.execute(
            """
            SELECT pd.id AS document_id, pd.active_parse_run_id,
                   pd.active_chunk_run_id, pd.approved_metadata_revision_id,
                   mr.title AS document_title, mr.document_code,
                   mr.status AS document_status, mr.confidentiality_level,
                   mr.authority_level,
                   cr.parse_run_id, cr.status, cr.review_status, cr.source_scope
            FROM policy_document pd
            JOIN chunk_run cr ON cr.id=pd.active_chunk_run_id
            JOIN document_metadata_revision mr ON mr.id=pd.approved_metadata_revision_id
            WHERE pd.active_chunk_run_id IS NOT NULL
              AND mr.lifecycle_status IN ('APPROVED', 'PUBLISHED')
              AND mr.parse_run_id=cr.parse_run_id
            ORDER BY pd.id
            """
        ).fetchall()
        if not rows:
            raise ValueError("没有可用于正式索引的 active ChunkRun")
        required = {int(value) for value in (required_document_ids or [])}
        available = {int(row["document_id"]) for row in rows}
        missing = sorted(required - available)
        if missing:
            raise ValueError(f"以下制度尚未完成元数据和Chunk审核：{missing}")

        sources: list[dict[str, Any]] = []
        for row in rows:
            if int(row["active_parse_run_id"]) != int(row["parse_run_id"]):
                raise ValueError(f"文档 {row['document_id']} 的 active ParseRun/ChunkRun 已失配")
            if row["status"] != "succeeded" or row["source_scope"] != "active":
                raise ValueError(f"ChunkRun {row['active_chunk_run_id']} 不是正式成功运行")
            if row["review_status"] != "approved":
                raise ValueError(f"ChunkRun {row['active_chunk_run_id']} 尚未通过审核")

            chunks = self.connection.execute(
                """
                SELECT id, chunk_key, retrieval_text_hash, parent_chunk_id,
                       chunk_type, path_text, page_start, page_end
                FROM policy_chunk
                WHERE chunk_run_id=? AND is_retrievable=1 AND chunk_role='retrieval'
                ORDER BY chunk_index
                """,
                (int(row["active_chunk_run_id"]),),
            ).fetchall()
            if not chunks:
                raise ValueError(f"ChunkRun {row['active_chunk_run_id']} 没有可检索 Chunk")
            # 文档状态等字段会写入 Qdrant payload，必须进入来源摘要；否则只改
            # SQLite 元数据后，索引器会错误复用携带旧过滤值的 collection。
            digest_input = {
                "document_payload": {
                    "document_title": row["document_title"],
                    "document_code": row["document_code"],
                    "document_status": row["document_status"],
                    "confidentiality_level": row["confidentiality_level"],
                    "authority_level": row["authority_level"],
                },
                "chunks": [
                    {
                        "chunk_id": int(chunk["id"]),
                        "chunk_key": str(chunk["chunk_key"]),
                        "retrieval_text_hash": str(chunk["retrieval_text_hash"]),
                        "parent_chunk_id": chunk["parent_chunk_id"],
                        "chunk_type": chunk["chunk_type"],
                        "path_text": chunk["path_text"],
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                    }
                    for chunk in chunks
                ],
            }
            sources.append(
                {
                    "document_id": int(row["document_id"]),
                    "parse_run_id": int(row["parse_run_id"]),
                    "chunk_run_id": int(row["active_chunk_run_id"]),
                    "metadata_revision_id": int(row["approved_metadata_revision_id"]),
                    "retrievable_count": len(chunks),
                    "source_digest": sha256_text(canonical_json(digest_input)),
                }
            )
        return sources

    def freeze_exact_sources(
        self, expected_sources: Sequence[dict[str, int]]
    ) -> list[dict[str, Any]]:
        """按Platform冻结清单逐项取数，既不补入新制度，也不静默遗漏基线制度。"""

        normalized = sorted(
            (
                {
                    "document_id": int(source["document_id"]),
                    "parse_run_id": int(source["parse_run_id"]),
                    "chunk_run_id": int(source["chunk_run_id"]),
                    "metadata_revision_id": int(source["metadata_revision_id"]),
                }
                for source in expected_sources
            ),
            key=lambda item: item["document_id"],
        )
        if not normalized:
            raise ValueError("精确发布快照不能为空")
        if len({item["document_id"] for item in normalized}) != len(normalized):
            raise ValueError("精确发布快照包含重复制度")

        sources: list[dict[str, Any]] = []
        for expected in normalized:
            row = self.connection.execute(
                """
                SELECT pd.id AS document_id,pd.active_parse_run_id,
                       pd.active_chunk_run_id,pd.approved_metadata_revision_id,
                       mr.title AS document_title,mr.document_code,
                       mr.status AS document_status,mr.confidentiality_level,
                       mr.authority_level,mr.lifecycle_status,
                       mr.parse_run_id AS metadata_parse_run_id,
                       cr.parse_run_id,cr.status,cr.review_status,cr.source_scope
                FROM policy_document pd
                JOIN chunk_run cr ON cr.id=? AND cr.document_id=pd.id
                JOIN document_metadata_revision mr ON mr.id=? AND mr.document_id=pd.id
                WHERE pd.id=?
                """,
                (
                    expected["chunk_run_id"],
                    expected["metadata_revision_id"],
                    expected["document_id"],
                ),
            ).fetchone()
            if row is None:
                raise ValueError(f"制度 {expected['document_id']} 的冻结来源已不存在")
            actual = (
                int(row["active_parse_run_id"]) if row["active_parse_run_id"] is not None else None,
                int(row["active_chunk_run_id"]) if row["active_chunk_run_id"] is not None else None,
                int(row["approved_metadata_revision_id"]) if row["approved_metadata_revision_id"] is not None else None,
            )
            wanted = (
                expected["parse_run_id"], expected["chunk_run_id"],
                expected["metadata_revision_id"],
            )
            if actual != wanted:
                raise ValueError(
                    f"制度 {expected['document_id']} 的审核来源已变化：expected={wanted}, actual={actual}"
                )
            if int(row["parse_run_id"]) != expected["parse_run_id"] or int(row["metadata_parse_run_id"]) != expected["parse_run_id"]:
                raise ValueError(f"制度 {expected['document_id']} 的ParseRun来源不一致")
            if row["lifecycle_status"] not in {"APPROVED", "PUBLISHED"}:
                raise ValueError(f"元数据修订 {expected['metadata_revision_id']} 尚未审核通过")
            if row["status"] != "succeeded" or row["source_scope"] != "active":
                raise ValueError(f"ChunkRun {expected['chunk_run_id']} 不是正式成功运行")
            if row["review_status"] != "approved":
                raise ValueError(f"ChunkRun {expected['chunk_run_id']} 尚未通过审核")

            chunks = self.connection.execute(
                """
                SELECT id,chunk_key,retrieval_text_hash,parent_chunk_id,
                       chunk_type,path_text,page_start,page_end
                FROM policy_chunk
                WHERE chunk_run_id=? AND is_retrievable=1 AND chunk_role='retrieval'
                ORDER BY chunk_index
                """,
                (expected["chunk_run_id"],),
            ).fetchall()
            if not chunks:
                raise ValueError(f"ChunkRun {expected['chunk_run_id']} 没有可检索 Chunk")
            digest_input = {
                "document_payload": {
                    "document_title": row["document_title"],
                    "document_code": row["document_code"],
                    "document_status": row["document_status"],
                    "confidentiality_level": row["confidentiality_level"],
                    "authority_level": row["authority_level"],
                },
                "chunks": [
                    {
                        "chunk_id": int(chunk["id"]),
                        "chunk_key": str(chunk["chunk_key"]),
                        "retrieval_text_hash": str(chunk["retrieval_text_hash"]),
                        "parent_chunk_id": chunk["parent_chunk_id"],
                        "chunk_type": chunk["chunk_type"],
                        "path_text": chunk["path_text"],
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                    }
                    for chunk in chunks
                ],
            }
            sources.append({
                **expected,
                "retrievable_count": len(chunks),
                "source_digest": sha256_text(canonical_json(digest_input)),
            })
        return sources

    @staticmethod
    def source_manifest_hash(sources: Sequence[dict[str, Any]]) -> str:
        manifest = [
            {
                "document_id": int(source["document_id"]),
                "parse_run_id": int(source["parse_run_id"]),
                "chunk_run_id": int(source["chunk_run_id"]),
                "metadata_revision_id": int(source["metadata_revision_id"]),
                "retrievable_count": int(source["retrievable_count"]),
                "source_digest": str(source["source_digest"]),
            }
            for source in sources
        ]
        return sha256_text(canonical_json(manifest))

    def find_run(
        self,
        profile_id: int,
        source_manifest_hash: str,
        embedding_contract_hash: str,
        config_hash: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM index_run
            WHERE profile_id=? AND source_manifest_hash=?
              AND embedding_contract_hash=? AND config_hash=?
            """,
            (profile_id, source_manifest_hash, embedding_contract_hash, config_hash),
        ).fetchone()
        return dict(row) if row else None

    def create_run(
        self,
        *,
        profile_id: int,
        sources: Sequence[dict[str, Any]],
        source_manifest_hash: str,
        contract: dict[str, Any],
        contract_json: str,
        contract_hash: str,
        collection_name: str,
        alias_name: str,
        point_schema_version: str,
        config_json: str,
        config_hash: str,
        indexer_version: str,
    ) -> dict[str, Any]:
        now = utc_now()
        expected_count = sum(int(source["retrievable_count"]) for source in sources)
        with self.transaction():
            cursor = self.connection.execute(
                """
                INSERT INTO index_run (
                    profile_id, source_manifest_hash, embedding_provider,
                    embedding_model, embedding_model_revision,
                    embedding_contract_json, embedding_contract_hash,
                    dimension, distance_metric, vector_name, collection_name,
                    alias_name, point_schema_version, config_json, config_hash,
                    indexer_version, status, activation_status, expected_count,
                    started_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'queued', 'inactive', ?, ?, ?)
                """,
                (
                    profile_id,
                    source_manifest_hash,
                    contract["provider"],
                    contract["model"],
                    contract["model_revision"],
                    contract_json,
                    contract_hash,
                    contract["dimension"],
                    contract["distance_metric"],
                    contract["vector_name"],
                    collection_name,
                    alias_name,
                    point_schema_version,
                    config_json,
                    config_hash,
                    indexer_version,
                    expected_count,
                    now,
                    now,
                ),
            )
            run_id = int(cursor.lastrowid)
            self.connection.executemany(
                """
                INSERT INTO index_run_source (
                    index_run_id, document_id, parse_run_id, chunk_run_id, metadata_revision_id,
                    retrievable_count, source_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        source["document_id"],
                        source["parse_run_id"],
                        source["chunk_run_id"],
                        source["metadata_revision_id"],
                        source["retrievable_count"],
                        source["source_digest"],
                        now,
                    )
                    for source in sources
                ],
            )
            self.connection.execute(
                """
                UPDATE index_profile
                SET latest_index_run_id=?, updated_at=?
                WHERE id=?
                """,
                (run_id, now, profile_id),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: int) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM index_run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"IndexRun {run_id} 不存在")
        return dict(row)

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{name}=?" for name in fields)
        self.connection.execute(
            f"UPDATE index_run SET {columns} WHERE id=?",  # 字段名仅来自模块内部固定调用
            (*fields.values(), run_id),
        )
        self.connection.commit()

    def ensure_chunk_records(
        self,
        run_id: int,
        collection_name: str,
        contract_hash: str,
        point_id_factory: Any,
    ) -> None:
        rows = self.connection.execute(
            """
            SELECT pc.id, pc.retrieval_text, pc.retrieval_text_hash
            FROM index_run_source src
            JOIN policy_chunk pc ON pc.chunk_run_id=src.chunk_run_id
            WHERE src.index_run_id=?
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            ORDER BY src.document_id, pc.chunk_index
            """,
            (run_id,),
        ).fetchall()
        now = utc_now()
        with self.transaction():
            for row in rows:
                actual_hash = sha256_text(str(row["retrieval_text"]))
                if actual_hash != str(row["retrieval_text_hash"]):
                    raise ValueError(f"Chunk {row['id']} retrieval_text_hash 不一致")
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO chunk_index_record (
                        index_run_id, chunk_id, point_id, collection_name,
                        embedding_input_hash, embedding_contract_hash,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        run_id,
                        int(row["id"]),
                        str(point_id_factory(int(row["id"]))),
                        collection_name,
                        actual_hash,
                        contract_hash,
                        now,
                    ),
                )

    def pending_records(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT cir.*, pc.retrieval_text, pc.chunk_key, pc.parent_chunk_id,
                   pc.chunk_type, pc.path_text, pc.page_start, pc.page_end,
                   pc.chunk_run_id, cr.parse_run_id, cr.document_id,
                   mr.title AS document_title, mr.document_code,
                   mr.status AS document_status, mr.confidentiality_level,
                   mr.authority_level
            FROM chunk_index_record cir
            JOIN policy_chunk pc ON pc.id=cir.chunk_id
            JOIN chunk_run cr ON cr.id=pc.chunk_run_id
            JOIN index_run_source src
              ON src.index_run_id=cir.index_run_id AND src.chunk_run_id=cr.id
            JOIN document_metadata_revision mr ON mr.id=src.metadata_revision_id
            WHERE cir.index_run_id=? AND cir.status!='verified'
            ORDER BY cir.id
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def all_records(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM chunk_index_record WHERE index_run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_embedding(self, record_ids: Sequence[int]) -> None:
        if not record_ids:
            return
        with self.transaction():
            self.connection.executemany(
                """
                UPDATE chunk_index_record
                SET status='embedding', attempt_count=attempt_count+1,
                    error_stage=NULL, error_code=NULL, error_message=NULL
                WHERE id=?
                """,
                [(record_id,) for record_id in record_ids],
            )

    def mark_indexed(
        self,
        record_id: int,
        *,
        dimension: int,
        vector_norm: float,
        payload_hash: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE chunk_index_record
            SET status='indexed', vector_dimension=?, vector_norm=?, payload_hash=?,
                indexed_at=?, error_stage=NULL, error_code=NULL, error_message=NULL
            WHERE id=?
            """,
            (dimension, vector_norm, payload_hash, utc_now(), record_id),
        )
        self.connection.commit()

    def mark_failed(
        self, record_ids: Sequence[int], stage: str, code: str, message: str
    ) -> None:
        if not record_ids:
            return
        with self.transaction():
            self.connection.executemany(
                """
                UPDATE chunk_index_record
                SET status='failed', error_stage=?, error_code=?, error_message=?
                WHERE id=?
                """,
                [(stage, code, message[:2000], record_id) for record_id in record_ids],
            )

    def mark_verified(self, record_id: int) -> None:
        self.connection.execute(
            """
            UPDATE chunk_index_record
            SET status='verified', verified_at=?, error_stage=NULL,
                error_code=NULL, error_message=NULL
            WHERE id=?
            """,
            (utc_now(), record_id),
        )
        self.connection.commit()

    def refresh_counts(self, run_id: int) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT
                SUM(CASE WHEN status IN ('indexed', 'verified') THEN 1 ELSE 0 END) AS indexed_count,
                SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) AS verified_count,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count
            FROM chunk_index_record WHERE index_run_id=?
            """,
            (run_id,),
        ).fetchone()
        counts = {
            "indexed_count": int(row["indexed_count"] or 0),
            "verified_count": int(row["verified_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
        }
        self.update_run(run_id, **counts)
        return counts

    def sources_are_current(self, run_id: int) -> bool:
        mismatch = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM index_run_source src
            JOIN policy_document pd ON pd.id=src.document_id
            WHERE src.index_run_id=?
              AND (
                    pd.active_chunk_run_id IS NULL
                 OR pd.active_chunk_run_id!=src.chunk_run_id
                 OR pd.approved_metadata_revision_id IS NULL
                 OR pd.approved_metadata_revision_id!=src.metadata_revision_id
              )
            """,
            (run_id,),
        ).fetchone()[0]
        return int(mismatch) == 0

    def activate_run(self, profile_id: int, run_id: int) -> None:
        """在 alias 已核验后，用短事务切换 SQLite active 指针。"""

        now = utc_now()
        with self.transaction():
            profile = self.connection.execute(
                "SELECT active_index_run_id FROM index_profile WHERE id=?", (profile_id,)
            ).fetchone()
            old_run_id = profile["active_index_run_id"] if profile else None
            if old_run_id is not None and int(old_run_id) != run_id:
                self.connection.execute(
                    "UPDATE index_run SET activation_status='superseded' WHERE id=?",
                    (int(old_run_id),),
                )
            self.connection.execute(
                """
                UPDATE index_profile
                SET active_index_run_id=?, updated_at=?
                WHERE id=?
                """,
                (run_id, now, profile_id),
            )
            self.connection.execute(
                """
                UPDATE index_run
                SET activation_status='active', status='succeeded', finished_at=?,
                    error_code=NULL, error_message=NULL
                WHERE id=?
                """,
                (now, run_id),
            )
            sources = self.connection.execute(
                """
                SELECT src.document_id, src.metadata_revision_id,
                       d.active_metadata_revision_id
                FROM index_run_source src
                JOIN policy_document d ON d.id=src.document_id
                WHERE src.index_run_id=?
                """,
                (run_id,),
            ).fetchall()
            for source in sources:
                revision_id = source["metadata_revision_id"]
                if revision_id is None:
                    raise RuntimeError("IndexRun缺少冻结的元数据修订")
                previous_id = source["active_metadata_revision_id"]
                if previous_id is not None and int(previous_id) != int(revision_id):
                    self.connection.execute(
                        """
                        UPDATE document_metadata_revision
                        SET lifecycle_status='SUPERSEDED', updated_at=?
                        WHERE id=? AND lifecycle_status='PUBLISHED'
                        """,
                        (now, int(previous_id)),
                    )
                self.connection.execute(
                    """
                    UPDATE document_metadata_revision
                    SET lifecycle_status='PUBLISHED', published_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (now, now, int(revision_id)),
                )
                self.connection.execute(
                    """
                    UPDATE policy_document
                    SET active_metadata_revision_id=?,
                        title=(SELECT title FROM document_metadata_revision WHERE id=?),
                        document_code=(SELECT document_code FROM document_metadata_revision WHERE id=?),
                        document_type=(SELECT document_type FROM document_metadata_revision WHERE id=?),
                        issuing_org=(SELECT issuing_org FROM document_metadata_revision WHERE id=?),
                        addressee_text=(SELECT addressee_text FROM document_metadata_revision WHERE id=?),
                        authority_level=(SELECT authority_level FROM document_metadata_revision WHERE id=?),
                        publish_date=(SELECT publish_date FROM document_metadata_revision WHERE id=?),
                        effective_date=(SELECT effective_date FROM document_metadata_revision WHERE id=?),
                        expiry_date=(SELECT expiry_date FROM document_metadata_revision WHERE id=?),
                        status=(SELECT status FROM document_metadata_revision WHERE id=?),
                        version=(SELECT version FROM document_metadata_revision WHERE id=?),
                        owner_department=(SELECT owner_department FROM document_metadata_revision WHERE id=?),
                        confidentiality_level=(SELECT confidentiality_level FROM document_metadata_revision WHERE id=?),
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        int(revision_id),
                        *([int(revision_id)] * 13),
                        now,
                        int(source["document_id"]),
                    ),
                )

    def active_context(self, profile_name: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT ip.profile_name, ip.alias_name, ip.active_index_run_id,
                   ir.*
            FROM index_profile ip
            JOIN index_run ir ON ir.id=ip.active_index_run_id
            WHERE ip.profile_name=?
            """,
            (profile_name,),
        ).fetchone()
        if row is None:
            raise ValueError(f"索引配置 {profile_name} 尚无 active IndexRun")
        return dict(row)

    def hydrate_chunks(self, index_run_id: int, chunk_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.connection.execute(
            f"""
            SELECT pc.*, cr.document_id, cr.parse_run_id,
                   cr.chunker_version, cr.config_hash AS chunk_config_hash,
                   mr.title AS document_title, mr.document_code,
                   mr.status AS document_status, mr.confidentiality_level,
                   mr.authority_level, pd.source_file, pd.file_name,
                   pd.checksum AS document_checksum,
                   pd.accepted_checksum AS accepted_document_checksum
            FROM policy_chunk pc
            JOIN chunk_run cr ON cr.id=pc.chunk_run_id
            JOIN policy_document pd ON pd.id=cr.document_id
            JOIN index_run_source src
              ON src.index_run_id=? AND src.chunk_run_id=pc.chunk_run_id
            JOIN document_metadata_revision mr ON mr.id=src.metadata_revision_id
            WHERE pc.id IN ({placeholders})
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            """,
            (index_run_id, *chunk_ids),
        ).fetchall()
        return {int(row["id"]): dict(row) for row in rows}

    def hydrate_citation_sources(
        self, index_run_id: int, chunk_ids: Sequence[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """批量回读冻结IndexRun内Chunk的全部Node来源映射。

        查询同时连接 ``index_run_source``，因此任意历史或其他运行的Chunk ID
        都不能借此进入当前证据上下文。
        """

        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.connection.execute(
            f"""
            SELECT csn.*, pn.node_type, pn.node_number, pn.title AS node_title,
                   pn.path_text AS node_path_text, pn.page_start AS node_page_start,
                   pn.page_end AS node_page_end
            FROM chunk_source_node csn
            JOIN policy_chunk pc ON pc.id=csn.chunk_id
            JOIN policy_node pn ON pn.id=csn.node_id
            JOIN index_run_source src
              ON src.index_run_id=? AND src.chunk_run_id=pc.chunk_run_id
            WHERE csn.chunk_id IN ({placeholders})
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            ORDER BY csn.chunk_id, csn.source_order, csn.id
            """,
            (index_run_id, *chunk_ids),
        ).fetchall()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(int(row["chunk_id"]), []).append(dict(row))
        return result
