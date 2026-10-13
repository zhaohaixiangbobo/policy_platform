"""文件说明：单实例Worker的跨进程PG互斥；专用连接不持有事务、不进入业务连接池。"""

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import get_settings


WORKER_LOCKS = {"ingestion": 17003001, "learning": 17003002}


@contextmanager
def worker_mutex(role: str, *, database_url: str | None = None):
    """串行化同一数据库中的同类Worker；独立角色仍可同时运行。"""
    key = WORKER_LOCKS[role]
    url = database_url or get_settings().database_url
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("Worker互斥要求PostgreSQL连接")
    engine = create_engine(
        url, poolclass=NullPool, isolation_level="AUTOCOMMIT", hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar_one()
            if not acquired:
                raise RuntimeError(f"{role} Worker已在此数据库运行")
            try:
                yield
            finally:
                # NullPool关闭物理会话即释放锁；失联时不新建连接假装释放旧锁。
                connection.close()
    finally:
        engine.dispose()
