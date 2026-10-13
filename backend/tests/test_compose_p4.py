"""文件说明：P4配置与迁移身份最小回归；仅临时目录/模拟连接，不连接业务库或模型。"""

import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import pytest
from dotenv import dotenv_values
from app.infrastructure.db.migration_guard import migration_plan

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_compose", ROOT / "scripts/prepare-compose.py")
prepare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_module)


def test_prepare_isolated_and_preserves_existing():
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "old.env"
        source.write_text("POLICY_EMBEDDING_URL=http://model/embedding\nPOLICY_RERANK_URL=http://model/rerank\n"
                          "POLICY_GENERATOR_URL=http://model/generator\nPLATFORM_DATABASE_URL=old-secret\n"
                          "POLICY_QDRANT_URL=http://old-qdrant\nPLATFORM_MATERIALS_ROOT=C:/old\n", encoding="utf-8")
        target = Path(tmp) / "new"
        result = prepare_module.prepare(source, target)
        app = dotenv_values(target / "runtime.env")
        owner = dotenv_values(target / "migration.env")
        assert "@postgres:5432/platform" in app["PLATFORM_DATABASE_URL"]
        assert app["POLICY_QDRANT_URL"] == "http://qdrant:6333"
        assert app["PLATFORM_MATERIALS_ROOT"] == "/data/materials"
        assert app["POLICY_INDEX_ALIAS"] == result["namespace"] + "_active"
        assert owner["PLATFORM_DATABASE_MARKER"] == result["identity"] + ":platform"
        assert not any("MIGRATION" in key or "owner" in str(value) for key, value in app.items())
        sql = (target / "init.sql").read_text(encoding="utf-8")
        assert "REVOKE ALL ON DATABASE knowledge FROM PUBLIC" in sql
        assert "DROP " not in sql
        original = (target / "runtime.env").read_bytes()
        with pytest.raises(ValueError, match="已存在"):
            prepare_module.prepare(source, target)
        assert (target / "runtime.env").read_bytes() == original


def test_env_roundtrip():
    from io import StringIO
    data = {"VALUE": "path\\name 'quoted' # spaces $literal"}
    assert dotenv_values(stream=StringIO(prepare_module.env_text(data))) == data


def connection(marker, username="platform_owner"):
    conn = Mock()
    conn.dialect.name = "postgresql"
    conn.execute.return_value.mappings.return_value.one.return_value = {
        "database": "platform", "username": username, "version": "170011", "marker": marker}
    conn.engine.url.host = "postgres"
    conn.engine.url.port = 5432
    return conn


def test_marker_requires_explicit_match_and_owner():
    marker = "policy-platform-compose-test:platform"
    with pytest.raises(ValueError, match="标识不匹配"):
        migration_plan(connection(marker), Mock())
    with pytest.raises(ValueError, match="标识不匹配"):
        migration_plan(connection(marker, "platform_app"), Mock(), expected_marker=marker)
    with pytest.raises(ValueError, match="标识不匹配"):
        migration_plan(connection("policy-platform-compose-other:platform"), Mock(), expected_marker=marker)


def test_explicit_marker_enters_plan_fingerprint():
    script = Mock()
    script.dir = str(ROOT / "backend/migrations")
    script.get_current_head.return_value = "head"
    script.iterate_revisions.return_value = []
    script.walk_revisions.return_value = []
    with patch("app.infrastructure.db.migration_guard.inspect") as inspector:
        inspector.return_value.get_table_names.return_value = []
        marker = "policy-platform-compose-test:platform"
        result = migration_plan(connection(marker), script, expected_marker=marker)
        assert result["marker"] == marker and result["current"] == []
        assert len(result["sha256"]) == 64


def test_compose_has_no_host_database_ports_or_old_volumes():
    content = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1:8088:8080" in content
    assert "55432" not in content and "6333:6333" not in content
    assert "policy-platform-pg17-dev-data" not in content
    assert "profiles: [tools]" in content
    assert "pull_policy: never" in content
    assert "/api/v1/health/ready" in content
    assert "PLATFORM_WORKER_LOCK_DIR: /logs/worker-locks" in content
    assert content.count("create_host_path: false") == 6
    assert "./deploy/portal" in content
    nginx = (ROOT / "deploy/nginx.conf").read_text(encoding="utf-8")
    assert "server api:8020 resolve;" in nginx
    assert "resolver 127.0.0.11" in nginx


def test_inspection_thresholds_without_live_faults():
    spec = importlib.util.spec_from_file_location("inspect_compose", ROOT / "scripts/inspect-compose.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    states = {name: {"status": "running", "restarts": 0} for name in module.SERVICES}
    assert module.alerts_for(states, 60, 10, 0, min_free=15, max_connections=80) == []
    alerts = module.alerts_for(states, 5, 95, 1, min_free=15, max_connections=80)
    assert len(alerts) == 3
    states["api"]["restarts"] = 1
    assert any("自动重启" in item for item in module.alerts_for(states, 60, 10, 0, min_free=15, max_connections=80))
