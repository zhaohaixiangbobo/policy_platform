"""文件说明：增加发布请求与制度来源、知识运行版本的精确绑定表。

Revision ID: 0005_index_publication_job
Revises: 0004_query_scope_upload_status
"""

from collections.abc import Sequence

from alembic import op

from app.infrastructure.db.models import IndexPublicationSource

revision: str = "0005_index_publication_job"
down_revision: str | None = "0004_query_scope_upload_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立标准化发布任务绑定表，不猜测或回填历史绑定。"""

    IndexPublicationSource.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """删除发布任务绑定表。"""

    IndexPublicationSource.__table__.drop(bind=op.get_bind(), checkfirst=True)
