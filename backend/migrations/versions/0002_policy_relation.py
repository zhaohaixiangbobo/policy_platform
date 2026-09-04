"""文件说明：增加第二期制度关系实体，证据继续复用统一EvidenceReference表。

Revision ID: 0002_policy_relation
Revises: 0001_platform_core_baseline
"""

from collections.abc import Sequence

from alembic import op

from app.infrastructure.db.models import PolicyRelation

revision: str = "0002_policy_relation"
down_revision: str | None = "0001_platform_core_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    PolicyRelation.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    PolicyRelation.__table__.drop(bind=op.get_bind(), checkfirst=True)
