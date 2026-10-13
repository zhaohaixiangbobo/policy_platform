"""文件说明：PostgreSQL原子领取与执行租约；数据库时钟、代次条件及独立心跳短事务。"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
from threading import Event, Thread

from sqlalchemy import event, func, or_, select, update

LOGGER = logging.getLogger("policy_platform.worker")


class LeaseLostError(RuntimeError):
    """执行身份已失效；旧执行者只能放弃结果，不能登记成功或失败。"""


@dataclass(frozen=True)
class LeaseToken:
    model: object
    key_name: str
    key: str
    owner: str
    generation: int

    def conditions(self):
        model = self.model
        return (
            getattr(model, self.key_name) == self.key,
            model.lease_owner == self.owner,
            model.lease_generation == self.generation,
            model.lease_expires_at > func.clock_timestamp(),
        )


def lease_seconds():
    value = int(os.getenv("PLATFORM_WORKER_LEASE_SECONDS", "120"))
    if value < 30:
        raise ValueError("Worker租约至少30秒")
    return value


def claim(session, model, *, key_name, eligible, order_by, owner):
    """锁定一个候选并条件更新，提交后返回不可变令牌；有效租约从不抢占。"""
    available = or_(model.lease_expires_at.is_(None), model.lease_expires_at <= func.clock_timestamp())
    key_column = getattr(model, key_name)
    candidate = select(key_column).where(*eligible, available).order_by(order_by).limit(1).with_for_update(skip_locked=True).scalar_subquery()
    row = session.execute(update(model).where(key_column == candidate, available).values(
        lease_owner=owner, lease_generation=model.lease_generation + 1,
        heartbeat_at=func.clock_timestamp(),
        lease_expires_at=func.clock_timestamp() + timedelta(seconds=lease_seconds()),
    ).returning(key_column, model.lease_generation).execution_options(synchronize_session=False)).first()
    session.commit()
    return LeaseToken(model, key_name, row[0], owner, row[1]) if row else None


class LeaseExecution:
    """长耗时调用期间续租；写入前在同一事务内锁定租约，短事务提交后释放行锁。"""

    def __init__(self, factory, token):
        self.factory, self.token = factory, token
        self.stopped, self.lost = Event(), Event()
        self.thread = None

    def check(self, session=None):
        if self.lost.is_set():
            raise LeaseLostError("任务租约失效，当前执行结果不再提交")
        if session is None:
            with self.factory() as current:
                self.check(current)
            return
        with session.no_autoflush:
            valid = session.scalar(select(getattr(self.token.model, self.token.key_name)).where(
                *self.token.conditions()).with_for_update())
        if valid is None:
            self.lost.set()
            raise LeaseLostError("任务租约过期或已被其他代次接管")

    def _heartbeat(self):
        interval = min(30, lease_seconds() / 3)
        while not self.stopped.wait(interval):
            try:
                with self.factory() as session:
                    result = session.execute(update(self.token.model).where(*self.token.conditions()).values(
                        heartbeat_at=func.clock_timestamp(),
                        lease_expires_at=func.clock_timestamp() + timedelta(seconds=lease_seconds()),
                    ).execution_options(synchronize_session=False))
                    session.commit()
                    if result.rowcount != 1:
                        self.lost.set()
                        return
            except Exception:
                self.lost.set()
                LOGGER.warning("event=lease_heartbeat_failed task_id=%s generation=%s", self.token.key, self.token.generation)
                return

    @contextmanager
    def guard_session(self, session):
        def before_commit(current):
            self.check(current)
        event.listen(session, "before_commit", before_commit)
        try:
            yield
        finally:
            event.remove(session, "before_commit", before_commit)

    def __enter__(self):
        self.check()
        self.thread = Thread(target=self._heartbeat, name="worker-lease-heartbeat", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=10)
        # 只清除本代次租约；任务状态决定是否可领取，不在这里自动重试。
        try:
            with self.factory() as session:
                session.execute(update(self.token.model).where(*self.token.conditions()).values(
                    lease_owner=None, lease_expires_at=None,
                ).execution_options(synchronize_session=False))
                session.commit()
        except Exception:
            LOGGER.warning("event=lease_release_deferred task_id=%s generation=%s", self.token.key, self.token.generation)
