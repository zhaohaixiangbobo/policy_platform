"""文件说明：验证连接池采样来自原进程对象，不连接数据库或运行后台采样线程。"""

from unittest.mock import Mock, patch
from knowledge.storage import pool_metrics


def test_snapshot_has_no_connection_secrets():
    pool = Mock()
    pool.size.return_value = 5
    pool.checkedout.return_value = 2
    pool.checkedin.return_value = 1
    pool.overflow.return_value = -2
    with patch.dict(pool_metrics._pools, {"platform": pool}, clear=True):
        sample = pool_metrics.snapshot()
    assert sample["pools"] == {"platform": {"size": 5, "checked_out": 2, "checked_in": 1, "overflow": 0}}
    assert sample["sampled_at"] > 0


def test_cli_does_not_start_sampling(monkeypatch):
    monkeypatch.delenv("PLATFORM_POOL_METRICS_FILE", raising=False)
    with patch.object(pool_metrics.threading, "Thread") as thread:
        pool_metrics.register_pool(Mock(), "platform")
        thread.assert_not_called()
