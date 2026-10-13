"""文件说明：将统一配置和SQLAlchemy元数据接入Alembic迁移运行时。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from alembic.script import ScriptDirectory
from app.infrastructure.db.migration_guard import migration_plan

from app.config import get_settings
from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401  # 注册全部Platform ORM表

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", (config.attributes.get("migration_url") or get_settings().database_url).replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在不创建数据库连接时生成迁移SQL。"""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接Platform业务库并应用迁移。"""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # session级锁覆盖再次检查及DDL；关闭连接必定释放，避免并行迁移。
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(17001001)")).scalar()
            if not acquired:
                raise ValueError("已有迁移正在执行")
            plan = migration_plan(connection, ScriptDirectory.from_config(config), expected_marker=config.attributes.get("expected_marker"))
            if plan["sha256"] != config.attributes.get("expected_plan"):
                raise ValueError("PG迁移需通过scripts/migrate-platform-pg.py预览并确认指纹")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
            if connection.dialect.name == "postgresql":
                # 版本表属于迁移控制面，运行账号只读取版本；每次迁移均固化权限。
                connection.execute(text("REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.alembic_version FROM platform_app"))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
