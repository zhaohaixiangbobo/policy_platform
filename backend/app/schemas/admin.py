"""文件说明：定义任务中心、审核工作台和流程管理的公开接口契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestionJobResponse(BaseModel):
    id: str
    task_name: str
    original_filename: str
    initial_document_status: Literal["effective", "repealed", "expired"]
    state: str
    state_version: int
    stage_progress: int
    attempt_no: int
    retryable: bool
    failed_stage: str | None
    error_code: str | None
    document_id: int | None
    parse_run_id: int | None
    chunk_run_id: int | None
    index_run_id: int | None
    batch_id: str | None
    rework_of_job_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: list[IngestionJobResponse]
    total: int
    page: int
    page_size: Literal[10]
    counts: dict[str, int]


class JobRetryRequest(BaseModel):
    expected_state_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class JobPublishRequest(BaseModel):
    expected_state_version: int = Field(ge=1)


class BatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)


class MetadataDraftCreateRequest(BaseModel):
    request_type: Literal["CORRECTION", "REPEAL", "EXPIRY"]
    change_reason: str | None = Field(default=None, max_length=2000)


class MetadataRevisionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    document_code: str | None = Field(default=None, max_length=200)
    document_type: str | None = Field(default=None, max_length=100)
    issuing_org: str | None = Field(default=None, max_length=300)
    addressee_text: str | None = Field(default=None, max_length=1000)
    authority_level: str | None = Field(default=None, max_length=100)
    publish_date: str | None = Field(default=None, max_length=30)
    effective_date: str | None = Field(default=None, max_length=30)
    expiry_date: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=100)
    owner_department: str | None = Field(default=None, max_length=300)
    confidentiality_level: str | None = Field(default=None, max_length=100)
    change_reason: str | None = Field(default=None, max_length=2000)
    repeal_date: str | None = Field(default=None, max_length=30)
    repeal_reason: str | None = Field(default=None, max_length=2000)
    repeal_evidence: str | None = Field(default=None, max_length=5000)
    status_confirmation_note: str | None = Field(default=None, max_length=2000)


class MetadataReviewRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=2000)


class PolicySeriesAssignRequest(BaseModel):
    series_id: int | None = Field(default=None, ge=1)
    canonical_title: str | None = Field(default=None, max_length=500)


class ParseNodeCorrectionRequest(BaseModel):
    source_parse_run_id: int = Field(ge=1)
    source_node_id: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=1000)
    node_number: str | None = Field(default=None, max_length=200)
    node_type: str | None = Field(default=None, max_length=80)
    parent_id: int | None = Field(default=None, ge=1)
    order_no: int | None = Field(default=None, ge=0)


class IndexPublicationCreateRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=20)


class ReviewDecisionRequest(BaseModel):
    outcome: Literal["PASS", "PASS_WITH_WARNING", "REJECT"]
    comment: str | None = Field(default=None, max_length=2000)
    warning_acceptance: str | None = Field(default=None, max_length=2000)


class ReviewItemDecisionRequest(BaseModel):
    target_type: Literal["issue", "field", "node", "chunk_issue", "chunk"]
    target_id: int = Field(ge=1)
    action: Literal["confirm", "ignore", "reject", "correct"]
    comment: str | None = Field(default=None, max_length=2000)
    corrected_value: str | None = Field(default=None, max_length=5000)


class ReviewBatchDecisionRequest(BaseModel):
    target_type: Literal["node", "issue", "chunk_issue"]
    target_ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "ignore"]
    comment: str | None = Field(default=None, max_length=2000)


class ReviewArticleTitleDecisionRequest(BaseModel):
    node_id: int = Field(ge=1)
    mode: Literal["TITLE", "CONTENT"]
    title: str | None = Field(default=None, max_length=1000)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewQueueItem(BaseModel):
    target_type: Literal["PARSE_RUN", "CHUNK_RUN"]
    target_id: str
    job_id: str
    document_id: int | None
    title: str
    document_code: str | None
    state: str
    issue_count: int
    review_status: str
    processing_status: Literal["PENDING", "PROCESSED"]
    review_outcome: str | None
    display_state: Literal["ACTION_REQUIRED", "READY_TO_SUBMIT", "PASS", "PASS_WITH_WARNING", "REJECT", "FAILED"]
    created_at: datetime
    updated_at: datetime


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    page: int
    page_size: Literal[10]
    counts: dict[str, int]


class ReviewDetail(BaseModel):
    target_type: Literal["PARSE_RUN", "CHUNK_RUN"]
    run: dict[str, Any]
    metrics: dict[str, Any]
    nodes: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    pdf_available: bool


class IndexStatusResponse(BaseModel):
    profile: dict[str, Any] | None
    runs: list[dict[str, Any]]


class ProcessCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProcessGraphUpdateRequest(BaseModel):
    graph: dict[str, Any]
    change_summary: str | None = Field(default=None, max_length=1000)


class ProcessSummary(BaseModel):
    id: str
    name: str
    description: str | None
    revision_id: str
    revision_no: int
    status: str
    graph: dict[str, Any]
    updated_at: datetime


class EvidenceBindRequest(BaseModel):
    owner_kind: Literal["NODE", "EDGE", "RELATION"]
    cell_id: str = Field(min_length=1, max_length=120)
    document_id: int = Field(ge=1)
    parse_run_id: int = Field(ge=1)
    primary_node_id: int = Field(ge=1)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    quote_snapshot: str = Field(min_length=1, max_length=20000)


class EvidenceReferenceResponse(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    document_id: int
    parse_run_id: int
    primary_node_id: int
    page_start: int | None
    page_end: int | None
    quote_snapshot: str
    snapshot_hash: str
    validation_status: str
    validated_at: datetime | None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RelationCreateRequest(BaseModel):
    relation_type: Literal["CITES", "SUPERSEDES", "REPEALS", "RELATED_TOPIC", "CONFLICTS_WITH"]
    source_document_id: int = Field(ge=1)
    source_parse_run_id: int = Field(ge=1)
    target_document_id: int = Field(ge=1)
    target_parse_run_id: int = Field(ge=1)
    rationale: str | None = Field(default=None, max_length=2000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class RelationSummary(BaseModel):
    id: str
    relation_type: str
    source_document_id: int
    source_parse_run_id: int
    target_document_id: int
    target_parse_run_id: int
    status: str
    rationale: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    created_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RelationReviewRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=2000)


class ProcessReviewerRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
