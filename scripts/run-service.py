"""文件说明：跨平台API、Worker和显式迁移入口；容器运行时一进程一职责。"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["api", "worker", "migrate"])
    args, remaining = parser.parse_known_args()
    load_dotenv(ROOT / ".env", override=False)
    os.chdir(ROOT / "backend")
    # exec替换自身，容器PID 1直接接收停止信号；不自动安装依赖。
    if args.service == "api":
        command = ["-m", "uvicorn", "app.main:app", "--host", os.getenv("PLATFORM_HOST", "127.0.0.1"),
                   "--port", os.getenv("PLATFORM_PORT", "8020")]
    elif args.service == "worker":
        command = ["worker.py"]
    else:
        command = ["-m", "alembic", "-c", str(ROOT / "backend/alembic.ini"), "upgrade", "head"]
    os.execv(sys.executable, [sys.executable, *command, *remaining])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
