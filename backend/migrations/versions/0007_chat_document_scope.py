"""文件说明：为每轮问答保存显式制度选择与授权范围快照。

Revision ID: 0007_chat_document_scope
Revises: 0006_exact_publication_snapshot
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_chat_document_scope"
down_revision: str | None = "0006_exact_publication_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """旧消息明确迁移为全部制度范围，不通过NULL推断业务语义。"""

    with op.batch_alter_table("chat_message") as batch:
        batch.add_column(sa.Column(
            "document_selection_mode", sa.String(length=20),
            nullable=False, server_default="ALL",
        ))
        batch.add_column(sa.Column(
            "selected_document_ids_json", sa.Text(),
            nullable=False, server_default="[]",
        ))
        batch.add_column(sa.Column(
            "resolved_document_scope_mode", sa.String(length=20),
            nullable=False, server_default="ALL",
        ))
        batch.add_column(sa.Column("query_index_run_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column(
            "access_scope_version", sa.String(length=100),
            nullable=False, server_default="document_access_open_v1",
        ))
        batch.add_column(sa.Column(
            "access_scope_hash", sa.String(length=64),
            nullable=False, server_default="",
        ))
        batch.add_column(sa.Column(
            "access_scope_count", sa.Integer(),
            nullable=False, server_default="0",
        ))


def downgrade() -> None:
    """移除问答制度范围快照字段。"""

    with op.batch_alter_table("chat_message") as batch:
        batch.drop_column("access_scope_count")
        batch.drop_column("access_scope_hash")
        batch.drop_column("access_scope_version")
        batch.drop_column("query_index_run_id")
        batch.drop_column("resolved_document_scope_mode")
        batch.drop_column("selected_document_ids_json")
        batch.drop_column("document_selection_mode")
