"""文件说明：为三类后台任务增加持久化执行代次及租约，不改变业务状态枚举。"""

from alembic import op
import sqlalchemy as sa

revision = "0013_worker_leases"
down_revision = "0012_supporting_materials"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("ingestion_job", "learning_assessment_slot", "index_publication_request"):
        op.add_column(table, sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"))
        if table != "ingestion_job":
            op.add_column(table, sa.Column("lease_owner", sa.String(100)))
            op.add_column(table, sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
            op.add_column(table, sa.Column("heartbeat_at", sa.DateTime(timezone=True)))


def downgrade():
    raise RuntimeError("Worker租约迁移需保留执行身份，请按备份恢复方案处理版本回退")
