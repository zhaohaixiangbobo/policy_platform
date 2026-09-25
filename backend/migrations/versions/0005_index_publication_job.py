"""文件说明：冻结历史数据库结构，后续变更由后续迁移负责，不引用当前ORM模型。"""

import sqlalchemy as sa
from alembic import op

revision = '0005_index_publication_job'
down_revision = '0004_query_scope_upload_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立本版本拥有的表、字段和约束。"""
    op.create_table('index_publication_source',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('publication_request_id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('parse_run_id', sa.Integer(), nullable=False),
    sa.Column('chunk_run_id', sa.Integer(), nullable=False),
    sa.Column('metadata_revision_id', sa.Integer(), nullable=False),
    sa.Column('index_run_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['ingestion_job.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['publication_request_id'], ['index_publication_request.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('publication_request_id', 'document_id', name='uq_index_publication_source_document')
    )
    op.create_index('ix_index_publication_source_job', 'index_publication_source', ['job_id'], unique=False)


def downgrade() -> None:
    """按依赖逆序回退本版本对象。"""
    op.drop_table('index_publication_source')
