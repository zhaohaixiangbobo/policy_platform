"""文件说明：按请求关联知识问答阶段耗时，不记录问题、Prompt、证据或模型草稿。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
import time

LOGGER = logging.getLogger("policy_platform.api.query_timing")
_trace = ContextVar("knowledge_query_timing", default=None)


def event(stage: str, **fields) -> None:
    """调用方只传阶段名、计数、耗时及受控错误码。"""
    trace = _trace.get()
    if trace is not None:
        value = {"stage": stage, **fields}
        trace["events"].append(value)
        LOGGER.info("event=query_stage request_id=%s data=%s", trace["request_id"], json.dumps(value, ensure_ascii=False))


@contextmanager
def query_trace(request_id: str, queued_at: float):
    """在线程入口创建独立追踪，成功和失败都落盘汇总。"""
    started = time.perf_counter()
    value = {"version": "query_timing_v1", "request_id": request_id, "events": []}
    token = _trace.set(value)
    event("queue", elapsed_ms=round((started - queued_at) * 1000, 3))
    try:
        yield
    except Exception as exc:
        value["error_type"] = type(exc).__name__
        raise
    finally:
        value["service_elapsed_ms"] = round((time.perf_counter() - queued_at) * 1000, 3)
        LOGGER.info("event=query_timing_summary data=%s", json.dumps(value, ensure_ascii=False))
        _trace.reset(token)


def call(stage: str, function, *args, **kwargs):
    """记录一次调用（含网络等待），HTTP失败状态码也会保留。"""
    if _trace.get() is None:
        return function(*args, **kwargs)
    started = time.perf_counter()
    LOGGER.info("event=query_stage_started request_id=%s stage=%s", _trace.get()["request_id"], stage)
    fields = {}
    try:
        result = function(*args, **kwargs)
        if hasattr(result, "status_code"):
            fields["status_code"] = result.status_code
        return result
    except Exception as exc:
        fields["error_type"] = type(exc).__name__
        # 只记录异常链类型，避免异常正文泄露服务响应、密钥或用户输入。
        chain = []
        current = exc
        for _ in range(5):
            if current is None or type(current).__name__ in chain:
                break
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        fields["error_chain"] = chain
        raise
    finally:
        event(stage, elapsed_ms=round((time.perf_counter() - started) * 1000, 3), **fields)


def timed(stage: str):
    """仅记录函数总体耗时，父阶段包含子阶段，不能重复相加。"""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            return call(stage, function, *args, **kwargs)
        return wrapped
    return decorate
