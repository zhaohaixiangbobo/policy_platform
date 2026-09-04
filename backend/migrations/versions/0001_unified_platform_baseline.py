"""文件说明：创建第二期清空重建后的Platform完整核心业务基线。

Revision ID: 0001_platform_core_baseline
Revises: None
"""

from collections.abc import Sequence

from alembic import op

from app.infrastructure.db.base import Base
from app.infrastructure.db import models as _models  # noqa: F401

revision: str = "0001_platform_core_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """按SQLAlchemy元数据建立跨SQLite/MySQL一致的空业务库。"""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """仅供全新开发库回退，按外键依赖逆序删除全部基线表。"""

    Base.metadata.drop_all(bind=op.get_bind())
