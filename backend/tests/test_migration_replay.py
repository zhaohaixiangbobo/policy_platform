"""文件说明：仅用隔离临时库验证历史迁移重放、版本边界及最终模型结构。"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_path():
    """隔离库集中放在工程测试产物目录，保留供失败排查。"""
    path = BACKEND.parent / "var/tests" / f"migration-replay-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def migrate(path, command, target):
    result = subprocess.run([sys.executable, "-m", "alembic", command, target], cwd=BACKEND,
        env={**os.environ, "PLATFORM_DATABASE_URL": f"sqlite:///{path.as_posix()}"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_empty_and_incremental_replay(tmp_path):
    path = tmp_path / "platform.db"
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        migrate(path, "upgrade", "0001_platform_core_baseline")
        assert "query_scope" not in columns(engine, "chat_message")
        assert "learning_assessment_slot" not in sa.inspect(engine).get_table_names()
        assert "index_publication_request" not in sa.inspect(engine).get_table_names()
        migrate(path, "upgrade", "0005_index_publication_job")
        assert "snapshot_contract_version" not in columns(engine, "index_publication_request")
        assert "source_role" not in columns(engine, "index_publication_source")
        migrate(path, "upgrade", "0010_conversation_context")
        assert "learning_assessment_slot" not in sa.inspect(engine).get_table_names()
        migrate(path, "upgrade", "head")
        migrate(path, "upgrade", "head")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("select version_num from alembic_version")) == "0011_learning_assessment"
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        # 回退只删除所属表，外部表仍保留；重新建库也应成功。
        with engine.begin() as connection:
            connection.execute(sa.text("create table unrelated_test (id integer)"))
        migrate(path, "downgrade", "base")
        assert set(sa.inspect(engine).get_table_names()) == {"alembic_version", "unrelated_test"}
        migrate(path, "upgrade", "head")
    finally:
        engine.dispose()


def test_historical_scripts_are_independent():
    for script in (BACKEND / "migrations/versions").glob("*.py"):
        source = script.read_text(encoding="utf-8-sig")
        assert "app.infrastructure.db" not in source
        assert "create_all" not in source and "drop_all" not in source
        assert "\ufffd" not in source
