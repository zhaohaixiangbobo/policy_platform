"""文件说明：为每份制度建立唯一的未完成元数据变更槽位。

Revision ID: 0008_metadata_change_open_slot
Revises: 0007_chat_document_scope
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_metadata_change_open_slot"
down_revision: str | None = "0007_chat_document_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """存量未完成请求占用OPEN槽位，终态请求使用NULL并允许保留多条历史。"""

    with op.batch_alter_table("metadata_change_request") as batch:
        batch.add_column(sa.Column("open_slot", sa.String(length=20), nullable=True))
    op.execute(
        """
        UPDATE metadata_change_request
        SET open_slot='OPEN'
        WHERE status IN ('DRAFT', 'PENDING_REVIEW', 'APPROVED')
        """
    )
    with op.batch_alter_table("metadata_change_request") as batch:
        batch.create_unique_constraint(
            "uq_metadata_change_document_open_slot",
            ["document_id", "open_slot"],
        )


def downgrade() -> None:
    """移除元数据变更唯一槽位。"""

    with op.batch_alter_table("metadata_change_request") as batch:
        batch.drop_constraint("uq_metadata_change_document_open_slot", type_="unique")
        batch.drop_column("open_slot")
