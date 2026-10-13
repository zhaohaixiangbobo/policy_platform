"""文件说明：Core仓储事务边界；只接受SQLAlchemy语句，查询完成立即归还连接。"""

import os
from functools import lru_cache
from dataclasses import dataclass
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import Executable
from sqlalchemy.sql.elements import TextClause
from .execution import fence_write


@lru_cache(maxsize=4)
def engine_for(url: str):
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("Knowledge必须配置postgresql+psycopg数据库URL")
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True, pool_size=3, max_overflow=1,
                         pool_timeout=10, pool_recycle=1800,
                         connect_args={"connect_timeout": 5, "options": "-c timezone=UTC -c statement_timeout=60000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=60000"})
    from .pool_metrics import register_pool
    register_pool(engine, "knowledge")
    return engine


def database_url():
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("请显式配置KNOWLEDGE_DATABASE_URL并执行Knowledge迁移")
    return url


@dataclass(frozen=True)
class WriteOutcome:
    rowcount: int


class CoreRepository:
    """查询返回已物化的Core结果；写事务由业务阶段显式save/discard。"""

    def __init__(self, url=None):
        self.engine = engine_for(url or database_url())
        self._write_connection = None

    def run(self, statement: Executable, parameters=None):
        if not isinstance(statement, Executable):
            raise TypeError("仓储仅接受SQLAlchemy Core语句及命名参数")
        if parameters == []:
            return WriteOutcome(0)
        read = statement.is_select or (isinstance(statement, TextClause) and statement.text.lstrip().upper().startswith("SELECT"))
        if read and self._write_connection is None:
            with self.engine.connect() as connection:
                return connection.execute(statement, parameters or {}).freeze()()
        if self._write_connection is None:
            self._write_connection = self.engine.connect()
        try:
            if not read:
                fence_write(self._write_connection)
            result = self._write_connection.execute(statement, parameters or {})
            return result.freeze()() if result.returns_rows else WriteOutcome(result.rowcount)
        except Exception:
            # 连接/约束错误保留原分类，立即释放失败事务；业务方按唯一键决定重试。
            self.discard()
            raise

    @contextmanager
    def read_snapshot(self):
        """多次关联读取共享短快照，离开后释放连接；其中不得调用外部模型。"""
        if self._write_connection is not None:
            raise RuntimeError("快照读取必须独立于写事务")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                self._write_connection = connection
                try:
                    yield self
                finally:
                    self._write_connection = None

    def save(self):
        if self._write_connection is not None:
            try:
                self._write_connection.commit()
            finally:
                self._write_connection.close()
                self._write_connection = None

    def discard(self):
        if self._write_connection is not None:
            try:
                self._write_connection.rollback()
            finally:
                self._write_connection.close()
                self._write_connection = None

    def close(self):
        self.discard()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
