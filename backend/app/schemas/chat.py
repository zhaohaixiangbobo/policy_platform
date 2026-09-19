"""文件说明：定义平台会话、公开回答、Citation、Conflict和反馈API契约。"""

from datetime import datetime
from typing import Annotated, Literal

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


class ConfirmedConversationValue(BaseModel):
    """用户明确确认的值及对应消息来源。"""
    value: str
    source_message_id: str


class ConversationContextSnapshot(BaseModel):
    """仅保存用户问题和确认条件，不包含历史模型回答。"""
    root_question: str
    root_message_id: str
    confirmed: dict[str, ConfirmedConversationValue]


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    query_scope: Literal["CURRENT", "HISTORICAL"]
    document_selection_mode: Literal["ALL", "SELECTED"]
    selected_document_ids: list[int]
    resolved_document_scope_mode: Literal["ALL", "SELECTED"]
    query_index_run_id: int | None
    access_scope_version: str
    access_scope_hash: str
    access_scope_count: int
    content: str
    answer_status: Literal["ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICT"] | None
    answerability: Literal["SUFFICIENT", "PARTIAL", "NONE"] | None = None
    reason_code: str | None = None
    missing_fields: list[str] | None = None
    clarification_question: str | None = None
    rewrite_used: bool | None = None
    retrieval_query: str | None = None
    rewrite_strategy_version: str | None = None
    conversation_context: ConversationContextSnapshot | None = None
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


class AllDocumentSelection(BaseModel):
    """用户明确选择全部可访问制度。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["ALL"] = "ALL"


class SelectedDocumentSelection(BaseModel):
    """用户明确选择一至二十个具体制度版本。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["SELECTED"]
    document_ids: list[int] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def normalize_ids(self) -> "SelectedDocumentSelection":
        normalized = sorted(set(self.document_ids))
        if any(document_id <= 0 for document_id in normalized):
            raise ValueError("document_ids必须是正整数")
        self.document_ids = normalized
        return self


DocumentSelection = Annotated[
    AllDocumentSelection | SelectedDocumentSelection,
    Field(discriminator="mode"),
]


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    query_scope: Literal["CURRENT", "HISTORICAL"] = "CURRENT"
    document_selection: DocumentSelection = Field(default_factory=AllDocumentSelection)


class ChatTurnResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


class QueryScopeCapabilitiesResponse(BaseModel):
    active_index_run_id: int
    current_document_count: int
    historical_document_count: int


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
