"""文件说明：定义仅基于平台公开响应快照的受控诊断契约。"""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.chat import ChatMessageResponse


class DiagnosticRequestSummary(BaseModel):
    request_id: str
    question_summary: str
    answer_status: str
    quality_gate_version: str | None
    quality_gate_status: str | None
    citation_count: int
    index_run_id: int | None
    latency_total_ms: float | None
    has_down_feedback: bool
    created_at: datetime


class DiagnosticListResponse(BaseModel):
    items: list[DiagnosticRequestSummary]
    total: int
    page: int
    page_size: int


class DiagnosticRequestDetail(BaseModel):
    question: ChatMessageResponse
    answer: ChatMessageResponse
    rag_version: str | None
    generator_model: str | None
    generator_revision: str | None
    prompt_version: str | None
    prompt_schema_version: str | None
    retrieval_config_hash: str | None
    context_config_hash: str | None
    latency_total_ms: float | None
    diagnostic_scope: str = "public_response_snapshot_only"
