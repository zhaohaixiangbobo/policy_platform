"""文件说明：在空Platform业务库中交互式创建首个本地管理员，不在源码或日志保存密码。"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.application.auth_service import bootstrap_local_user  # noqa: E402
from app.infrastructure.db.session import get_session_factory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="创建制度知识平台首个本地管理员")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("初始密码（至少10个字符）: ")
    confirmation = getpass.getpass("再次输入初始密码: ")
    if password != confirmation:
        print("两次密码不一致", file=sys.stderr)
        return 2
    with get_session_factory()() as session:
        user = bootstrap_local_user(session, args.username.strip(), args.display_name.strip(), password, ["ADMIN"])
    print(f"已创建管理员：{user.username} ({user.id})；首次登录后必须修改初始密码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
