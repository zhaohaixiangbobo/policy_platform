"""文件说明：增加V2制度元数据治理、多文档批次和索引发布控制表。

Revision ID: 0003_v2_governance
Revises: 0002_policy_relation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.infrastructure.db.models import IndexPublicationRequest, IngestionBatch, MetadataChangeRequest

revision: str = "0003_v2_governance"
down_revision: str | None = "0002_policy_relation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立新控制表，并为既有入库任务补充批次和返工来源。"""

    bind = op.get_bind()
    IngestionBatch.__table__.create(bind=bind, checkfirst=True)
    MetadataChangeRequest.__table__.create(bind=bind, checkfirst=True)
    IndexPublicationRequest.__table__.create(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("ingestion_job")}
    if "batch_id" not in columns:
        op.add_column("ingestion_job", sa.Column("batch_id", sa.String(length=36), nullable=True))
    if "rework_of_job_id" not in columns:
        op.add_column("ingestion_job", sa.Column("rework_of_job_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    """仅回退V2新增对象，保留原有入库任务。"""

    with op.batch_alter_table("ingestion_job") as batch:
        batch.drop_column("rework_of_job_id")
        batch.drop_column("batch_id")
    IndexPublicationRequest.__table__.drop(bind=op.get_bind(), checkfirst=True)
    MetadataChangeRequest.__table__.drop(bind=op.get_bind(), checkfirst=True)
    IngestionBatch.__table__.drop(bind=op.get_bind(), checkfirst=True)
