"""文件说明：进程内连接池只读采样到日志卷，不连接数据库、不输出凭据。"""

import json
import logging
import os
from pathlib import Path
import threading
import time

_pools = {}
_lock = threading.Lock()
_started = False


def snapshot():
    with _lock:
        pools = dict(_pools)
    return {"pid": os.getpid(), "sampled_at": time.time(), "pools": {
        name: {"size": pool.size(), "checked_out": pool.checkedout(),
               "checked_in": pool.checkedin(), "overflow": max(0, pool.overflow())}
        for name, pool in pools.items()}}


def register_pool(engine, name):
    """只在明确配置采样路径的服务进程启动；诊断 CLI 默认不开线程。"""
    global _started
    filename = os.environ.get("PLATFORM_POOL_METRICS_FILE")
    if not filename:
        return
    with _lock:
        _pools[name] = engine.pool
        if _started:
            return
        _started = True

    def sample():
        target = Path(filename)
        while True:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(f".{os.getpid()}.tmp")
                temporary.write_text(json.dumps(snapshot()), encoding="utf-8")
                temporary.replace(target)
            except OSError:
                logging.getLogger(__name__).warning("event=db_pool_metrics_write_failed")
            time.sleep(15)
    threading.Thread(target=sample, name="db-pool-metrics", daemon=True).start()
