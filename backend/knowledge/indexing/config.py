"""索引模块配置与稳定哈希。

配置分为定义向量空间的 Embedding 契约和控制运行行为的索引配置。所有参与
结果语义的字段都会规范化后计算哈希，避免模型名相同但实际向量空间不同。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def canonical_json(value: Any) -> str:
    """以稳定 UTF-8 JSON 表示配置或 payload。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    """计算 UTF-8 文本的 SHA-256。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmbeddingContract:
    """完整描述一次可复现的 Embedding 向量空间。"""

    provider: str = "openai_compatible"
    model: str = "qwen3-embedding-4b"
    model_revision: str = "deployment-unreported"
    dimension: int = 2560
    normalize_embeddings: bool = True
    distance_metric: str = "cosine"
    vector_name: str = "dense"
    document_input: str = "retrieval_text"
    query_instruction: str = (
        "Given a policy and regulation query, retrieve passages that directly answer it."
    )
    instruction_language: str = "en"
    max_input_tokens: int = 8192
    truncation: str = "reject"
    contract_version: str = "embedding_contract_v1"

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("Embedding dimension 必须大于 0")
        if self.distance_metric != "cosine":
            raise ValueError("当前第一阶段只允许 cosine 距离")
        if not self.vector_name.strip():
            raise ValueError("vector_name 不能为空")
        if self.truncation != "reject":
            raise ValueError("当前版本禁止静默截断，只支持 truncation=reject")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def contract_hash(self) -> str:
        return sha256_text(self.canonical_json)

    def format_query(self, query: str) -> str:
        """按 Qwen3 官方推荐语义为查询添加固定 instruction。"""

        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("检索问题不能为空")
        return f"Instruct: {self.query_instruction}\nQuery:{normalized}"


@dataclass(frozen=True)
class RerankerContract:
    """描述当前 8004 vLLM Reranker 的可审计语义与请求边界。"""

    provider: str = "http_vllm_reranker"
    model: str = "qwen3-reranker-4b"
    model_revision: str = "deployment-unreported"
    service_backend: str = "vllm-qwen3-reranker"
    service_api_version: str = "0.1.0"
    service_revision: str = "deployment-unreported"
    tokenizer_revision: str = "deployment-unreported"
    runner: str = "generate"
    max_input_tokens: int = 8192
    score_semantics: str = "yes_no_probability_like_unverified"
    server_instruction: str = (
        "Given a policy and regulation query, retrieve passages that directly answer it."
    )
    yes_token_id: int = 9693
    no_token_id: int = 2152
    query_input: str = "raw_query"
    document_input: str = "retrieval_text"
    request_fields: tuple[str, ...] = ("model", "query", "documents", "top_n")
    client_instruction_supported: bool = False
    client_truncation_supported: bool = False
    contract_version: str = "reranker_contract_v2"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Reranker model 不能为空")
        if self.max_input_tokens <= 0:
            raise ValueError("Reranker max_input_tokens 必须大于 0")
        if not self.server_instruction.strip() or self.yes_token_id == self.no_token_id:
            raise ValueError("8004 服务端 instruction 或 yes/no token 契约非法")
        expected_fields = ("model", "query", "documents", "top_n")
        if self.request_fields != expected_fields:
            raise ValueError("当前 8004 契约只允许 model/query/documents/top_n")
        if self.client_instruction_supported or self.client_truncation_supported:
            raise ValueError("当前 8004 不支持客户端 instruction 或 truncate 参数")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def contract_hash(self) -> str:
        return sha256_text(self.canonical_json)


@dataclass(frozen=True)
class RerankConfig:
    """版本化的 Dense Top20 → Rerank 客户端运行配置。

    默认值继续对应历史 ``dense20_rerank5_v2``；RAG Context Builder 必须
    显式使用 :meth:`rag_context_v3`，避免原地改变既有评测语义。
    """

    candidate_top_k: int = 20
    output_top_k: int = 5
    request_timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    connection_mode: str = "keep_alive"
    config_version: str = "dense20_rerank5_v2"

    def __post_init__(self) -> None:
        supported_versions = {
            "dense20_rerank5_v2": (20, 5),
            "dense20_rerank8_v3": (20, 8),
        }
        expected = supported_versions.get(self.config_version)
        if expected is None or (self.candidate_top_k, self.output_top_k) != expected:
            raise ValueError("Rerank TopK 必须与已冻结的配置版本严格匹配")
        if self.request_timeout_seconds <= 0 or self.retry_backoff_seconds < 0:
            raise ValueError("Reranker timeout/backoff 配置非法")
        if self.max_retries < 0:
            raise ValueError("Reranker max_retries 不能小于 0")
        if self.connection_mode not in {"keep_alive", "close"}:
            raise ValueError("connection_mode 只允许 keep_alive 或 close")

    @classmethod
    def rag_context_v3(cls, **overrides: Any) -> "RerankConfig":
        """创建面向RAG上下文的 Dense Top20 → Rerank Top8 配置。"""

        values: dict[str, Any] = {
            "candidate_top_k": 20,
            "output_top_k": 8,
            "config_version": "dense20_rerank8_v3",
        }
        values.update(overrides)
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def config_hash(self) -> str:
        return sha256_text(self.canonical_json)


@dataclass(frozen=True)
class IndexConfig:
    """不包含密钥的索引运行配置。"""

    profile_name: str = "policy_platform_dense"
    alias_name: str = "policy_platform_dense_active"
    collection_prefix: str = "policy_platform_dense"
    batch_size: int = 16
    request_timeout_seconds: float = 60.0
    max_retries: int = 3
    point_schema_version: str = "policy_point_v1"
    strict_source_freshness: bool = True
    indexer_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.profile_name.strip() or not self.alias_name.strip():
            raise ValueError("profile_name 与 alias_name 不能为空")
        if self.batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必须大于 0")
        if self.max_retries < 0:
            raise ValueError("max_retries 不能小于 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def config_hash(self) -> str:
        return sha256_text(self.canonical_json)

    def collection_name(self, source_manifest_hash: str, contract_hash: str) -> str:
        """用来源与向量契约生成稳定、可重建的物理 collection 名称。"""

        return (
            f"{self.collection_prefix}_{source_manifest_hash[:12]}_{contract_hash[:8]}"
        )
