"""文件说明：生命周期测试用空Worker，只报告PID和响应停止文件，不连接业务资源。"""

import os
import time

from app.worker_control import WorkerControl


with WorkerControl("probe") as control:
    print(f"probe_pid={os.getpid()}", flush=True)
    while not control.is_set():
        time.sleep(0.02)
