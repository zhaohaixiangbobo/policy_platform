"""文件说明：补齐旧最终模型中的制度系列查询索引；保留已执行基线的不可变性。"""

from alembic import op

revision = "k0002_document_series_index"
down_revision = "k0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("idx_policy_document_series", "policy_document", ["series_id", "document_version_no"])


def downgrade():
    op.drop_index("idx_policy_document_series", table_name="policy_document")
