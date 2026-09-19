"""文件说明：执行版本化 Dense Top20 → Rerank TopK 的正式两阶段检索器。

Dense 候选仍由 active Qdrant alias 召回并从 SQLite 回读；Reranker 只消费原始 query
和候选 retrieval_text。输出同时保留 Dense 与 Rerank 的 rank/score 及版本化配置哈希。
"""

from __future__ import annotations

from typing import Any, Protocol

from ..indexing.config import (
    EmbeddingContract,
    RerankConfig,
    RerankerContract,
    canonical_json,
    sha256_text,
)
from .reranker import RerankResponse
from .retriever import DenseRetriever, SearchFilters
from ..telemetry import timed, call


class RerankClient(Protocol):
    def rerank(
        self, query: str, documents: list[str], *, top_n: int
    ) -> RerankResponse: ...


class DenseRerankRetriever:
    """组合正式 DenseRetriever 与 Reranker 客户端，不改变任何 active 状态。"""

    def __init__(
        self,
        dense_retriever: DenseRetriever,
        rerank_client: RerankClient,
        *,
        embedding_contract: EmbeddingContract,
        reranker_contract: RerankerContract,
        config: RerankConfig,
    ) -> None:
        self.dense_retriever = dense_retriever
        self.rerank_client = rerank_client
        self.embedding_contract = embedding_contract
        self.reranker_contract = reranker_contract
        self.config = config

    @property
    def retrieval_config_hash(self) -> str:
        """冻结 Dense/Reranker 契约及 TopK 配置，供评测和结果审计。"""

        value = {
            "embedding_contract_hash": self.embedding_contract.contract_hash,
            "reranker_contract_hash": self.reranker_contract.contract_hash,
            "rerank_config_hash": self.config.config_hash,
        }
        return sha256_text(canonical_json(value))

    @timed("retrieval_total")
    def search(
        self, query: str, *, filters: SearchFilters | None = None
    ) -> list[dict[str, Any]]:
        dense_results = self.dense_retriever.search(
            query,
            top_k=self.config.candidate_top_k,
            filters=filters,
        )
        if not dense_results:
            return []
        top_n = min(self.config.output_top_k, len(dense_results))
        response = call("reranker_total", self.rerank_client.rerank,
            query,
            [str(item["retrieval_text"]) for item in dense_results],
            top_n=top_n,
        )
        results: list[dict[str, Any]] = []
        for rerank_rank, rerank_item in enumerate(response.items, start=1):
            dense_item = dense_results[rerank_item.index]
            result = dict(dense_item)
            result.update(
                {
                    "rank": rerank_rank,
                    "dense_rank": int(dense_item["rank"]),
                    "dense_score": float(dense_item["score"]),
                    "rerank_rank": rerank_rank,
                    "rerank_score": rerank_item.score,
                    "rerank_attempts": response.attempts,
                    "rerank_elapsed_seconds": response.elapsed_seconds,
                    "reranker_contract_hash": self.reranker_contract.contract_hash,
                    "rerank_config_hash": self.config.config_hash,
                    "retrieval_config_hash": self.retrieval_config_hash,
                }
            )
            results.append(result)
        return results
