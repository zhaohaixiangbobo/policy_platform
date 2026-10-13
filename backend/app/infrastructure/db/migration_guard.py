"""文件说明：迁移前核对PG身份、revision和待执行清单，生成脱敏审批指纹。"""

import hashlib
import json
from pathlib import Path
from sqlalchemy import inspect, text


def migration_plan(connection, script, database="platform", *, expected_marker=None):
    """仅查询；空版本表且已有业务表视为未知库，禁止自动stamp。"""
    if connection.dialect.name != "postgresql":
        raise ValueError("此迁移入口仅支持PostgreSQL")
    identity = dict(connection.execute(text("SELECT current_database() AS database, current_user AS username, current_setting('server_version_num') AS version, shobj_description(oid,'pg_database') AS marker FROM pg_database WHERE datname=current_database()" )).mappings().one())
    if int(identity["version"]) // 10000 != 17:
        raise ValueError("需要PostgreSQL17")
    if database not in {"platform", "knowledge"}:
        raise ValueError("未知迁移模块")
    # 显式部署标识来自迁移专用配置；旧开发入口保持原默认身份，不从目标库反推期望值。
    marker = expected_marker or f"policy-platform-pg17-dev:{database}"
    if not marker.startswith("policy-platform-") or not marker.endswith(f":{database}"):
        raise ValueError("迁移环境标识格式不正确")
    if identity["database"] != database or identity["username"] != f"{database}_owner" or identity["marker"] != marker:
        raise ValueError("目标库/账号/环境标识不匹配，拒绝执行迁移")
    tables = inspect(connection).get_table_names(schema="public")
    current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) if "alembic_version" in tables else []
    if len(current) > 1 or (not current and set(tables) - {"alembic_version"}):
        raise ValueError("未知结构或多head，禁止自动初始化")
    head = script.get_current_head()
    pending = [r.revision for r in reversed(list(script.iterate_revisions(head, current[0] if current else "base")))]
    plan = {**identity, "host": connection.engine.url.host, "port": connection.engine.url.port,
            "current": current, "head": head, "pending": pending,
            "migration_hashes": {r.revision: hashlib.sha256(Path(r.path).read_bytes()).hexdigest() for r in script.walk_revisions()}}
    # 基线冻结模型也是迁移代码，必须参与审批指纹。
    baseline = Path(script.dir) / "baseline_v1.py"
    if baseline.is_file():
        plan["migration_hashes"]["baseline_v1"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
    plan["sha256"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan
