"""文件说明：学习自测短期槽位；独立于知识库，不建立长期考试记录。"""
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT
from alembic import op

revision = "0011_learning_assessment"
down_revision = "0010_conversation_context"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("learning_assessment_slot",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("current_id", sa.String(36)),
        sa.Column("current_json", sa.Text().with_variant(LONGTEXT(), "mysql")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("task_id", sa.String(36)),
        sa.Column("task_state", sa.String(20)),
        sa.Column("task_created_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("pending_json", sa.Text().with_variant(LONGTEXT(), "mysql")),
        sa.Column("progress", sa.String(200)),
        sa.Column("error_message", sa.String(300)),
        sa.UniqueConstraint("task_id", name="uq_learning_assessment_task"))


def downgrade():
    op.drop_table("learning_assessment_slot")
