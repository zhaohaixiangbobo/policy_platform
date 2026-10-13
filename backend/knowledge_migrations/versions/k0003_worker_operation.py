"""文件说明：知识侧记录后台操作代次与完成结果，阻止过期执行者覆盖新结果。"""

from alembic import op
import sqlalchemy as sa

revision = "k0003_worker_operation"
down_revision = "k0002_document_series_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("worker_operation", sa.Column("operation_key", sa.Text(), primary_key=True),
                    sa.Column("generation", sa.Integer(), nullable=False), sa.Column("result_json", sa.Text()))


def downgrade():
    raise RuntimeError("操作执行身份须保留，请使用受控备份恢复方案")
