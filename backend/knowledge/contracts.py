"""文件说明：定义独立 RAG HTTP 查询的稳定结果、引用和错误结构。

内部契约沿用rag_api_v1_1字段，保证聊天快照与历史数据语义稳定；不暴露Prompt正文、
reasoning、检索分数、完整Node映射或服务器绝对路径。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

class QueryRequest(BaseModel):
    """制度问答请求。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    query: StrictStr = Field(min_length=1, max_length=4000)
    query_scope: Literal["CURRENT", "HISTORICAL"] = "CURRENT"

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query不能只包含空白字符")
        return value


class CitationResponse(BaseModel):
    """由 Citation Registry 生成的公开引用。"""

    model_config = ConfigDict(extra="forbid")

    citation_version: Literal["citation_v1"]
    evidence_uid_version: Literal["evidence_uid_v1"]
    label: str
    evidence_uid: str
    document_id: int
    primary_node_id: int | None
    parse_run_id: int
    chunk_run_id: int
    index_run_id: int
    chunk_id: int
    document_title: str
    document_code: str | None
    document_status: str
    source_reference: str
    path_text: str | None
    page_start: int | None
    page_end: int | None
    quote: str
    truncated: bool
    snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ConflictPositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    citations: list[str]


class ConflictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    positions: list[ConflictPositionResponse]


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_run_id: int
    dense_count: int
    rerank_count: int
    rerank_returned_count: int


class LatencyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: float
    retrieval: float
    context: float
    llm: float


class QualityGateResponse(BaseModel):
    """可供平台持久化的质量门禁摘要。"""

    model_config = ConfigDict(extra="forbid")

    version: str
    status: Literal["PASS", "DOWNGRADED", "NOT_REQUIRED"]
    semantic_verification: str
    checked_claim_count: int
    reason_codes: list[str]
    verifier_schema_version: str
    verifier_schema_hash: str
    verifier_prompt_hash: str


class ProvenanceResponse(BaseModel):
    """不含Prompt正文与reasoning的回答生成快照。"""

    model_config = ConfigDict(extra="forbid")

    rag_version: str
    generator_model: str
    generator_revision: str
    prompt_version: str
    prompt_schema_version: str
    retrieval_config_hash: str
    context_config_hash: str
    rewrite_used: bool


class QueryResponse(BaseModel):
    """与 rag_api_v1_1 对齐的离线兼容响应模型。"""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["rag_api_v1_1"]
    request_id: str
    status: Literal["ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICT"]
    answerable: bool
    answer: str
    citations: list[CitationResponse]
    conflicts: list[ConflictResponse]
    warnings: list[str]
    retrieval: RetrievalResponse
    quality_gate: QualityGateResponse
    provenance: ProvenanceResponse
    latency_ms: LatencyResponse


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    retryable: bool


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


def public_query_response(result: Any, request_id: str) -> QueryResponse:
    """将RAG内部可审计响应裁剪为Platform可持久化契约。"""

    value = result.to_dict(include_debug=False)
    retrieval = value["retrieval"]
    context = value["context"]
    generation = value["generation"]
    quality_gate = value["quality_gate"]
    latency = value["latency_ms"]
    return QueryResponse(
        contract_version="rag_api_v1_1",
        request_id=request_id,
        status=value["status"],
        answerable=bool(value["answerable"]),
        answer=str(value["answer"]),
        citations=[CitationResponse.model_validate(item) for item in value["citations"]],
        conflicts=[ConflictResponse.model_validate(item) for item in value["conflicts"]],
        warnings=[str(item) for item in value["warnings"]],
        retrieval=RetrievalResponse(
            index_run_id=int(retrieval["index_run_id"]),
            dense_count=int(retrieval["dense_configured_count"]),
            rerank_count=int(retrieval["rerank_configured_count"]),
            rerank_returned_count=int(retrieval["rerank_returned_count"]),
        ),
        quality_gate=QualityGateResponse(
            version=str(quality_gate["version"]),
            status=str(quality_gate["status"]),
            semantic_verification=str(quality_gate["semantic_verification"]),
            checked_claim_count=int(quality_gate["checked_claim_count"]),
            reason_codes=[str(item) for item in quality_gate["reason_codes"]],
            verifier_schema_version=str(quality_gate["verifier_schema_version"]),
            verifier_schema_hash=str(quality_gate["verifier_schema_hash"]),
            verifier_prompt_hash=str(quality_gate["verifier_prompt_hash"]),
        ),
        provenance=ProvenanceResponse(
            rag_version=str(generation["pipeline_version"]),
            generator_model=str(generation["model"]),
            generator_revision=str(generation["model_revision"]),
            prompt_version=str(generation["prompt_version"]),
            prompt_schema_version=str(generation["schema_version"]),
            retrieval_config_hash=str(retrieval["retrieval_config_hash"]),
            context_config_hash=str(context["context_config_hash"]),
            rewrite_used=False,
        ),
        latency_ms=LatencyResponse(
            total=float(latency["total"]),
            retrieval=float(latency["retrieval"]),
            context=float(latency["context"]),
            llm=float(latency["llm"]),
        ),
    )


def error_payload(
    *, code: str, message: str, request_id: str, retryable: bool
) -> dict[str, Any]:
    """按统一错误 Schema 生成 JSON 兼容对象。"""

    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
        )
    ).model_dump(mode="json")
