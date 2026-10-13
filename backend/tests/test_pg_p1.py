"""文件说明：P0隔离配置与P1真实PG最小验收；测试用户写入由外层事务回滚。"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.infrastructure.db.base import Base
from app.infrastructure.db.models import LocalCredential
from app.application.auth_service import bootstrap_local_user
from knowledge.indexing.config import IndexConfig
from knowledge.rag.runtime import RagRuntimeSettings
from knowledge.indexing.indexer import PolicyIndexer
from unittest.mock import Mock
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.infrastructure.db.migration_guard import migration_plan

ROOT = Path(__file__).resolve().parents[2]


def test_namespace_complete_and_consistent():
    with patch.dict(os.environ, {"POLICY_INDEX_PROFILE": "pg_test", "POLICY_INDEX_ALIAS": "pg_test_active", "POLICY_COLLECTION_PREFIX": "pg_test"}):
        config = IndexConfig.from_environment()
        assert config.profile_name == RagRuntimeSettings.from_environment().profile_name
        assert config.collection_name("a"*64, "b"*64).startswith("pg_test_")


def test_partial_namespace_rejected():
    with patch.dict(os.environ, {"POLICY_INDEX_PROFILE": "pg_test", "POLICY_INDEX_ALIAS": "", "POLICY_COLLECTION_PREFIX": ""}):
        with pytest.raises(ValueError):
            IndexConfig.from_environment()


def test_foreign_run_activation_rejected_before_qdrant():
    indexer = object.__new__(PolicyIndexer)
    indexer.config = IndexConfig(profile_name="pg_test", alias_name="pg_test_active", collection_prefix="pg_test")
    indexer.db = Mock()
    indexer.db.get_run.return_value = {"alias_name": "policy_platform_dense_active"}
    indexer.db.repository.run.return_value.mappings.return_value.fetchone.return_value = {"profile_name": "policy_platform_dense", "alias_name": "policy_platform_dense_active"}
    indexer.vector_store = Mock()
    with pytest.raises(ValueError, match="命名空间"):
        indexer._activate(1, 1)
    assert not indexer.vector_store.mock_calls


def test_migration_guard_rejects_app_account(engine):
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    with engine.connect() as connection, pytest.raises(ValueError, match="身份不匹配|标识不匹配"):
        migration_plan(connection, ScriptDirectory.from_config(config))


@pytest.fixture
def engine():
    values = dotenv_values(ROOT / "var/postgres-dev/platform.env")
    if not values.get("PLATFORM_DATABASE_URL"):
        pytest.skip("需显式建立隔离P1数据库")
    engine = create_engine(values["PLATFORM_DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database(),current_user")).one() == ("platform", "platform_app")
        assert connection.execute(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()" )).scalar() == "policy-platform-pg17-dev:platform"
    yield engine
    engine.dispose()


def test_schema_matches_models(engine):
    with engine.connect() as connection:
        config = Config(str(ROOT / "backend/alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/migrations"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == ScriptDirectory.from_config(config).get_current_head()
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert not connection.execute(text("SELECT has_table_privilege(current_user,'public.alembic_version',:privilege)"), {"privilege": privilege}).scalar()
        assert connection.execute(text("SELECT has_table_privilege(current_user,'public.alembic_version','SELECT')")).scalar()
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert not differences, differences
        assert not connection.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE')")).scalar()


def test_bootstrap_duplicate_keeps_password_and_rollback(engine):
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            session = Session(bind=connection, join_transaction_mode="create_savepoint")
            user = bootstrap_local_user(session, "p1_test_only", "迁移测试", "Temporary-test-only-928!", ["ADMIN"])
            original = session.scalar(select(LocalCredential).where(LocalCredential.user_id == user.id)).password_hash
            with pytest.raises(ValueError, match="已经存在"):
                bootstrap_local_user(session, "p1_test_only", "替换", "Different-test-only-731!", ["ADMIN"])
            assert session.scalar(select(LocalCredential).where(LocalCredential.user_id == user.id)).password_hash == original
            session.close()
        finally:
            outer.rollback()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM user_account WHERE username='p1_test_only'")).scalar() == 0


def test_knowledge_baseline_ready():
    values = dotenv_values(ROOT / "var/postgres-dev/platform.env")
    if not values.get("KNOWLEDGE_DATABASE_URL"):
        pytest.skip("需隔离PG")
    engine = create_engine(values["KNOWLEDGE_DATABASE_URL"])
    try:
        from knowledge.storage.schema import metadata
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend/knowledge_alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "backend/knowledge_migrations"))
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == ScriptDirectory.from_config(config).get_current_head()
            assert not compare_metadata(MigrationContext.configure(connection), metadata)
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not connection.execute(text("SELECT has_table_privilege(current_user,'public.alembic_version',:privilege)"), {"privilege": privilege}).scalar()
    finally:
        engine.dispose()
