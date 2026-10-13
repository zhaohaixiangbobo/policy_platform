"""文件说明：创建独立platform.db连接、会话工厂和最小健康检查。"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """按配置创建Platform业务库引擎，不连接知识引擎控制库。"""

    settings = get_settings()
    engine = create_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True,
                         pool_size=5, max_overflow=2, pool_timeout=10, pool_recycle=1800,
                         connect_args={"connect_timeout": 5, "options": "-c timezone=UTC -c statement_timeout=60000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=60000"})
    from knowledge.storage.pool_metrics import register_pool
    register_pool(engine, "platform")
    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """返回不跨请求共享状态的同步会话工厂。"""

    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Iterator[Session]:
    """为单个API请求提供独立Platform数据库会话。"""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> bool:
    """执行最小SELECT验证Platform业务库是否可用。"""

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        # 健康接口只返回稳定状态，详细异常由后续结构化日志记录。
        return False
