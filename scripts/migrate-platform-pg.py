"""文件说明：Platform PG17迁移默认只预览，执行必须提供当前预览指纹；不操作SQLite。"""

import argparse
import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.infrastructure.db.migration_guard import migration_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--execute-plan", help="必须精确匹配本次预览sha256")
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    url = values.get("PLATFORM_MIGRATION_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise ValueError("缺少明确的PostgreSQL迁移URL")
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    config.attributes["migration_url"] = url
    config.attributes["expected_plan"] = args.execute_plan
    config.attributes["expected_marker"] = values.get("PLATFORM_DATABASE_MARKER")
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            plan = migration_plan(connection, ScriptDirectory.from_config(config), expected_marker=config.attributes["expected_marker"])
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.execute_plan:
            if args.execute_plan != plan["sha256"]:
                raise ValueError("计划已变化，请重新预览")
            command.upgrade(config, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
