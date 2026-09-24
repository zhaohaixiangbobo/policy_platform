"""正式索引构建、校验和发布流程。

流程冻结全部 active ChunkRun，生成确定性 point，写入不可见的版本化 collection，
全量核验后才切换 alias 和 SQLite active IndexRun。失败运行不会影响既有 active 索引。
"""

from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from .config import EmbeddingContract, IndexConfig, canonical_json, sha256_text
from .database import IndexDatabase, utc_now
from .qdrant_store import StoredPoint, VectorPoint


class EmbeddingClient(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def collection_exists(self, collection_name: str) -> bool: ...

    def ensure_collection(
        self, collection_name: str, *, vector_name: str, dimension: int, distance_metric: str
    ) -> None: ...

    def ensure_payload_indexes(self, collection_name: str) -> None: ...

    def upsert(
        self, collection_name: str, vector_name: str, points: Sequence[VectorPoint]
    ) -> None: ...

    def exact_count(self, collection_name: str) -> int: ...

    def retrieve(
        self,
        collection_name: str,
        point_ids: Sequence[str],
        *,
        vector_name: str,
        with_vectors: bool,
    ) -> dict[str, StoredPoint]: ...

    def alias_target(self, alias_name: str) -> str | None: ...

    def switch_alias(self, alias_name: str, collection_name: str) -> None: ...


class PolicyIndexer:
    """制度 Chunk 的 Dense 索引构建器。"""

    def __init__(
        self,
        database_path: Path,
        *,
        embedding_client: EmbeddingClient,
        vector_store: VectorStore,
        contract: EmbeddingContract | None = None,
        config: IndexConfig | None = None,
    ) -> None:
        self.db = IndexDatabase(database_path)
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.contract = contract or EmbeddingContract()
        self.config = config or IndexConfig()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "PolicyIndexer":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def build(
        self,
        *,
        activate: bool = True,
        required_document_ids: Sequence[int] | None = None,
        frozen_sources: Sequence[dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        """构建或幂等复用索引，必要时发布为 active。"""

        profile = self.db.get_or_create_profile(
            self.config.profile_name, self.config.alias_name
        )
        self._reconcile_switching_run(int(profile["id"]))
        sources = (
            self.db.freeze_exact_sources(frozen_sources)
            if frozen_sources is not None
            else self.db.freeze_active_sources(required_document_ids)
        )
        manifest_hash = self.db.source_manifest_hash(sources)
        collection_name = self.config.collection_name(
            manifest_hash, self.contract.contract_hash
        )
        run = self.db.find_run(
            int(profile["id"]),
            manifest_hash,
            self.contract.contract_hash,
            self.config.config_hash,
        )
        if run is None:
            run = self.db.create_run(
                profile_id=int(profile["id"]),
                sources=sources,
                source_manifest_hash=manifest_hash,
                contract=self.contract.to_dict(),
                contract_json=self.contract.canonical_json,
                contract_hash=self.contract.contract_hash,
                collection_name=collection_name,
                alias_name=self.config.alias_name,
                point_schema_version=self.config.point_schema_version,
                config_json=self.config.canonical_json,
                config_hash=self.config.config_hash,
                indexer_version=self.config.indexer_version,
            )

        run_id = int(run["id"])
        self._assert_storage_available(run, require_collection=run["status"] == "succeeded")
        self.db.ensure_chunk_records(
            run_id,
            collection_name,
            self.contract.contract_hash,
            lambda chunk_id: uuid5(
                NAMESPACE_URL,
                f"policy-index:{self.config.profile_name}:{run_id}:{chunk_id}",
            ),
        )

        if run["status"] != "succeeded":
            self._execute_run(run_id)
        if activate:
            self._activate(int(profile["id"]), run_id)
        return self.summary(run_id, reused=run["status"] == "succeeded")

    def _assert_storage_available(self, run: dict[str, Any], *, require_collection: bool = True) -> None:
        """历史成功与物理可用分离；已清理运行必须显式恢复后才能再次使用。"""
        retired = self.db.connection.execute(
            "SELECT state FROM index_storage_retirement WHERE index_run_id=?", (run["id"],)
        ).fetchone()
        if retired:
            raise ValueError(f"IndexRun {run['id']} 存储已退役（{retired['state']}），请使用新的来源快照构建索引")
        if require_collection:
            name = str(run["collection_name"])
            if not self.vector_store.collection_exists(name):
                raise ValueError(f"IndexRun {run['id']} 物理 collection 缺失，请恢复原快照后重试")
            if self.vector_store.exact_count(name) != int(run["expected_count"]):
                raise ValueError(f"IndexRun {run['id']} 物理 point 数不完整，拒绝复用或发布")

    def _execute_run(self, run_id: int) -> None:
        run = self.db.get_run(run_id)
        self.db.update_run(
            run_id,
            status="running",
            activation_status="inactive",
            error_code=None,
            error_message=None,
        )
        try:
            self.vector_store.ensure_collection(
                str(run["collection_name"]),
                vector_name=self.contract.vector_name,
                dimension=self.contract.dimension,
                distance_metric=self.contract.distance_metric,
            )
            self.vector_store.ensure_payload_indexes(str(run["collection_name"]))
            records = self.db.pending_records(run_id)
            for offset in range(0, len(records), self.config.batch_size):
                batch = records[offset : offset + self.config.batch_size]
                self._process_batch(run_id, str(run["collection_name"]), batch)
            self.db.update_run(run_id, status="verifying")
            self._verify_run(run_id)
            if self.config.strict_source_freshness and not self.db.sources_are_current(run_id):
                raise RuntimeError("构建期间 active ChunkRun 已变化，拒绝发布过期索引")
            self.db.update_run(
                run_id,
                status="succeeded",
                finished_at=utc_now(),
                error_code=None,
                error_message=None,
            )
        except Exception as exc:
            self.db.refresh_counts(run_id)
            self.db.update_run(
                run_id,
                status="failed",
                activation_status="inactive",
                finished_at=utc_now(),
                error_code=type(exc).__name__,
                error_message=str(exc)[:2000],
            )
            raise

    def _process_batch(
        self, run_id: int, collection_name: str, batch: Sequence[dict[str, Any]]
    ) -> None:
        record_ids = [int(record["id"]) for record in batch]
        self.db.mark_embedding(record_ids)
        try:
            vectors = self.embedding_client.embed(
                [str(record["retrieval_text"]) for record in batch]
            )
            if len(vectors) != len(batch):
                raise ValueError("Embedding 返回数量与 batch 不一致")
            points: list[VectorPoint] = []
            payloads: list[dict[str, Any]] = []
            for record, vector in zip(batch, vectors, strict=True):
                if len(vector) != self.contract.dimension:
                    raise ValueError(f"Chunk {record['chunk_id']} 向量维度错误")
                payload = self._payload(run_id, record)
                payloads.append(payload)
                points.append(
                    VectorPoint(
                        point_id=str(record["point_id"]),
                        vector=vector,
                        payload=payload,
                    )
                )
            self.vector_store.upsert(collection_name, self.contract.vector_name, points)
            for record, vector, payload in zip(batch, vectors, payloads, strict=True):
                norm = math.sqrt(sum(float(value) ** 2 for value in vector))
                self.db.mark_indexed(
                    int(record["id"]),
                    dimension=len(vector),
                    vector_norm=norm,
                    payload_hash=sha256_text(canonical_json(payload)),
                )
        except Exception as exc:
            self.db.mark_failed(record_ids, "embedding_or_upsert", type(exc).__name__, str(exc))
            raise

    def _payload(self, run_id: int, record: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "point_schema_version": self.config.point_schema_version,
            "index_run_id": run_id,
            "chunk_id": int(record["chunk_id"]),
            "chunk_key": str(record["chunk_key"]),
            "document_id": int(record["document_id"]),
            "parse_run_id": int(record["parse_run_id"]),
            "chunk_run_id": int(record["chunk_run_id"]),
            "chunk_type": str(record["chunk_type"]),
            "document_status": str(record["document_status"]),
            "embedding_input_hash": str(record["embedding_input_hash"]),
        }
        optional = {
            "parent_chunk_id": record.get("parent_chunk_id"),
            "document_title": record.get("document_title"),
            "document_code": record.get("document_code"),
            "confidentiality_level": record.get("confidentiality_level"),
            "authority_level": record.get("authority_level"),
            "path_text": record.get("path_text"),
            "page_start": record.get("page_start"),
            "page_end": record.get("page_end"),
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload

    def _verify_run(self, run_id: int) -> None:
        run = self.db.get_run(run_id)
        records = self.db.all_records(run_id)
        expected = int(run["expected_count"])
        if len(records) != expected:
            raise RuntimeError(
                f"本地索引记录数不匹配：expected={expected}, actual={len(records)}"
            )
        qdrant_count = self.vector_store.exact_count(str(run["collection_name"]))
        if qdrant_count != expected:
            raise RuntimeError(
                f"Qdrant point 数不匹配：expected={expected}, actual={qdrant_count}"
            )

        for offset in range(0, len(records), 64):
            batch = records[offset : offset + 64]
            stored = self.vector_store.retrieve(
                str(run["collection_name"]),
                [str(record["point_id"]) for record in batch],
                vector_name=self.contract.vector_name,
                with_vectors=True,
            )
            for record in batch:
                point = stored.get(str(record["point_id"]))
                self._verify_point(run_id, record, point)
                self.db.mark_verified(int(record["id"]))
        counts = self.db.refresh_counts(run_id)
        if (
            counts["indexed_count"] != expected
            or counts["verified_count"] != expected
            or counts["failed_count"] != 0
        ):
            raise RuntimeError(f"索引核验统计不满足发布条件：{counts}")

    def _verify_point(
        self,
        run_id: int,
        record: dict[str, Any],
        point: StoredPoint | None,
    ) -> None:
        if point is None:
            raise RuntimeError(f"Qdrant 缺少 point {record['point_id']}")
        if point.vector is None or len(point.vector) != self.contract.dimension:
            raise RuntimeError(f"Point {record['point_id']} 向量维度错误")
        payload = point.payload
        expected_fields = {
            "index_run_id": run_id,
            "chunk_id": int(record["chunk_id"]),
            "embedding_input_hash": str(record["embedding_input_hash"]),
            "point_schema_version": self.config.point_schema_version,
        }
        for field, expected_value in expected_fields.items():
            if payload.get(field) != expected_value:
                raise RuntimeError(
                    f"Point {record['point_id']} payload.{field} 不一致"
                )
        if sha256_text(canonical_json(payload)) != str(record["payload_hash"]):
            raise RuntimeError(f"Point {record['point_id']} payload_hash 不一致")

    def _activate(self, profile_id: int, run_id: int) -> None:
        run = self.db.get_run(run_id)
        if run["status"] != "succeeded":
            raise ValueError("只有 succeeded IndexRun 才能激活")
        self._assert_storage_available(run)
        if self.config.strict_source_freshness and not self.db.sources_are_current(run_id):
            raise ValueError("IndexRun 来源已不是当前 active ChunkRun")
        self.db.update_run(run_id, activation_status="switching")
        self.vector_store.switch_alias(
            str(run["alias_name"]), str(run["collection_name"])
        )
        actual = self.vector_store.alias_target(str(run["alias_name"]))
        if actual != str(run["collection_name"]):
            raise RuntimeError(
                f"Alias 切换核验失败：expected={run['collection_name']}, actual={actual}"
            )
        self.db.activate_run(profile_id, run_id)

    def activate(self, run_id: int) -> dict[str, Any]:
        """人工发布已经完成并核验的IndexRun。"""

        run = self.db.get_run(run_id)
        self._activate(int(run["profile_id"]), run_id)
        return self.summary(run_id)

    def _reconcile_switching_run(self, profile_id: int) -> None:
        rows = self.db.connection.execute(
            """
            SELECT * FROM index_run
            WHERE profile_id=? AND activation_status='switching'
            ORDER BY id DESC
            """,
            (profile_id,),
        ).fetchall()
        for row in rows:
            target = self.vector_store.alias_target(str(row["alias_name"]))
            if target == str(row["collection_name"]) and row["status"] == "succeeded":
                self.db.activate_run(profile_id, int(row["id"]))
            elif target != str(row["collection_name"]):
                self.db.update_run(int(row["id"]), activation_status="inactive")

    def summary(self, run_id: int, *, reused: bool = False) -> dict[str, Any]:
        run = self.db.get_run(run_id)
        profile = self.db.connection.execute(
            "SELECT * FROM index_profile WHERE id=?", (int(run["profile_id"]),)
        ).fetchone()
        return {
            "index_run_id": run_id,
            "profile_name": str(profile["profile_name"]),
            "collection_name": str(run["collection_name"]),
            "alias_name": str(run["alias_name"]),
            "status": str(run["status"]),
            "activation_status": str(run["activation_status"]),
            "active_index_run_id": profile["active_index_run_id"],
            "latest_index_run_id": profile["latest_index_run_id"],
            "expected_count": int(run["expected_count"]),
            "indexed_count": int(run["indexed_count"]),
            "verified_count": int(run["verified_count"]),
            "failed_count": int(run["failed_count"]),
            "reused": reused,
        }
