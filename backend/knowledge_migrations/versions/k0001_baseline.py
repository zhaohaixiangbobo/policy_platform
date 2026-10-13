"""文件说明：Knowledge PostgreSQL空库基线，保留最终字段、约束和证据契约。"""

from alembic import op
from knowledge_migrations.baseline_v1 import metadata

revision = "k0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    raise RuntimeError("Knowledge业务结构回退需独立审核，不自动删表")
