"""文件说明：定义第二期Platform业务库的身份、会话、入库、审核、流程和问答审计模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_text() -> str:
    return str(uuid4())


class UserAccount(Base):
    """平台内部稳定用户；认证来源变化时业务主键保持不变。"""
    __tablename__ = "user_account"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class LocalCredential(Base):
    """本地认证凭据；后续接入4A时可停用而不影响用户业务数据。"""
    __tablename__ = "local_credential"
    user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AuthProvider(Base):
    """认证提供者配置；LOCAL和未来4A共享统一身份映射入口。"""
    __tablename__ = "auth_provider"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IdentityLink(Base):
    """外部不可变主体与内部稳定用户的映射。"""
    __tablename__ = "identity_link"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    provider_id: Mapped[str] = mapped_column(ForeignKey("auth_provider.id", ondelete="RESTRICT"), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(300), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("provider_id", "external_subject", name="uq_identity_provider_subject"),)


class Role(Base):
    """粗粒度角色；接口授权仍使用明确权限码。"""
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class UserRole(Base):
    """用户与角色的多对多关联。"""
    __tablename__ = "user_role"
    user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), primary_key=True)
    granted_by: Mapped[str | None] = mapped_column(String(36))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AuthSession(Base):
    """服务端会话；浏览器仅持有不可读的随机令牌Cookie。"""
    __tablename__ = "auth_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[str] = mapped_column(ForeignKey("auth_provider.id", ondelete="RESTRICT"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (Index("ix_auth_session_user_expires", "user_id", "expires_at"),)


class SystemConfig(Base):
    """受审计的平台配置，例如固定流程审核管理员。"""
    __tablename__ = "system_config"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ChatSession(Base):
    """平台自有聊天会话。"""
    __tablename__ = "chat_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """用户问题或rag_api_v1_1公开回答快照。"""
    __tablename__ = "chat_message"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    query_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="CURRENT")
    document_selection_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    selected_document_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    resolved_document_scope_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    query_index_run_id: Mapped[int | None] = mapped_column(Integer)
    access_scope_version: Mapped[str] = mapped_column(String(100), nullable=False, default="document_access_open_v1")
    access_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    access_scope_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_status: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_request_id: Mapped[str | None] = mapped_column(String(128))
    contract_version: Mapped[str | None] = mapped_column(String(80))
    rag_version: Mapped[str | None] = mapped_column(String(100))
    generator_model: Mapped[str | None] = mapped_column(String(300))
    generator_revision: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(100))
    retrieval_config_hash: Mapped[str | None] = mapped_column(String(200))
    context_config_hash: Mapped[str | None] = mapped_column(String(200))
    index_run_id: Mapped[int | None] = mapped_column(Integer)
    rewrite_used: Mapped[bool | None] = mapped_column(Boolean)
    retrieval_query: Mapped[str | None] = mapped_column(Text)
    rewrite_strategy_version: Mapped[str | None] = mapped_column(String(80))
    conversation_context_json: Mapped[str | None] = mapped_column(Text)
    quality_gate_version: Mapped[str | None] = mapped_column(String(100))
    answerability: Mapped[str | None] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    missing_fields_json: Mapped[str | None] = mapped_column(Text)
    clarification_question: Mapped[str | None] = mapped_column(Text)
    quality_gate_status: Mapped[str | None] = mapped_column(String(40))
    quality_gate_semantic_verification: Mapped[str | None] = mapped_column(String(80))
    quality_gate_reason_codes: Mapped[str | None] = mapped_column(Text)
    latency_total_ms: Mapped[float | None] = mapped_column(Float)
    warnings_snapshot: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    session: Mapped[ChatSession] = relationship(back_populates="messages")
    citations: Mapped[list["MessageCitation"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    conflicts: Mapped[list["MessageConflict"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    feedback: Mapped["MessageFeedback | None"] = relationship(back_populates="message", cascade="all, delete-orphan", uselist=False)
    __table_args__ = (Index("ix_chat_message_session_created", "session_id", "created_at"), Index("ix_chat_message_request", "request_id"))


class MessageCitation(Base):
    """公开、版本化Citation的历史证据快照。"""
    __tablename__ = "message_citation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False)
    citation_version: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_uid_version: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_uid: Mapped[str] = mapped_column(String(200), nullable=False)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_node_id: Mapped[int | None] = mapped_column(Integer)
    parse_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    index_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    document_title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_code: Mapped[str | None] = mapped_column(String(200))
    document_status: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    path_text: Mapped[str | None] = mapped_column(String(1000))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[ChatMessage] = relationship(back_populates="citations")
    __table_args__ = (UniqueConstraint("message_id", "label", name="uq_message_citation_label"), Index("ix_message_citation_document", "document_id", "primary_node_id"))


class MessageConflict(Base):
    """公开CONFLICT主题快照。"""
    __tablename__ = "message_conflict"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[ChatMessage] = relationship(back_populates="conflicts")
    positions: Mapped[list["ConflictPosition"]] = relationship(back_populates="conflict", cascade="all, delete-orphan")


class ConflictPosition(Base):
    """CONFLICT中的单个立场和公开引用编号。"""
    __tablename__ = "conflict_position"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conflict_id: Mapped[int] = mapped_column(ForeignKey("message_conflict.id", ondelete="CASCADE"), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    citation_labels: Mapped[str] = mapped_column(Text, nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict: Mapped[MessageConflict] = relationship(back_populates="positions")


class MessageFeedback(Base):
    """用户对助手消息的结构化反馈。"""
    __tablename__ = "message_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    message_id: Mapped[str] = mapped_column(ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False, unique=True)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    primary_reason_code: Mapped[str | None] = mapped_column(String(80))
    reason_codes: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    mark_as_eval_case: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    message: Mapped[ChatMessage] = relationship(back_populates="feedback")
    eval_candidate: Mapped["EvalCandidate | None"] = relationship(back_populates="feedback", cascade="all, delete-orphan", uselist=False)


class EvalCandidate(Base):
    """等待管理员审核的候选评测案例。"""
    __tablename__ = "eval_candidate"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    feedback_id: Mapped[str] = mapped_column(ForeignKey("message_feedback.id", ondelete="CASCADE"), nullable=False, unique=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    question_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    answer_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    citation_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CANDIDATE")
    manual_correction: Mapped[str | None] = mapped_column(Text)
    expected_document_id: Mapped[int | None] = mapped_column(Integer)
    expected_node_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    feedback: Mapped[MessageFeedback] = relationship(back_populates="eval_candidate")


class IngestionBatch(Base):
    """多文档入库批次；批次只负责组织，每个文件仍保持独立状态和审核结果。"""
    __tablename__ = "ingestion_batch"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(Base):
    """制度入库编排状态；知识运行数据仍由知识库保存。"""
    __tablename__ = "ingestion_job"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    task_name: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 上传声明值只表达提交人对初始制度状态的声明，不代表解析识别或审核结论。
    initial_document_status: Mapped[str] = mapped_column(String(20), nullable=False, default="effective")
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="UPLOADED")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stage_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_stage: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(Integer)
    parse_run_id: Mapped[int | None] = mapped_column(Integer)
    chunk_run_id: Mapped[int | None] = mapped_column(Integer)
    index_run_id: Mapped[int | None] = mapped_column(Integer)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_batch.id", ondelete="SET NULL"))
    rework_of_job_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_job.id", ondelete="SET NULL"))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (Index("ix_ingestion_job_state_created", "state", "created_at"), Index("ix_ingestion_job_sha", "file_sha256"))


class MetadataChangeRequest(Base):
    """Platform侧元数据确认、修订和废止审核任务。"""
    __tablename__ = "metadata_change_request"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_revision_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_job.id", ondelete="SET NULL"))
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    # OPEN槽位让同一制度在草稿、待审核、待发布阶段最多存在一条变更链；终态写NULL。
    open_slot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (
        Index("ix_metadata_change_status", "status", "updated_at"),
        UniqueConstraint("document_id", "open_slot", name="uq_metadata_change_document_open_slot"),
    )


class IndexPublicationRequest(Base):
    """一次全局索引快照的构建与Alias正式发布控制记录。"""
    __tablename__ = "index_publication_request"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    # 新发布请求必须冻结完整基线与本次变更；旧请求保留 legacy 标记且不可重试。
    snapshot_contract_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="legacy"
    )
    base_index_run_id: Mapped[int | None] = mapped_column(Integer)
    source_document_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    index_run_id: Mapped[int | None] = mapped_column(Integer)
    alias_name: Mapped[str] = mapped_column(String(200), nullable=False, default="policy_platform_dense_active")
    requested_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(36))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_index_publication_status", "status", "updated_at"),)


class IndexPublicationSource(Base):
    """冻结发布请求采用的制度、知识运行版本和可选入库任务。"""

    __tablename__ = "index_publication_source"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    publication_request_id: Mapped[str] = mapped_column(
        ForeignKey("index_publication_request.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_job.id", ondelete="RESTRICT")
    )
    source_role: Mapped[str] = mapped_column(String(20), nullable=False, default="CHANGE")
    document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_revision_id: Mapped[int] = mapped_column(Integer, nullable=False)
    index_run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint(
            "publication_request_id", "document_id", name="uq_index_publication_source_document"
        ),
        Index("ix_index_publication_source_job", "job_id"),
    )


class IngestionJobEvent(Base):
    """不可变的任务状态转换记录。"""
    __tablename__ = "ingestion_job_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_job.id", ondelete="CASCADE"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(Text)
    run_type: Mapped[str | None] = mapped_column(String(30))
    run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IngestionArtifact(Base):
    """任务产生的受控文件清单。"""
    __tablename__ = "ingestion_artifact"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_job.id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ReviewRecord(Base):
    """ParseRun、ChunkRun、关系和流程共用的标准审核记录。"""
    __tablename__ = "review_record"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    warning_acceptance: Mapped[str | None] = mapped_column(Text)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (Index("ix_review_target", "target_type", "target_id", "created_at"),)


class ReviewIssue(Base):
    """标准化审核问题及其处置状态。"""
    __tablename__ = "review_issue"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    disposition: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    handled_by: Mapped[str | None] = mapped_column(String(36))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceReference(Base):
    """关系或流程绑定的版本化制度证据快照，不建立跨库外键。"""
    __tablename__ = "evidence_reference"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    quote_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNAVAILABLE")
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (Index("ix_evidence_owner", "owner_type", "owner_id"),)


class PolicyRelation(Base):
    """人工维护的制度关系；正式确认前始终保留为可审计草稿。"""
    __tablename__ = "policy_relation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_parse_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_parse_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    rationale: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (
        Index("ix_policy_relation_status", "status", "updated_at"),
        Index("ix_policy_relation_documents", "source_document_id", "target_document_id"),
    )


class PolicyProcess(Base):
    """流程稳定身份，具体内容保存在不可覆盖的修订版本中。"""
    __tablename__ = "policy_process"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    published_revision_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ProcessRevision(Base):
    """流程修订及草稿、审核、发布生命周期。"""
    __tablename__ = "process_revision"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    process_id: Mapped[str] = mapped_column(ForeignKey("policy_process.id", ondelete="CASCADE"), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    graph_json: Mapped[str] = mapped_column(Text, nullable=False, default='{"nodes":[],"edges":[]}')
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(36))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("process_id", "revision_no", name="uq_process_revision_no"),)


class PlatformAuditLog(Base):
    """平台业务审计，不保存Prompt、推理草稿或服务器绝对路径。"""
    __tablename__ = "platform_audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36))
    auth_provider: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (Index("ix_platform_audit_request", "request_id"), Index("ix_platform_audit_actor_created", "actor_user_id", "created_at"))
