"""Dense Retrieval 与 SQLite 权威 Chunk 回读。

查询只访问 active alias；Qdrant 返回 chunk_id 和分数后，模块从当前 active IndexRun
的来源清单批量读取 SQLite，拒绝无法回读或来自其他索引快照的 point。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from ..indexing.config import EmbeddingContract
from ..indexing.database import IndexDatabase
from ..indexing.qdrant_store import SearchHit
from ..telemetry import call, timed


class QueryEmbeddingClient(Protocol):
    def format_query(self, query: str) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SearchVectorStore(Protocol):
    def alias_target(self, alias_name: str) -> str | None: ...

    def search(
        self,
        alias_name: str,
        *,
        vector_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: Any = None,
    ) -> list[SearchHit]: ...

    def build_filter(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class SearchFilters:
    """可选的 Qdrant 前置过滤条件。"""

    document_ids: tuple[int, ...] = ()
    document_statuses: tuple[str, ...] = ()
    confidentiality_levels: tuple[str, ...] = ()
    authority_levels: tuple[str, ...] = ()


class DenseRetriever:
    """面向 active IndexRun 的 Dense 检索器。"""

    def __init__(
        self,
        database_path: Path,
        *,
        embedding_client: QueryEmbeddingClient,
        vector_store: SearchVectorStore,
        contract: EmbeddingContract | None = None,
        profile_name: str = "policy_platform_dense",
    ) -> None:
        self.db = IndexDatabase(database_path)
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.contract = contract or EmbeddingContract()
        self.profile_name = profile_name

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "DenseRetriever":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @timed("dense_total")
    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        context = self.db.active_context(self.profile_name)
        if context["status"] != "succeeded" or context["activation_status"] != "active":
            raise RuntimeError("active IndexRun 状态不允许检索")
        if str(context["embedding_contract_hash"]) != self.contract.contract_hash:
            raise RuntimeError("查询 Embedding 契约与 active IndexRun 不一致")

        alias_name = str(context["alias_name"])
        actual_target = call("qdrant_alias", self.vector_store.alias_target, alias_name)
        if actual_target != str(context["collection_name"]):
            raise RuntimeError(
                f"Qdrant alias 与 SQLite active IndexRun 不一致：{actual_target}"
            )

        query_input = self.embedding_client.format_query(query)
        vectors = call("embedding_total", self.embedding_client.embed, [query_input])
        if len(vectors) != 1 or len(vectors[0]) != self.contract.dimension:
            raise RuntimeError("Query Embedding 返回不符合 active 契约")
        selected = filters or SearchFilters()
        query_filter = self.vector_store.build_filter(
            document_ids=selected.document_ids,
            document_statuses=selected.document_statuses,
            confidentiality_levels=selected.confidentiality_levels,
            authority_levels=selected.authority_levels,
        )
        hits = call("qdrant_search", self.vector_store.search,
            alias_name,
            vector_name=self.contract.vector_name,
            query_vector=vectors[0],
            limit=top_k,
            query_filter=query_filter,
        )
        chunk_ids = [
            int(hit.payload["chunk_id"])
            for hit in hits
            if isinstance(hit.payload.get("chunk_id"), int)
        ]
        chunks = call("hydrate_chunks", self.db.hydrate_chunks, int(context["id"]), chunk_ids)

        results: list[dict[str, Any]] = []
        for hit in hits:
            chunk_id = hit.payload.get("chunk_id")
            if not isinstance(chunk_id, int) or chunk_id not in chunks:
                # 无法从 active 快照回读的 point 不能进入正式结果。
                continue
            chunk = chunks[chunk_id]
            results.append(
                {
                    "rank": len(results) + 1,
                    "score": hit.score,
                    "point_id": hit.point_id,
                    "index_run_id": int(context["id"]),
                    "chunk_id": chunk_id,
                    "chunk_key": chunk["chunk_key"],
                    "document_id": int(chunk["document_id"]),
                    "document_title": chunk["document_title"],
                    "document_code": chunk["document_code"],
                    "document_status": chunk["document_status"],
                    "chunk_type": chunk["chunk_type"],
                    "path_text": chunk["path_text"],
                    "page_start": chunk["page_start"],
                    "page_end": chunk["page_end"],
                    "primary_node_id": chunk["primary_node_id"],
                    "parent_chunk_id": chunk["parent_chunk_id"],
                    "raw_text": chunk["raw_text"],
                    "retrieval_text": chunk["retrieval_text"],
                }
            )
        return results
