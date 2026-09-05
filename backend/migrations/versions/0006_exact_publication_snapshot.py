"""文件说明：为全量索引发布增加精确快照契约、基线版本和来源角色。

Revision ID: 0006_exact_publication_snapshot
Revises: 0005_index_publication_job
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_exact_publication_snapshot"
down_revision: str | None = "0005_index_publication_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """历史请求保持 legacy；只有新请求使用 exact_snapshot_v2。"""

    with op.batch_alter_table("index_publication_request") as batch:
        batch.add_column(sa.Column(
            "snapshot_contract_version", sa.String(length=40),
            nullable=False, server_default="legacy",
        ))
        batch.add_column(sa.Column("base_index_run_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("index_publication_source") as batch:
        batch.add_column(sa.Column(
            "source_role", sa.String(length=20),
            nullable=False, server_default="CHANGE",
        ))


def downgrade() -> None:
    with op.batch_alter_table("index_publication_source") as batch:
        batch.drop_column("source_role")
    with op.batch_alter_table("index_publication_request") as batch:
        batch.drop_column("base_index_run_id")
        batch.drop_column("snapshot_contract_version")
