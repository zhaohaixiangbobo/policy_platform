"""文件说明：冻结历史数据库结构，后续变更由后续迁移负责，不引用当前ORM模型。"""

import sqlalchemy as sa
from alembic import op

revision = '0002_policy_relation'
down_revision = '0001_platform_core_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立本版本拥有的表、字段和约束。"""
    op.create_table('policy_relation',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('relation_type', sa.String(length=40), nullable=False),
    sa.Column('source_document_id', sa.Integer(), nullable=False),
    sa.Column('source_parse_run_id', sa.Integer(), nullable=False),
    sa.Column('target_document_id', sa.Integer(), nullable=False),
    sa.Column('target_parse_run_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('reviewed_by', sa.String(length=36), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_policy_relation_documents', 'policy_relation', ['source_document_id', 'target_document_id'], unique=False)
    op.create_index('ix_policy_relation_status', 'policy_relation', ['status', 'updated_at'], unique=False)


def downgrade() -> None:
    """按依赖逆序回退本版本对象。"""
    op.drop_table('policy_relation')
