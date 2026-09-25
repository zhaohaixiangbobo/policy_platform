"""文件说明：本机Worker角色锁及协作式停止；锁随进程退出释放，停止只发生在阶段边界。"""

import os
import signal
import threading
from pathlib import Path

from app.config import PROJECT_ROOT


class WorkerControl:
    """统一单独/联合入口的角色互斥和停止信号，不跨主机协调。"""

    def __init__(self, role: str):
        self.role = role
        self.event = threading.Event()
        self.lock_file = None
        self.handlers = {}
        self.stop_file = os.getenv("PLATFORM_WORKER_STOP_FILE")

    def __enter__(self):
        root = Path(os.getenv("PLATFORM_WORKER_LOCK_DIR", str(PROJECT_ROOT / "var" / "worker-locks")))
        root.mkdir(parents=True, exist_ok=True)
        self.lock_file = (root / f"{self.role}.lock").open("a+b")
        self.lock_file.seek(0, 2)
        if self.lock_file.tell() == 0:
            self.lock_file.write(b"0")
            self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock_file.close()
            raise RuntimeError(f"{self.role} Worker已运行，请先停止旧进程") from exc
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.handlers[sig] = signal.signal(sig, lambda *_: self.event.set())
        print(f"event=worker_ready role={self.role} pid={os.getpid()}", flush=True)
        return self

    def is_set(self):
        return self.event.is_set() or bool(self.stop_file and Path(self.stop_file).exists())

    def wait(self, seconds: float):
        """空闲期间同时观察信号和停止文件。"""
        import time
        deadline = time.monotonic() + seconds
        while not self.is_set() and time.monotonic() < deadline:
            self.event.wait(min(0.2, max(0, deadline - time.monotonic())))

    def __exit__(self, *_):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)
        self.lock_file.close()
