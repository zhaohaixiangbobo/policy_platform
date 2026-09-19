"""文件说明：冻结Generator与Context Builder第一版契约及稳定哈希。

配置不包含API密钥。所有会改变生成或上下文语义的字段均进入规范化JSON和哈希，
供后续RAG运行、评测和问题复现使用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..indexing.config import canonical_json, sha256_text

from .models import ANSWER_JSON_SCHEMA


class _HashedConfig:
    """为冻结数据类提供统一规范化JSON与哈希。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @property
    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def config_hash(self) -> str:
        return sha256_text(self.canonical_json)


@dataclass(frozen=True)
class GeneratorContract(_HashedConfig):
    """描述8000 Qwen Generator的已验证部署边界。"""

    provider: str = "openai_compatible_vllm"
    base_url: str = "http://10.9.7.1:8000/v1"
    endpoint: str = "/chat/completions"
    model: str = "Qwen/Qwen3.8-27B"
    model_revision: str = "deployment-unreported"
    tokenizer_revision: str = "deployment-unreported"
    service_version: str = "0.1.dev19754+g3a0914114"
    max_context_tokens: int = 262_144
    strict_json_schema_supported: bool = True
    chat_template_kwargs_supported: bool = True
    chat_template_sha256: str = (
        "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"
    )
    contract_version: str = "generator_contract_v1"

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Generator base_url 必须是HTTP(S)地址")
        if not self.model.strip() or self.max_context_tokens <= 0:
            raise ValueError("Generator模型或上下文契约非法")
        if not self.strict_json_schema_supported or not self.chat_template_kwargs_supported:
            raise ValueError("generator_contract_v1要求strict JSON Schema和thinking控制")

    @property
    def contract_hash(self) -> str:
        return self.config_hash


@dataclass(frozen=True)
class GenerationConfig(_HashedConfig):
    """第一版制度问答生成参数。"""

    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 1024
    timeout_seconds: float = 180.0
    max_retries: int = 2
    enable_thinking: bool = False
    application_concurrency_limit: int = 4
    response_format: str = "strict_json_schema"
    schema_name: str = "policy_rag_answer_v3"
    schema_version: str = "policy_rag_answer_schema_v3"
    config_version: str = "generator_runtime_v3"

    def __post_init__(self) -> None:
        if self.temperature != 0 or self.top_p != 1:
            raise ValueError("generator_runtime_v3固定temperature=0、top_p=1")
        if self.max_tokens != 1024:
            raise ValueError("generator_runtime_v3固定max_tokens=1024")
        if self.timeout_seconds != 180 or self.max_retries != 2:
            raise ValueError("generator_runtime_v3固定timeout=180、max_retries=2")
        if self.enable_thinking or self.application_concurrency_limit != 4:
            raise ValueError("generator_runtime_v3固定关闭thinking且并发上限为4")
        if self.response_format != "strict_json_schema":
            raise ValueError("第一版必须使用strict JSON Schema")

    @property
    def schema_hash(self) -> str:
        return sha256_text(canonical_json(ANSWER_JSON_SCHEMA))

    def request_extra_body(self) -> dict[str, Any]:
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def openai_response_format(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.schema_name,
                "strict": True,
                "schema": ANSWER_JSON_SCHEMA,
            },
        }


@dataclass(frozen=True)
class ContextBuilderConfig(_HashedConfig):
    """确定性Top8上下文选择和预算配置。"""

    max_evidence: int = 8
    evidence_budget_tokens: int = 8000
    token_estimator_version: str = "conservative_mixed_v1"
    citation_version: str = "citation_v1"
    evidence_uid_version: str = "evidence_uid_v1"
    parent_expansion_enabled: bool = False
    deduplicate_same_chunk: bool = True
    deduplicate_same_document_text: bool = True
    group_by_document_and_path: bool = True
    builder_version: str = "context_builder_v1"

    def __post_init__(self) -> None:
        if self.max_evidence != 8 or self.evidence_budget_tokens != 8000:
            raise ValueError("context_builder_v1固定Top8和8000-token证据预算")
        if self.parent_expansion_enabled:
            raise ValueError("当前active语料无父子Chunk，第一版禁止启用Parent Expansion")
        if self.token_estimator_version != "conservative_mixed_v1":
            raise ValueError("未知Token估算器版本")
        if self.citation_version != "citation_v1":
            raise ValueError("未知Citation公开契约版本")
        if self.evidence_uid_version != "evidence_uid_v1":
            raise ValueError("未知evidence_uid算法版本")


@dataclass(frozen=True)
class RagPipelineConfig(_HashedConfig):
    """第一版端到端编排与模型输出校验配置。"""

    answer_validation_retries: int = 1
    transport_retry_backoff_seconds: float = 1.0
    pipeline_version: str = "rag_pipeline_v2"

    def __post_init__(self) -> None:
        if self.answer_validation_retries != 1:
            raise ValueError("rag_pipeline_v2固定一次模型输出校验重试")
        if self.transport_retry_backoff_seconds != 1.0:
            raise ValueError("rag_pipeline_v2固定传输重试退避基数为1秒")
