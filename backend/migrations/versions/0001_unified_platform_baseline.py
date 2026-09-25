"""文件说明：冻结历史数据库结构，后续变更由后续迁移负责，不引用当前ORM模型。"""

import sqlalchemy as sa
from alembic import op

revision = '0001_platform_core_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立本版本拥有的表、字段和约束。"""
    op.create_table('auth_provider',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('provider_key', sa.String(length=50), nullable=False),
    sa.Column('provider_type', sa.String(length=30), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_key')
    )
    op.create_table('platform_audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('request_id', sa.String(length=128), nullable=False),
    sa.Column('actor_user_id', sa.String(length=36), nullable=True),
    sa.Column('auth_provider', sa.String(length=50), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('object_type', sa.String(length=80), nullable=False),
    sa.Column('object_id', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('detail_json', sa.Text(), nullable=False),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_platform_audit_actor_created', 'platform_audit_log', ['actor_user_id', 'created_at'], unique=False)
    op.create_index('ix_platform_audit_request', 'platform_audit_log', ['request_id'], unique=False)
    op.create_table('review_issue',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.String(length=100), nullable=False),
    sa.Column('issue_type', sa.String(length=80), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('disposition', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('location_json', sa.Text(), nullable=False),
    sa.Column('handled_by', sa.String(length=36), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('role',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('permissions_json', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('system_config',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value_json', sa.Text(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('user_account',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('auth_session',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('provider_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=80), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['auth_provider.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_auth_session_user_expires', 'auth_session', ['user_id', 'expires_at'], unique=False)
    op.create_table('chat_session',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('evidence_reference',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_type', sa.String(length=40), nullable=False),
    sa.Column('owner_id', sa.String(length=100), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('parse_run_id', sa.Integer(), nullable=False),
    sa.Column('primary_node_id', sa.Integer(), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('quote_snapshot', sa.Text(), nullable=False),
    sa.Column('snapshot_hash', sa.String(length=64), nullable=False),
    sa.Column('validation_status', sa.String(length=30), nullable=False),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_evidence_owner', 'evidence_reference', ['owner_type', 'owner_id'], unique=False)
    op.create_table('identity_link',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('provider_id', sa.String(length=36), nullable=False),
    sa.Column('external_subject', sa.String(length=300), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['auth_provider.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_id', 'external_subject', name='uq_identity_provider_subject')
    )
    op.create_table('local_credential',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('password_hash', sa.String(length=500), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('policy_process',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('current_revision_id', sa.String(length=36), nullable=True),
    sa.Column('published_revision_id', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('review_record',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.String(length=100), nullable=False),
    sa.Column('outcome', sa.String(length=30), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('warning_acceptance', sa.Text(), nullable=True),
    sa.Column('reviewer_user_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_review_target', 'review_record', ['target_type', 'target_id', 'created_at'], unique=False)
    op.create_table('user_role',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('granted_by', sa.String(length=36), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    op.create_table('chat_message',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('answer_status', sa.String(length=40), nullable=True),
    sa.Column('request_id', sa.String(length=128), nullable=False),
    sa.Column('engine_request_id', sa.String(length=128), nullable=True),
    sa.Column('contract_version', sa.String(length=80), nullable=True),
    sa.Column('rag_version', sa.String(length=100), nullable=True),
    sa.Column('generator_model', sa.String(length=300), nullable=True),
    sa.Column('generator_revision', sa.String(length=200), nullable=True),
    sa.Column('prompt_version', sa.String(length=100), nullable=True),
    sa.Column('prompt_schema_version', sa.String(length=100), nullable=True),
    sa.Column('retrieval_config_hash', sa.String(length=200), nullable=True),
    sa.Column('context_config_hash', sa.String(length=200), nullable=True),
    sa.Column('index_run_id', sa.Integer(), nullable=True),
    sa.Column('rewrite_used', sa.Boolean(), nullable=True),
    sa.Column('quality_gate_version', sa.String(length=100), nullable=True),
    sa.Column('quality_gate_status', sa.String(length=40), nullable=True),
    sa.Column('quality_gate_semantic_verification', sa.String(length=80), nullable=True),
    sa.Column('quality_gate_reason_codes', sa.Text(), nullable=True),
    sa.Column('latency_total_ms', sa.Float(), nullable=True),
    sa.Column('warnings_snapshot', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chat_message_request', 'chat_message', ['request_id'], unique=False)
    op.create_index('ix_chat_message_session_created', 'chat_message', ['session_id', 'created_at'], unique=False)
    op.create_table('ingestion_job',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_name', sa.String(length=300), nullable=False),
    sa.Column('original_filename', sa.String(length=500), nullable=False),
    sa.Column('stored_path', sa.String(length=1000), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.Column('state_version', sa.Integer(), nullable=False),
    sa.Column('stage_progress', sa.Integer(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('retryable', sa.Boolean(), nullable=False),
    sa.Column('failed_stage', sa.String(length=40), nullable=True),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('parse_run_id', sa.Integer(), nullable=True),
    sa.Column('chunk_run_id', sa.Integer(), nullable=True),
    sa.Column('index_run_id', sa.Integer(), nullable=True),
    sa.Column('lease_owner', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ingestion_job_sha', 'ingestion_job', ['file_sha256'], unique=False)
    op.create_index('ix_ingestion_job_state_created', 'ingestion_job', ['state', 'created_at'], unique=False)
    op.create_table('process_revision',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('process_id', sa.String(length=36), nullable=False),
    sa.Column('revision_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('graph_json', sa.Text(), nullable=False),
    sa.Column('change_summary', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('reviewed_by', sa.String(length=36), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', sa.String(length=36), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['process_id'], ['policy_process.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('process_id', 'revision_no', name='uq_process_revision_no')
    )
    op.create_table('ingestion_artifact',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('artifact_type', sa.String(length=50), nullable=False),
    sa.Column('relative_path', sa.String(length=1000), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['ingestion_job.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ingestion_job_event',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('from_state', sa.String(length=40), nullable=True),
    sa.Column('to_state', sa.String(length=40), nullable=False),
    sa.Column('actor_user_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('run_type', sa.String(length=30), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['ingestion_job.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('message_citation',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('message_id', sa.String(length=36), nullable=False),
    sa.Column('citation_version', sa.String(length=80), nullable=False),
    sa.Column('evidence_uid_version', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=30), nullable=False),
    sa.Column('evidence_uid', sa.String(length=200), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('primary_node_id', sa.Integer(), nullable=True),
    sa.Column('parse_run_id', sa.Integer(), nullable=False),
    sa.Column('chunk_run_id', sa.Integer(), nullable=False),
    sa.Column('index_run_id', sa.Integer(), nullable=False),
    sa.Column('chunk_id', sa.Integer(), nullable=False),
    sa.Column('document_title', sa.String(length=500), nullable=False),
    sa.Column('document_code', sa.String(length=200), nullable=True),
    sa.Column('document_status', sa.String(length=80), nullable=False),
    sa.Column('source_reference', sa.String(length=1000), nullable=False),
    sa.Column('path_text', sa.String(length=1000), nullable=True),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('snapshot_hash', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['chat_message.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id', 'label', name='uq_message_citation_label')
    )
    op.create_index('ix_message_citation_document', 'message_citation', ['document_id', 'primary_node_id'], unique=False)
    op.create_table('message_conflict',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('message_id', sa.String(length=36), nullable=False),
    sa.Column('topic', sa.Text(), nullable=False),
    sa.Column('order_no', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['chat_message.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('message_feedback',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('message_id', sa.String(length=36), nullable=False),
    sa.Column('rating', sa.String(length=10), nullable=False),
    sa.Column('primary_reason_code', sa.String(length=80), nullable=True),
    sa.Column('reason_codes', sa.Text(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('mark_as_eval_case', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['chat_message.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id')
    )
    op.create_table('conflict_position',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('conflict_id', sa.Integer(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('citation_labels', sa.Text(), nullable=False),
    sa.Column('order_no', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['conflict_id'], ['message_conflict.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('eval_candidate',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('feedback_id', sa.String(length=36), nullable=False),
    sa.Column('request_id', sa.String(length=128), nullable=False),
    sa.Column('question_snapshot', sa.Text(), nullable=False),
    sa.Column('answer_snapshot', sa.Text(), nullable=False),
    sa.Column('citation_snapshot', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('manual_correction', sa.Text(), nullable=True),
    sa.Column('expected_document_id', sa.Integer(), nullable=True),
    sa.Column('expected_node_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['feedback_id'], ['message_feedback.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('feedback_id')
    )


def downgrade() -> None:
    """按依赖逆序回退本版本对象。"""
    op.drop_table('eval_candidate')
    op.drop_table('conflict_position')
    op.drop_table('message_feedback')
    op.drop_table('message_conflict')
    op.drop_table('message_citation')
    op.drop_table('ingestion_job_event')
    op.drop_table('ingestion_artifact')
    op.drop_table('process_revision')
    op.drop_table('ingestion_job')
    op.drop_table('chat_message')
    op.drop_table('user_role')
    op.drop_table('review_record')
    op.drop_table('policy_process')
    op.drop_table('local_credential')
    op.drop_table('identity_link')
    op.drop_table('evidence_reference')
    op.drop_table('chat_session')
    op.drop_table('auth_session')
    op.drop_table('user_account')
    op.drop_table('system_config')
    op.drop_table('role')
    op.drop_table('review_issue')
    op.drop_table('platform_audit_log')
    op.drop_table('auth_provider')
