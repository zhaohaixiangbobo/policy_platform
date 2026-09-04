"""文件说明：定义平台会话、公开回答、Citation、Conflict和反馈API契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class CitationSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    citation_version: str
    evidence_uid_version: str
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
    snapshot_hash: str


class ConflictPositionSnapshot(BaseModel):
    statement: str
    citations: list[str]


class ConflictSnapshot(BaseModel):
    topic: str
    positions: list[ConflictPositionSnapshot]


class QualityGateSummary(BaseModel):
    version: str
    status: str
    semantic_verification: str
    reason_codes: list[str]


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    query_scope: Literal["CURRENT", "HISTORICAL"]
    content: str
    answer_status: Literal["ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICT"] | None
    request_id: str
    engine_request_id: str | None
    contract_version: str | None
    index_run_id: int | None
    quality_gate: QualityGateSummary | None
    citations: list[CitationSnapshot]
    conflicts: list[ConflictSnapshot]
    created_at: datetime


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessageResponse]


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    query_scope: Literal["CURRENT", "HISTORICAL"] = "CURRENT"


class ChatTurnResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


FeedbackRating = Literal["up", "down"]
FeedbackReasonCode = Literal[
    "retrieval_miss",
    "citation_mismatch",
    "answer_wrong_with_valid_citation",
    "answer_incomplete",
    "inactive_document_used",
    "query_misunderstood",
    "conflict_mishandled",
    "other",
]


class MessageFeedbackCreate(BaseModel):
    rating: FeedbackRating
    reason_codes: list[FeedbackReasonCode] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=2000)
    mark_as_eval_case: bool = False

    @model_validator(mode="after")
    def validate_down_reasons(self) -> "MessageFeedbackCreate":
        if self.rating == "down" and not self.reason_codes:
            raise ValueError("点踩必须至少选择一个原因")
        return self


class MessageFeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: FeedbackRating
    reason_codes: list[str]
    comment: str | None
    mark_as_eval_case: bool
    eval_candidate_id: str | None
    created_at: datetime
