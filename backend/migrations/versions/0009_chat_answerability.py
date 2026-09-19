"""文件说明：为公开回答增加可回答程度和澄清快照，历史记录保持NULL。"""

import sqlalchemy as sa
from alembic import op

revision = "0009_chat_answerability"
down_revision = "0008_metadata_change_open_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """只增加可空字段，保留旧回答原始语义。"""
    op.add_column("chat_message", sa.Column("answerability", sa.String(20), nullable=True))
    op.add_column("chat_message", sa.Column("reason_code", sa.String(80), nullable=True))
    op.add_column("chat_message", sa.Column("missing_fields_json", sa.Text(), nullable=True))
    op.add_column("chat_message", sa.Column("clarification_question", sa.Text(), nullable=True))


def downgrade() -> None:
    """降级会删除新字段，操作前应导出需要保留的回答快照。"""
    with op.batch_alter_table("chat_message") as batch:
        for name in ("clarification_question", "missing_fields_json", "reason_code", "answerability"):
            batch.drop_column(name)
