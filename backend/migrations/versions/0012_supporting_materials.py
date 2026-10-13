"""文件说明：配套资料身份、版本快照及案例导入预览；历史迁移使用固定结构。"""
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT
from alembic import op

revision = "0012_supporting_materials"
down_revision = "0011_learning_assessment"
branch_labels = None
depends_on = None


def upgrade():
    longtext = sa.Text().with_variant(LONGTEXT(), "mysql")
    op.create_table("supporting_material",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("latest_revision_id", sa.String(36), nullable=False),
        sa.Column("published_revision_id", sa.String(36)),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("material_revision",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("supporting_material.id"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("domains", sa.String(500), nullable=False),
        sa.Column("keywords", sa.String(1000), nullable=False),
        sa.Column("source_unit", sa.String(200), nullable=False),
        sa.Column("source_category", sa.String(50), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("source_date", sa.String(10), nullable=False),
        sa.Column("search_text", longtext, nullable=False),
        sa.Column("payload_json", longtext, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("material_id", "revision_no", name="uq_material_revision_no"))
    op.create_table("material_import_batch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", longtext, nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("material_import_batch")
    op.drop_table("material_revision")
    op.drop_table("supporting_material")
