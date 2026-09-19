"""文件说明：保存确定性多轮补全的检索问题、策略和用户确认来源；旧记录保持NULL。"""

import sqlalchemy as sa
from alembic import op

revision = "0010_conversation_context"
down_revision = "0009_chat_answerability"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_message", sa.Column("retrieval_query", sa.Text(), nullable=True))
    op.add_column("chat_message", sa.Column("rewrite_strategy_version", sa.String(80), nullable=True))
    op.add_column("chat_message", sa.Column("conversation_context_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("chat_message") as batch:
        for name in ("conversation_context_json", "rewrite_strategy_version", "retrieval_query"):
            batch.drop_column(name)
