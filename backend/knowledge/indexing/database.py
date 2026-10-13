"""文件说明：索引层PostgreSQL Core仓储。

该文件管理 index_profile、index_run、index_run_source 和 chunk_index_record，
通过外键读取既有 active ChunkRun，不修改解析与 Chunk 表的字段或生命周期。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


from knowledge.storage.repository import CoreRepository
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from knowledge.metadata_rules import status_transition_error

from .config import canonical_json, sha256_text


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IndexDatabase:
    """索引控制面仓储。"""

    def __init__(self, url: str) -> None:
        self.repository = CoreRepository(url)

    def close(self) -> None:
        self.repository.close()

    def __enter__(self) -> "IndexDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[CoreRepository]:
        try:
            yield self.repository
            self.repository.save()
        except Exception:
            self.repository.discard()
            raise


    def get_or_create_profile(self, profile_name: str, alias_name: str) -> dict[str, Any]:
        row = self.repository.run(sql_text('SELECT * FROM index_profile WHERE profile_name=:p0'), {'p0': profile_name}).mappings().fetchone()
        if row is not None:
            if str(row["alias_name"]) != alias_name:
                raise ValueError(
                    f"索引配置 {profile_name} 已绑定 alias={row['alias_name']}，不能静默改为 {alias_name}"
                )
            return dict(row)

        now = utc_now()
        cursor = self.repository.run(sql_text("""
            INSERT INTO index_profile (profile_name, alias_name, created_at, updated_at)
            VALUES (:p0, :p1, :p2, :p3) RETURNING id"""), {'p0': profile_name, 'p1': alias_name, 'p2': now, 'p3': now})
        self.repository.save()
        return dict(
            self.repository.run(sql_text('SELECT * FROM index_profile WHERE id=:p0'), {'p0': int(cursor.scalar_one())}).mappings().fetchone()
        )

    def freeze_active_sources(
        self, required_document_ids: Sequence[int] | None = None
    ) -> list[dict[str, Any]]:
        """冻结当前全部正式 active ChunkRun，并计算每份文档来源摘要。"""

        rows = self.repository.run(sql_text("""
            SELECT pd.id AS document_id, pd.active_parse_run_id,
                   pd.active_chunk_run_id, pd.approved_metadata_revision_id,
                   mr.title AS document_title, mr.document_code,
                   mr.status AS document_status, mr.confidentiality_level,
                   mr.authority_level,mr.source_type AS metadata_source_type,
                   cr.parse_run_id, cr.status, cr.review_status, cr.source_scope
            FROM policy_document pd
            JOIN chunk_run cr ON cr.id=pd.active_chunk_run_id
            JOIN document_metadata_revision mr ON mr.id=pd.approved_metadata_revision_id
            WHERE pd.active_chunk_run_id IS NOT NULL
              AND mr.lifecycle_status IN ('APPROVED', 'PUBLISHED')
              AND mr.parse_run_id=cr.parse_run_id
            ORDER BY pd.id
            """)).mappings().fetchall()
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
            transition_error = status_transition_error(
                str(row["metadata_source_type"]), row["document_status"]
            )
            if transition_error:
                raise ValueError(
                    f"制度 {row['document_id']} 的元数据生命周期不一致：{transition_error}"
                )

            chunks = self.repository.run(sql_text("""
                SELECT id, chunk_key, retrieval_text_hash, parent_chunk_id,
                       chunk_type, path_text, page_start, page_end
                FROM policy_chunk
                WHERE chunk_run_id=:p0 AND is_retrievable=1 AND chunk_role='retrieval'
                ORDER BY chunk_index
                """), {'p0': int(row["active_chunk_run_id"])}).mappings().fetchall()
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
            row = self.repository.run(sql_text("""
                SELECT pd.id AS document_id,pd.active_parse_run_id,
                       pd.active_chunk_run_id,pd.approved_metadata_revision_id,
                       mr.title AS document_title,mr.document_code,
                       mr.status AS document_status,mr.confidentiality_level,
                       mr.authority_level,mr.lifecycle_status,
                       mr.source_type AS metadata_source_type,
                       mr.parse_run_id AS metadata_parse_run_id,
                       cr.parse_run_id,cr.status,cr.review_status,cr.source_scope
                FROM policy_document pd
                JOIN chunk_run cr ON cr.id=:p0 AND cr.document_id=pd.id
                JOIN document_metadata_revision mr ON mr.id=:p1 AND mr.document_id=pd.id
                WHERE pd.id=:p2
                """), {'p0': expected["chunk_run_id"], 'p1': expected["metadata_revision_id"], 'p2': expected["document_id"]}).mappings().fetchone()
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
            transition_error = status_transition_error(
                str(row["metadata_source_type"]), row["document_status"]
            )
            if transition_error:
                raise ValueError(
                    f"制度 {expected['document_id']} 的元数据生命周期不一致：{transition_error}"
                )

            chunks = self.repository.run(sql_text("""
                SELECT id,chunk_key,retrieval_text_hash,parent_chunk_id,
                       chunk_type,path_text,page_start,page_end
                FROM policy_chunk
                WHERE chunk_run_id=:p0 AND is_retrievable=1 AND chunk_role='retrieval'
                ORDER BY chunk_index
                """), {'p0': expected["chunk_run_id"]}).mappings().fetchall()
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
        row = self.repository.run(sql_text("""
            SELECT * FROM index_run
            WHERE profile_id=:p0 AND source_manifest_hash=:p1
              AND embedding_contract_hash=:p2 AND config_hash=:p3
            """), {'p0': profile_id, 'p1': source_manifest_hash, 'p2': embedding_contract_hash, 'p3': config_hash}).mappings().fetchone()
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
            cursor = self.repository.run(sql_text("""
                INSERT INTO index_run (
                    profile_id, source_manifest_hash, embedding_provider,
                    embedding_model, embedding_model_revision,
                    embedding_contract_json, embedding_contract_hash,
                    dimension, distance_metric, vector_name, collection_name,
                    alias_name, point_schema_version, config_json, config_hash,
                    indexer_version, status, activation_status, expected_count,
                    started_at, created_at
                ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14, :p15,
                          'queued', 'inactive', :p16, :p17, :p18) RETURNING id"""), {'p0': profile_id, 'p1': source_manifest_hash, 'p2': contract["provider"], 'p3': contract["model"], 'p4': contract["model_revision"], 'p5': contract_json, 'p6': contract_hash, 'p7': contract["dimension"], 'p8': contract["distance_metric"], 'p9': contract["vector_name"], 'p10': collection_name, 'p11': alias_name, 'p12': point_schema_version, 'p13': config_json, 'p14': config_hash, 'p15': indexer_version, 'p16': expected_count, 'p17': now, 'p18': now})
            run_id = int(cursor.scalar_one())
            self.repository.run(sql_text("""
                INSERT INTO index_run_source (
                    index_run_id, document_id, parse_run_id, chunk_run_id, metadata_revision_id,
                    retrievable_count, source_digest, created_at
                ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7)
                """), [dict(zip(('p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7'), row, strict=True)) for row in [
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
                ]])
            self.repository.run(sql_text("""
                UPDATE index_profile
                SET latest_index_run_id=:p0, updated_at=:p1
                WHERE id=:p2
                """), {'p0': run_id, 'p1': now, 'p2': profile_id})
        return self.get_run(run_id)

    def get_run(self, run_id: int) -> dict[str, Any]:
        row = self.repository.run(sql_text('SELECT * FROM index_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"IndexRun {run_id} 不存在")
        return dict(row)

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        table = knowledge_metadata.tables["index_run"]
        self.repository.run(update(table).where(table.c.id == run_id).values(**fields))
        self.repository.save()

    def ensure_chunk_records(
        self,
        run_id: int,
        collection_name: str,
        contract_hash: str,
        point_id_factory: Any,
    ) -> None:
        rows = self.repository.run(sql_text("""
            SELECT pc.id, pc.retrieval_text, pc.retrieval_text_hash
            FROM index_run_source src
            JOIN policy_chunk pc ON pc.chunk_run_id=src.chunk_run_id
            WHERE src.index_run_id=:p0
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            ORDER BY src.document_id, pc.chunk_index
            """), {'p0': run_id}).mappings().fetchall()
        now = utc_now()
        with self.transaction():
            for row in rows:
                actual_hash = sha256_text(str(row["retrieval_text"]))
                if actual_hash != str(row["retrieval_text_hash"]):
                    raise ValueError(f"Chunk {row['id']} retrieval_text_hash 不一致")
                self.repository.run(sql_text("""
                    INSERT INTO chunk_index_record (
                        index_run_id, chunk_id, point_id, collection_name,
                        embedding_input_hash, embedding_contract_hash,
                        status, created_at
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, 'pending', :p6)
                     ON CONFLICT (index_run_id, chunk_id) DO NOTHING RETURNING id"""), {'p0': run_id, 'p1': int(row["id"]), 'p2': str(point_id_factory(int(row["id"]))), 'p3': collection_name, 'p4': actual_hash, 'p5': contract_hash, 'p6': now})

    def pending_records(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.repository.run(sql_text("""
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
            WHERE cir.index_run_id=:p0 AND cir.status!='verified'
            ORDER BY cir.id
            """), {'p0': run_id}).mappings().fetchall()
        return [dict(row) for row in rows]

    def all_records(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.repository.run(sql_text('SELECT * FROM chunk_index_record WHERE index_run_id=:p0 ORDER BY id'), {'p0': run_id}).mappings().fetchall()
        return [dict(row) for row in rows]

    def mark_embedding(self, record_ids: Sequence[int]) -> None:
        if not record_ids:
            return
        with self.transaction():
            self.repository.run(sql_text("""
                UPDATE chunk_index_record
                SET status='embedding', attempt_count=attempt_count+1,
                    error_stage=NULL, error_code=NULL, error_message=NULL
                WHERE id=:p0
                """), [dict(zip(('p0',), row, strict=True)) for row in [(record_id,) for record_id in record_ids]])

    def mark_indexed(
        self,
        record_id: int,
        *,
        dimension: int,
        vector_norm: float,
        payload_hash: str,
    ) -> None:
        self.repository.run(sql_text("""
            UPDATE chunk_index_record
            SET status='indexed', vector_dimension=:p0, vector_norm=:p1, payload_hash=:p2,
                indexed_at=:p3, error_stage=NULL, error_code=NULL, error_message=NULL
            WHERE id=:p4
            """), {'p0': dimension, 'p1': vector_norm, 'p2': payload_hash, 'p3': utc_now(), 'p4': record_id})
        self.repository.save()

    def mark_failed(
        self, record_ids: Sequence[int], stage: str, code: str, message: str
    ) -> None:
        if not record_ids:
            return
        with self.transaction():
            self.repository.run(sql_text("""
                UPDATE chunk_index_record
                SET status='failed', error_stage=:p0, error_code=:p1, error_message=:p2
                WHERE id=:p3
                """), [dict(zip(('p0', 'p1', 'p2', 'p3'), row, strict=True)) for row in [(stage, code, message[:2000], record_id) for record_id in record_ids]])

    def mark_verified(self, record_id: int) -> None:
        self.repository.run(sql_text("""
            UPDATE chunk_index_record
            SET status='verified', verified_at=:p0, error_stage=NULL,
                error_code=NULL, error_message=NULL
            WHERE id=:p1
            """), {'p0': utc_now(), 'p1': record_id})
        self.repository.save()

    def refresh_counts(self, run_id: int) -> dict[str, int]:
        row = self.repository.run(sql_text("""
            SELECT
                SUM(CASE WHEN status IN ('indexed', 'verified') THEN 1 ELSE 0 END) AS indexed_count,
                SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) AS verified_count,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count
            FROM chunk_index_record WHERE index_run_id=:p0
            """), {'p0': run_id}).mappings().fetchone()
        counts = {
            "indexed_count": int(row["indexed_count"] or 0),
            "verified_count": int(row["verified_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
        }
        self.update_run(run_id, **counts)
        return counts

    def sources_are_current(self, run_id: int) -> bool:
        mismatch = self.repository.run(sql_text("""
            SELECT COUNT(*)
            FROM index_run_source src
            JOIN policy_document pd ON pd.id=src.document_id
            WHERE src.index_run_id=:p0
              AND (
                    pd.active_chunk_run_id IS NULL
                 OR pd.active_chunk_run_id!=src.chunk_run_id
                 OR pd.approved_metadata_revision_id IS NULL
                 OR pd.approved_metadata_revision_id!=src.metadata_revision_id
              )
            """), {'p0': run_id}).scalar_one()
        return int(mismatch) == 0

    def activate_run(self, profile_id: int, run_id: int) -> None:
        """在 alias 已核验后，用短事务切换 SQLite active 指针。"""

        now = utc_now()
        with self.transaction():
            profile = self.repository.run(sql_text('SELECT active_index_run_id FROM index_profile WHERE id=:p0'), {'p0': profile_id}).mappings().fetchone()
            old_run_id = profile["active_index_run_id"] if profile else None
            if old_run_id is not None and int(old_run_id) != run_id:
                self.repository.run(sql_text("UPDATE index_run SET activation_status='superseded' WHERE id=:p0"), {'p0': int(old_run_id)})
            self.repository.run(sql_text("""
                UPDATE index_profile
                SET active_index_run_id=:p0, updated_at=:p1
                WHERE id=:p2
                """), {'p0': run_id, 'p1': now, 'p2': profile_id})
            self.repository.run(sql_text("""
                UPDATE index_run
                SET activation_status='active', status='succeeded', finished_at=:p0,
                    error_code=NULL, error_message=NULL
                WHERE id=:p1
                """), {'p0': now, 'p1': run_id})
            sources = self.repository.run(sql_text("""
                SELECT src.document_id, src.metadata_revision_id,
                       d.active_metadata_revision_id
                FROM index_run_source src
                JOIN policy_document d ON d.id=src.document_id
                WHERE src.index_run_id=:p0
                """), {'p0': run_id}).mappings().fetchall()
            for source in sources:
                revision_id = source["metadata_revision_id"]
                if revision_id is None:
                    raise RuntimeError("IndexRun缺少冻结的元数据修订")
                previous_id = source["active_metadata_revision_id"]
                if previous_id is not None and int(previous_id) != int(revision_id):
                    self.repository.run(sql_text("""
                        UPDATE document_metadata_revision
                        SET lifecycle_status='SUPERSEDED', updated_at=:p0
                        WHERE id=:p1 AND lifecycle_status='PUBLISHED'
                        """), {'p0': now, 'p1': int(previous_id)})
                self.repository.run(sql_text("""
                    UPDATE document_metadata_revision
                    SET lifecycle_status='PUBLISHED', published_at=:p0, updated_at=:p1
                    WHERE id=:p2
                    """), {'p0': now, 'p1': now, 'p2': int(revision_id)})
                self.repository.run(sql_text("""
                    UPDATE policy_document
                    SET active_metadata_revision_id=:p0,
                        title=(SELECT title FROM document_metadata_revision WHERE id=:p1),
                        document_code=(SELECT document_code FROM document_metadata_revision WHERE id=:p2),
                        document_type=(SELECT document_type FROM document_metadata_revision WHERE id=:p3),
                        issuing_org=(SELECT issuing_org FROM document_metadata_revision WHERE id=:p4),
                        addressee_text=(SELECT addressee_text FROM document_metadata_revision WHERE id=:p5),
                        authority_level=(SELECT authority_level FROM document_metadata_revision WHERE id=:p6),
                        publish_date=(SELECT publish_date FROM document_metadata_revision WHERE id=:p7),
                        effective_date=(SELECT effective_date FROM document_metadata_revision WHERE id=:p8),
                        expiry_date=(SELECT expiry_date FROM document_metadata_revision WHERE id=:p9),
                        status=(SELECT status FROM document_metadata_revision WHERE id=:p10),
                        version=(SELECT version FROM document_metadata_revision WHERE id=:p11),
                        owner_department=(SELECT owner_department FROM document_metadata_revision WHERE id=:p12),
                        confidentiality_level=(SELECT confidentiality_level FROM document_metadata_revision WHERE id=:p13),
                        updated_at=:p14
                    WHERE id=:p15
                    """), dict(zip(('p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13', 'p14', 'p15'), (
                        int(revision_id),
                        *([int(revision_id)] * 13),
                        now,
                        int(source["document_id"]),
                    ), strict=True)))

    def active_context(self, profile_name: str) -> dict[str, Any]:
        row = self.repository.run(sql_text("""
            SELECT ip.profile_name, ip.alias_name, ip.active_index_run_id,
                   ir.*
            FROM index_profile ip
            JOIN index_run ir ON ir.id=ip.active_index_run_id
            WHERE ip.profile_name=:p0
            """), {'p0': profile_name}).mappings().fetchone()
        if row is None:
            raise ValueError(f"索引配置 {profile_name} 尚无 active IndexRun")
        return dict(row)

    def hydrate_chunks(self, index_run_id: int, chunk_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        if not chunk_ids:
            return {}
        rows = self.repository.run(
            sql_text("""
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
              ON src.index_run_id=:run_id AND src.chunk_run_id=pc.chunk_run_id
            JOIN document_metadata_revision mr ON mr.id=src.metadata_revision_id
            WHERE pc.id IN :chunk_ids
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            """).bindparams(bindparam("chunk_ids", expanding=True)),
            {"run_id": index_run_id, "chunk_ids": list(chunk_ids)},
        ).mappings().fetchall()
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
        rows = self.repository.run(
            sql_text("""
            SELECT csn.*, pn.node_type, pn.node_number, pn.title AS node_title,
                   pn.path_text AS node_path_text, pn.page_start AS node_page_start,
                   pn.page_end AS node_page_end
            FROM chunk_source_node csn
            JOIN policy_chunk pc ON pc.id=csn.chunk_id
            JOIN policy_node pn ON pn.id=csn.node_id
            JOIN index_run_source src
              ON src.index_run_id=:run_id AND src.chunk_run_id=pc.chunk_run_id
            WHERE csn.chunk_id IN :chunk_ids
              AND pc.is_retrievable=1 AND pc.chunk_role='retrieval'
            ORDER BY csn.chunk_id, csn.source_order, csn.id
            """).bindparams(bindparam("chunk_ids", expanding=True)),
            {"run_id": index_run_id, "chunk_ids": list(chunk_ids)},
        ).mappings().fetchall()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(int(row["chunk_id"]), []).append(dict(row))
        return result
