"""文件说明：Knowledge独立PG迁移入口，身份/计划校验和版本表最小权限。"""

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from app.infrastructure.db.migration_guard import migration_plan
from knowledge.storage.schema import metadata

config = context.config
url = config.attributes.get("migration_url")
if not url:
    raise ValueError("使用scripts/migrate-knowledge-pg.py先预览再执行")
engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
with engine.connect() as connection:
    if not connection.execute(text("SELECT pg_try_advisory_lock(17002001)")).scalar():
        raise ValueError("Knowledge迁移正在执行")
    plan = migration_plan(connection, ScriptDirectory.from_config(config), "knowledge", expected_marker=config.attributes.get("expected_marker"))
    if plan["sha256"] != config.attributes.get("expected_plan"):
        raise ValueError("Knowledge迁移指纹不一致，请重新预览")
    connection.commit()
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
        connection.execute(text("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.alembic_version FROM knowledge_app"))
engine.dispose()
