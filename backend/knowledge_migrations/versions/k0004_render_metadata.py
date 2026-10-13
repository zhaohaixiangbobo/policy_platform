"""文件说明：独立保存转换配置及字体环境，不修改历史 PDF 或回填旧记录。"""

from alembic import op
import sqlalchemy as sa

revision = "k0004_render_metadata"
down_revision = "k0003_worker_operation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("parse_run", sa.Column("render_metadata_json", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("转换追溯记录应保留，请使用受控恢复方案")
