"""文件说明：同一索引profile的构建/激活互斥；锁连接独立且不持有长数据库事务。"""

from functools import wraps
from hashlib import sha256

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def serialized_operation(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        key = int.from_bytes(sha256(self.config.profile_name.encode()).digest()[:8], "big", signed=True)
        engine = create_engine(self.db.repository.engine.url, poolclass=NullPool,
                               isolation_level="AUTOCOMMIT", hide_parameters=True,
                               connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as connection:
                if not connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one():
                    raise RuntimeError("此索引profile正在构建、发布或恢复")
                pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                def check():
                    if connection.invalidated or connection.closed:
                        raise RuntimeError("索引互斥连接丢失，需人工核查发布状态")
                    if connection.execute(text("SELECT pg_backend_pid()")).scalar_one() != pid:
                        raise RuntimeError("索引互斥会话发生变化，停止发布")
                self._check_operation_lock = check
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._check_operation_lock = None
        finally:
            engine.dispose()
    return wrapped
