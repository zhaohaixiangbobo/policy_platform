"""文件说明：验证跨平台入口的命令与环境优先级，测试不启动真实服务。"""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch


def test_portable_launcher_commands():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("portable_launcher", root / "scripts/run-service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [("api", ["-m", "uvicorn", "app.main:app"]),
             ("worker", ["worker.py"]), ("migrate", ["-m", "alembic"])]
    for service, prefix in cases:
        with patch.object(module.sys, "argv", ["run-service.py", service]), \
             patch.object(module.os, "chdir") as chdir, \
             patch.object(module.os, "execv") as execute, \
             patch.dict(os.environ, {"PLATFORM_HOST": "0.0.0.0", "PLATFORM_PORT": "9020"}):
            module.main()
            chdir.assert_called_once_with(root / "backend")
            command = execute.call_args.args[1]
            assert command[1:1 + len(prefix)] == prefix
            if service == "api":
                assert "0.0.0.0" in command and "9020" in command
