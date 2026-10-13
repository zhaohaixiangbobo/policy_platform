"""文件说明：跨库交接的知识侧执行代次屏障；每个写事务校验并锁定当前操作代次。"""

from contextvars import ContextVar
from contextlib import contextmanager
import json
from sqlalchemy import text

CURRENT_EXECUTION = ContextVar("knowledge_worker_execution", default=None)


def check_execution():
    operation = CURRENT_EXECUTION.get()
    if operation:
        operation.check()


def fence_write(connection):
    operation = CURRENT_EXECUTION.get()
    if operation:
        operation.check()
        generation = connection.execute(text(
            "SELECT generation FROM worker_operation WHERE operation_key=:key FOR UPDATE"
        ), {"key": operation.key}).scalar_one_or_none()
        if generation != operation.generation:
            raise RuntimeError("知识操作代次已变化，拒绝过期执行者写入")


class KnowledgeExecution:
    def __init__(self, engine, key, generation, check):
        self.engine, self.key, self.generation, self.check = engine, key, generation, check

    def complete(self, result):
        with self.engine.begin() as connection:
            fence_write(connection)
            connection.execute(text("UPDATE worker_operation SET result_json=:result WHERE operation_key=:key AND generation=:generation"),
                               {"key": self.key, "generation": self.generation, "result": json.dumps(result, ensure_ascii=False)})


@contextmanager
def knowledge_execution(engine, key, generation, check):
    check()
    with engine.begin() as connection:
        accepted = connection.execute(text("""
            INSERT INTO worker_operation(operation_key,generation) VALUES (:key,:generation)
            ON CONFLICT (operation_key) DO UPDATE SET generation=EXCLUDED.generation, result_json=NULL
            WHERE worker_operation.generation < EXCLUDED.generation
            RETURNING generation
        """), {"key": key, "generation": generation}).scalar_one_or_none()
        if accepted != generation:
            raise RuntimeError("知识侧操作代次已经登记，当前执行身份不能复用")
    operation = KnowledgeExecution(engine, key, generation, check)
    token = CURRENT_EXECUTION.set(operation)
    try:
        yield operation
    finally:
        CURRENT_EXECUTION.reset(token)
