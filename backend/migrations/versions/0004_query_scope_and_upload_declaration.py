"""文件说明：持久化问答范围与制度上传声明状态。

Revision ID: 0004_query_scope_upload_status
Revises: 0003_v2_governance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_query_scope_upload_status"
down_revision: str | None = "0003_v2_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为历史记录补上安全默认值，并使新记录明确保存业务语义。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    chat_columns = {item["name"] for item in inspector.get_columns("chat_message")}
    if "query_scope" not in chat_columns:
        op.add_column(
            "chat_message",
            sa.Column("query_scope", sa.String(length=20), nullable=False, server_default="CURRENT"),
        )
    job_columns = {item["name"] for item in sa.inspect(bind).get_columns("ingestion_job")}
    if "initial_document_status" not in job_columns:
        op.add_column(
            "ingestion_job",
            sa.Column("initial_document_status", sa.String(length=20), nullable=False, server_default="effective"),
        )


def downgrade() -> None:
    """回退本次新增列。"""

    with op.batch_alter_table("ingestion_job") as batch:
        batch.drop_column("initial_document_status")
    with op.batch_alter_table("chat_message") as batch:
        batch.drop_column("query_scope")
