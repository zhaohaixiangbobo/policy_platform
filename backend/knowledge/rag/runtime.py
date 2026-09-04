"""文件说明：集中构建和关闭正式RAG运行时资源。

命令行、压测器和后续Windows测试版API复用同一构造逻辑，保证Dense Top20、Rerank Top8、
Context、Generator与Prompt契约一致。运行时只执行查询，不修改SQLite、Qdrant或运行指针。
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..indexing.config import EmbeddingContract, RerankConfig, RerankerContract
from ..indexing.database import IndexDatabase
from ..indexing.embedding import OpenAIEmbeddingClient
from ..indexing.qdrant_store import QdrantVectorStore
from ..retrieval.rerank_retriever import DenseRerankRetriever
from ..retrieval.reranker import OpenAIRerankClient
from ..retrieval.retriever import DenseRetriever, SearchFilters

from .config import ContextBuilderConfig, GenerationConfig, GeneratorContract, RagPipelineConfig
from .context_builder import ContextBuilder
from .generator import OpenAIGeneratorClient
from .pipeline import RagPipeline, RagResponse
from .prompt import PromptContract
from .quality_gate import AnswerQualityGate, GeneratorSupportVerifier


def _environment_bool(name: str, default: bool) -> bool:
    """严格解析布尔环境变量，避免拼写错误静默启用高成本能力。"""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name}必须是true/false、1/0、yes/no或on/off")


@dataclass(frozen=True)
class RagRuntimeSettings:
    """不包含密钥的运行时服务地址与模型契约参数。"""

    db_path: Path = Path(".policy_parser_output/policy_parser.db")
    qdrant_url: str = "http://127.0.0.1:6333"
    embedding_url: str = "http://10.9.7.1:8001/v1/embeddings"
    embedding_model: str = "qwen3-embedding-4b"
    embedding_revision: str = "deployment-unreported"
    rerank_url: str = "http://10.9.7.1:8004/v1/rerank"
    rerank_model: str = "qwen3-reranker-4b"
    rerank_revision: str = "deployment-unreported"
    generator_url: str = "http://10.9.7.1:8000/v1"
    generator_model: str = "Qwen/Qwen3.8-27B"
    generator_revision: str = "deployment-unreported"
    profile_name: str = "policy_platform_dense"
    quality_gate_enabled: bool = False

    @classmethod
    def from_environment(cls, **overrides: Any) -> "RagRuntimeSettings":
        """读取非密钥环境变量；显式参数优先于环境变量。"""

        defaults: dict[str, Any] = {
            "db_path": Path(os.getenv("POLICY_DB_PATH", ".policy_parser_output/policy_parser.db")),
            "qdrant_url": os.getenv("POLICY_QDRANT_URL", "http://127.0.0.1:6333"),
            "embedding_url": os.getenv(
                "POLICY_EMBEDDING_URL", "http://10.9.7.1:8001/v1/embeddings"
            ),
            "embedding_model": os.getenv("POLICY_EMBEDDING_MODEL", "qwen3-embedding-4b"),
            "embedding_revision": os.getenv(
                "POLICY_EMBEDDING_REVISION", "deployment-unreported"
            ),
            "rerank_url": os.getenv(
                "POLICY_RERANK_URL", "http://10.9.7.1:8004/v1/rerank"
            ),
            "rerank_model": os.getenv("POLICY_RERANK_MODEL", "qwen3-reranker-4b"),
            "rerank_revision": os.getenv(
                "POLICY_RERANK_REVISION", "deployment-unreported"
            ),
            "generator_url": os.getenv("POLICY_GENERATOR_URL", "http://10.9.7.1:8000/v1"),
            "generator_model": os.getenv(
                "POLICY_GENERATOR_MODEL", "Qwen/Qwen3.8-27B"
            ),
            "generator_revision": os.getenv(
                "POLICY_GENERATOR_REVISION", "deployment-unreported"
            ),
            "profile_name": os.getenv("POLICY_INDEX_PROFILE", "policy_platform_dense"),
            "quality_gate_enabled": _environment_bool(
                "POLICY_QUALITY_GATE_ENABLED", False
            ),
        }
        defaults.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**defaults)

    def public_dict(self) -> dict[str, Any]:
        """返回可写入压测清单的非敏感配置。"""

        return {
            "db_path": str(self.db_path.resolve()),
            "qdrant_url": self.qdrant_url,
            "embedding_url": self.embedding_url,
            "embedding_model": self.embedding_model,
            "embedding_revision": self.embedding_revision,
            "rerank_url": self.rerank_url,
            "rerank_model": self.rerank_model,
            "rerank_revision": self.rerank_revision,
            "generator_url": self.generator_url,
            "generator_model": self.generator_model,
            "generator_revision": self.generator_revision,
            "profile_name": self.profile_name,
            "quality_gate_enabled": self.quality_gate_enabled,
        }


class RagRuntime:
    """持有单个工作线程专用的数据库连接和HTTP客户端。"""

    def __init__(self, settings: RagRuntimeSettings) -> None:
        self.settings = settings
        self._closed = False
        self.embedding_contract = EmbeddingContract(
            model=settings.embedding_model,
            model_revision=settings.embedding_revision,
            dimension=2560,
        )
        self.reranker_contract = RerankerContract(
            model=settings.rerank_model,
            model_revision=settings.rerank_revision,
        )
        self.generator_contract = GeneratorContract(
            base_url=settings.generator_url,
            model=settings.generator_model,
            model_revision=settings.generator_revision,
        )
        self.rerank_config = RerankConfig.rag_context_v3()
        self.context_config = ContextBuilderConfig()
        self.generation_config = GenerationConfig()
        self.pipeline_config = RagPipelineConfig()
        stack = ExitStack()
        try:
            self.embedding = OpenAIEmbeddingClient(
                settings.embedding_url,
                self.embedding_contract,
                api_key=os.getenv("POLICY_EMBEDDING_API_KEY"),
            )
            stack.callback(self.embedding.session.close)
            self.store = QdrantVectorStore(
                settings.qdrant_url,
                api_key=os.getenv("POLICY_QDRANT_API_KEY"),
            )
            close_store = getattr(self.store.client, "close", None)
            if callable(close_store):
                stack.callback(close_store)
            self.dense = stack.enter_context(
                DenseRetriever(
                    settings.db_path,
                    embedding_client=self.embedding,
                    vector_store=self.store,
                    contract=self.embedding_contract,
                    profile_name=settings.profile_name,
                )
            )
            self.reranker = stack.enter_context(
                OpenAIRerankClient(
                    settings.rerank_url,
                    self.reranker_contract,
                    self.rerank_config,
                    api_key=os.getenv("POLICY_RERANK_API_KEY"),
                )
            )
            self.database = stack.enter_context(IndexDatabase(settings.db_path))
            self.generator = stack.enter_context(
                OpenAIGeneratorClient(
                    self.generator_contract,
                    self.generation_config,
                    api_key=os.getenv("POLICY_GENERATOR_API_KEY", "EMPTY"),
                    retry_backoff_seconds=(
                        self.pipeline_config.transport_retry_backoff_seconds
                    ),
                )
            )
            retriever = DenseRerankRetriever(
                self.dense,
                self.reranker,
                embedding_contract=self.embedding_contract,
                reranker_contract=self.reranker_contract,
                config=self.rerank_config,
            )
            self.pipeline = RagPipeline(
                retriever,
                ContextBuilder(
                    self.database,
                    config=self.context_config,
                    profile_name=settings.profile_name,
                ),
                self.generator,
                prompt=PromptContract(),
                quality_gate=AnswerQualityGate(
                    (
                        GeneratorSupportVerifier(self.generator)
                        if settings.quality_gate_enabled
                        else None
                    ),
                    enabled=settings.quality_gate_enabled,
                ),
                config=self.pipeline_config,
            )
        except BaseException:
            stack.close()
            raise
        self._resources = stack.pop_all()

    def query(
        self,
        question: str,
        *,
        filters: SearchFilters | None = None,
        include_debug: bool = False,
    ) -> RagResponse:
        """执行一次完整只读RAG查询。"""

        if self._closed:
            raise RuntimeError("RAG运行时已经关闭")
        return self.pipeline.query(question, filters=filters, include_debug=include_debug)

    def close(self) -> None:
        """按依赖反向顺序释放数据库、HTTP会话和Qdrant客户端。"""

        if self._closed:
            return
        self._closed = True
        self._resources.close()

    def __enter__(self) -> "RagRuntime":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
