"""文件说明：冻结历史数据库结构，后续变更由后续迁移负责，不引用当前ORM模型。"""

import sqlalchemy as sa
from alembic import op

revision = '0003_v2_governance'
down_revision = '0002_policy_relation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立本版本拥有的表、字段和约束。"""
    op.create_table('ingestion_batch',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metadata_change_request',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('metadata_revision_id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=True),
    sa.Column('request_type', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('reviewed_by', sa.String(length=36), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['job_id'], ['ingestion_job.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('metadata_revision_id')
    )
    op.create_index('ix_metadata_change_status', 'metadata_change_request', ['status', 'updated_at'], unique=False)
    op.create_table('index_publication_request',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('source_document_ids_json', sa.Text(), nullable=False),
    sa.Column('index_run_id', sa.Integer(), nullable=True),
    sa.Column('alias_name', sa.String(length=200), nullable=False),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('published_by', sa.String(length=36), nullable=True),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['requested_by'], ['user_account.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_index_publication_status', 'index_publication_request', ['status', 'updated_at'], unique=False)

    with op.batch_alter_table("ingestion_job") as batch:
        batch.add_column(sa.Column("batch_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("rework_of_job_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_ingestion_job_batch", "ingestion_batch", ["batch_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_ingestion_job_rework", "ingestion_job", ["rework_of_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """按依赖逆序回退本版本对象。"""
    with op.batch_alter_table("ingestion_job") as batch:
        batch.drop_constraint("fk_ingestion_job_rework", type_="foreignkey")
        batch.drop_constraint("fk_ingestion_job_batch", type_="foreignkey")
        batch.drop_column("rework_of_job_id")
        batch.drop_column("batch_id")
    op.drop_table('index_publication_request')
    op.drop_table('metadata_change_request')
    op.drop_table('ingestion_batch')
