"""文件说明：验证阶段追踪的关联、HTTP状态、异常收尾与请求隔离。"""

import json
import logging
import time
from types import SimpleNamespace

import pytest

from knowledge.telemetry import call, event, query_trace


def test_trace_success_failure_and_reset(caplog):
    with caplog.at_level(logging.INFO, logger="policy_platform.api.query_timing"):
        with query_trace("request-one", time.perf_counter()):
            call("generator_http", lambda: SimpleNamespace(status_code=503))
            event("answer_validation_failed", attempt=1, error_code="invalid_reason")
        with pytest.raises(ValueError):
            with query_trace("request-two", time.perf_counter()):
                call("generator_http", lambda: (_ for _ in ()).throw(ValueError("private model content")))
        event("must_not_leak")
    summaries = [json.loads(record.message.split("data=", 1)[1]) for record in caplog.records if "query_timing_summary" in record.message]
    assert len(summaries) == 2
    assert summaries[0]["request_id"] == "request-one"
    assert summaries[0]["events"][1]["status_code"] == 503
    assert summaries[1]["request_id"] == "request-two"
    assert summaries[1]["error_type"] == "ValueError"
    assert len(summaries[1]["events"]) == 2
    assert "private model content" not in caplog.text
    assert "must_not_leak" not in caplog.text
