"""文件说明：独立初始化本地PG角色/配置及可选管理员，重复执行不会覆盖密码。"""

import argparse
import getpass
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.application.auth_service import ensure_auth_baseline, bootstrap_local_user
from app.infrastructure.db.models import UserAccount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    args = parser.parse_args()
    url = dotenv_values(args.env_file).get("PLATFORM_DATABASE_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise ValueError("必须显式使用PG应用账号")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            identity = session.execute(text("SELECT current_database(),current_user,current_setting('server_version_num')")).one()
            if tuple(identity[:2]) != ("platform", "platform_app") or int(identity[2]) // 10000 != 17:
                raise ValueError("初始化目标身份不匹配")
            config = Config(str(ROOT / "backend/alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "backend/migrations"))
            if session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != ScriptDirectory.from_config(config).get_current_head():
                raise ValueError("先执行已审核迁移")
            if args.username:
                if session.scalar(select(UserAccount).where(UserAccount.username == args.username)):
                    print("账号已存在，保持原密码和权限不变")
                    return
                if not args.display_name:
                    raise ValueError("创建管理员必须提供display-name")
                password = getpass.getpass("初始密码（至少10字符）: ")
                if password != getpass.getpass("再次输入: "):
                    raise ValueError("两次密码不一致")
                bootstrap_local_user(session, args.username, args.display_name, password, ["ADMIN"])
                print("管理员已创建，首次登录须修改密码")
            else:
                ensure_auth_baseline(session)
                print("基础角色与认证配置已初始化；未创建管理员")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
