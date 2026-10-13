"""文件说明：Knowledge独立迁移预览/执行入口，不访问旧SQLite。"""

import argparse
import json
import sys
from pathlib import Path
from dotenv import dotenv_values
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.infrastructure.db.migration_guard import migration_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--execute-plan")
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    url = values.get("KNOWLEDGE_MIGRATION_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("必须显式指定Knowledge PostgreSQL迁移连接")
    config = Config(str(ROOT / "backend/knowledge_alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/knowledge_migrations"))
    config.attributes.update(migration_url=url, expected_plan=args.execute_plan)
    config.attributes["expected_marker"] = values.get("KNOWLEDGE_DATABASE_MARKER")
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            plan = migration_plan(connection, ScriptDirectory.from_config(config), "knowledge", expected_marker=config.attributes["expected_marker"])
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.execute_plan:
            if args.execute_plan != plan["sha256"]:
                raise ValueError("计划已变化，请重新预览")
            command.upgrade(config, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
