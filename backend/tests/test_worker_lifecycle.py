"""文件说明：验证进程入口、角色互斥和监督器停止行为，不领取真实业务任务。"""

import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import nullcontext
from uuid import uuid4

import pytest

from app.worker_control import WorkerControl

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_path():
    """沙箱测试产物集中到工程var/tests，避免系统临时目录权限差异。"""
    path = ROOT / "var/tests" / f"worker-lifecycle-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_entry_preserves_process():
    launcher = load("run-service")
    with patch.object(sys, "platform", "win32"), patch.object(sys, "argv", []), \
         patch.object(launcher.runpy, "run_path") as run_path, patch.object(launcher.os, "execv") as execv:
        launcher.execute(["worker.py", "--once"])
        run_path.assert_called_once_with("worker.py", run_name="__main__")
        assert sys.argv == ["worker.py", "--once"]
        execv.assert_not_called()
    with patch.object(sys, "platform", "win32"), patch.object(sys, "argv", []), \
         patch.object(launcher.runpy, "run_module") as run_module:
        launcher.execute(["-m", "alembic", "upgrade", "head"])
        run_module.assert_called_once_with("alembic", run_name="__main__", alter_sys=True)


def test_linux_entry_exec():
    launcher = load("run-service")
    with patch.object(sys, "platform", "linux"), patch.object(launcher.os, "execv") as execute:
        launcher.execute(["worker.py", "--once"])
        execute.assert_called_once_with(sys.executable, [sys.executable, "worker.py", "--once"])


def test_role_lock_release_and_cooperative_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_WORKER_LOCK_DIR", str(tmp_path))
    stop_file = tmp_path / "stop"
    monkeypatch.setenv("PLATFORM_WORKER_STOP_FILE", str(stop_file))
    with WorkerControl("test") as control:
        with pytest.raises(RuntimeError, match="Worker已运行"):
            with WorkerControl("test"):
                pass
        assert not control.is_set()
        stop_file.touch()
        assert control.is_set()
        control.wait(10)  # 已收到停止请求时立即返回。
    with WorkerControl("test"):
        pass


def test_feature_flag_selects_roles():
    supervisor = load("supervise-workers")
    assert supervisor.enabled_services(SimpleNamespace(learning_assessment_enabled=False)) == ["worker"]
    assert supervisor.enabled_services(SimpleNamespace(learning_assessment_enabled=True)) == ["worker", "learning-worker"]


def test_real_launcher_pid_and_stop(tmp_path):
    """用真实子进程确认入口没有改变PID，停止请求不会留下业务进程。"""
    stop_file = tmp_path / "stop"
    stop_file.touch()
    launcher = ROOT / "scripts/run-service.py"
    probe = Path(__file__).parent / "fixtures/worker_probe.py"
    code = (
        "import importlib.util; "
        f"s=importlib.util.spec_from_file_location('launcher', {str(launcher)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        f"m.execute([{str(probe)!r}])"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "PYTHONIOENCODING": "utf-8",
           "PLATFORM_WORKER_STOP_FILE": str(stop_file), "PLATFORM_WORKER_LOCK_DIR": str(tmp_path)}
    process = subprocess.Popen([sys.executable, "-c", code], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert f"probe_pid={process.pid}" in stdout
    finally:
        if process.poll() is None:
            process.kill()  # 仅测试用空进程的超时清理，生产监督器不强杀。
            process.wait(timeout=5)


@pytest.mark.parametrize("failure", [False, True])
def test_supervisor_drains_children(failure, tmp_path):
    supervisor = load("supervise-workers")
    children = []

    def spawn(*args, **kwargs):
        stop_file = Path(kwargs["env"]["PLATFORM_WORKER_STOP_FILE"])
        child = SimpleNamespace(pid=100 + len(children), returncode=None)

        def poll():
            if failure and child is children[0]:
                child.returncode = 2
            elif stop_file.exists():
                child.returncode = 0
            elif len(children) == 2 and not failure:
                # 模拟用户Ctrl+C；子进程直到收到停止文件才结束。
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            return child.returncode
        child.poll = poll
        children.append(child)
        return child

    with patch.object(supervisor.subprocess, "Popen", side_effect=spawn), \
         patch.object(supervisor.tempfile, "TemporaryDirectory", return_value=nullcontext(str(tmp_path))):
        assert supervisor.supervise(["worker", "learning-worker"]) == (1 if failure else 0)
    assert all(c.returncode is not None for c in children)


def test_worker_main_observes_stop_before_claim(tmp_path, monkeypatch):
    import worker
    import learning_worker
    monkeypatch.setenv("PLATFORM_WORKER_LOCK_DIR", str(tmp_path))
    stop = tmp_path / "stop"
    stop.touch()
    monkeypatch.setenv("PLATFORM_WORKER_STOP_FILE", str(stop))
    with patch.object(sys, "argv", ["worker.py"]), patch.object(worker, "configure_logging"), \
         patch.object(worker, "run_once") as run:
        assert worker.main() == 0
        run.assert_not_called()
    with patch.object(sys, "argv", ["learning_worker.py"]), \
         patch.object(learning_worker, "get_settings", return_value=SimpleNamespace(learning_assessment_enabled=True)), \
         patch.object(learning_worker, "configure_rotating_logger"), patch.object(learning_worker, "run_once") as run:
        assert learning_worker.main() == 0
        run.assert_not_called()
