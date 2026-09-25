"""文件说明：监督已启用的独立Worker；中断或子进程失败时请求阶段完成后退出，不强杀业务。"""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings


def enabled_services(settings):
    return ["worker", "learning-worker"] if settings.learning_assessment_enabled else ["worker"]


def supervise(services):
    stop = threading.Event()
    handlers = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    processes = []
    result = 0
    try:
        with tempfile.TemporaryDirectory(prefix="policy-workers-") as directory:
            stop_file = Path(directory) / "stop"
            env = {**os.environ, "PLATFORM_WORKER_STOP_FILE": str(stop_file)}
            try:
                for service in services:
                    if stop.is_set():
                        break
                    # Windows独立进程组避免Ctrl+C打断子进程启动，通过文件请求阶段完成后退出。
                    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
                    process = subprocess.Popen([sys.executable, str(ROOT / "scripts/run-service.py"), service],
                        cwd=ROOT / "backend", env=env, **options)
                    processes.append((service, process))
                    print(f"event=worker_spawned role={service} pid={process.pid} 等待worker_ready", flush=True)
                print("按Ctrl+C停止领取新任务并等待当前阶段完成。日志：logs/worker.log、logs/learning.log", flush=True)
                while not stop.wait(0.2):
                    exited = [(name, p.returncode) for name, p in processes if p.poll() is not None]
                    if exited:
                        print(f"event=worker_exited detail={exited}", flush=True)
                        result = 1 if any(code != 0 for _, code in exited) else 0
                        break
            finally:
                stop_file.touch()
                started = time.monotonic()
                next_report = 0.0
                while any(p.poll() is None for _, p in processes):
                    elapsed = time.monotonic() - started
                    if elapsed >= next_report:
                        pending = [f"{name}:{p.pid}" for name, p in processes if p.poll() is None]
                        print(f"event=workers_stopping elapsed_seconds={elapsed:.0f} pending={pending} 等待当前阶段完成，请保留终端", flush=True)
                        next_report = elapsed + 10
                    time.sleep(0.2)
                if any(p.returncode != 0 for _, p in processes):
                    result = 1
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return result


if __name__ == "__main__":
    raise SystemExit(supervise(enabled_services(get_settings())))
