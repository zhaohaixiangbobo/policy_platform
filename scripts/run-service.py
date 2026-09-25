"""文件说明：跨平台API、Worker和显式迁移入口；容器运行时一进程一职责。"""

import argparse
import os
import runpy
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["api", "worker", "learning-worker", "workers", "migrate"])
    args, remaining = parser.parse_known_args()
    load_dotenv(ROOT / ".env", override=False)
    os.chdir(ROOT / "backend")
    sys.path.insert(0, str(ROOT / "backend"))
    # exec替换自身，容器PID 1直接接收停止信号；不自动安装依赖。
    if args.service == "api":
        command = ["-m", "uvicorn", "app.main:app", "--host", os.getenv("PLATFORM_HOST", "127.0.0.1"),
                   "--port", os.getenv("PLATFORM_PORT", "8020")]
    elif args.service == "worker":
        command = ["worker.py"]
    elif args.service == "learning-worker":
        command = ["learning_worker.py"]
    elif args.service == "workers":
        command = [str(ROOT / "scripts" / "supervise-workers.py")]
    else:
        command = ["-m", "alembic", "-c", str(ROOT / "backend/alembic.ini"), "upgrade", "head"]
    execute(command + remaining)
    return 0


def execute(command: list[str]) -> None:
    """Windows在当前进程运行入口，Linux容器使用exec保留PID及信号语义。"""
    if sys.platform != "win32":
        os.execv(sys.executable, [sys.executable, *command])
        return
    if command[0] == "-m":
        sys.argv = command[1:]
        runpy.run_module(command[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = command
        runpy.run_path(command[0], run_name="__main__")


if __name__ == "__main__":
    raise SystemExit(main())
