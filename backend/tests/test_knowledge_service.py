"""文件说明：验证进程内知识查询的线程边界、范围过滤、公开契约和安全错误。"""

import asyncio
import logging
import threading

import pytest

from knowledge.rag.runtime import RagRuntimeSettings
from knowledge.retrieval import SearchFilters
from knowledge.service import KnowledgeService, KnowledgeServiceError


class _InternalResult:
    """提供 public_query_response 需要的最小内部RAG结果。"""

    request_id = "engine-request-1"

    def to_dict(self, *, include_debug: bool = False) -> dict[str, object]:
        assert include_debug is False
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "answerable": False,
            "answer": "现有证据不足。",
            "citations": [],
            "conflicts": [],
            "warnings": [],
            "retrieval": {
                "index_run_id": 7,
                "dense_configured_count": 20,
                "rerank_configured_count": 8,
                "rerank_returned_count": 0,
                "retrieval_config_hash": "retrieval-test",
            },
            "context": {"context_config_hash": "context-test"},
            "generation": {
                "pipeline_version": "rag-test",
                "model": "generator-test",
                "model_revision": "revision-test",
                "prompt_version": "prompt-test",
                "schema_version": "schema-test",
            },
            "quality_gate": {
                "version": "answer_quality_gate_v2",
                "status": "NOT_REQUIRED",
                "semantic_verification": "not_required",
                "checked_claim_count": 0,
                "reason_codes": [],
                "verifier_schema_version": "verifier-schema-test",
                "verifier_schema_hash": "verifier-schema-hash",
                "verifier_prompt_hash": "verifier-prompt-hash",
            },
            "latency_ms": {"total": 1.0, "retrieval": 1.0, "context": 0.0, "llm": 0.0},
        }


class _RecordingRuntime:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.state["created_thread"] = threading.get_ident()

    def query(
        self,
        question: str,
        *,
        filters: SearchFilters | None = None,
        include_debug: bool = False,
    ) -> _InternalResult:
        self.state["query_thread"] = threading.get_ident()
        self.state["question"] = question
        self.state["filters"] = filters
        self.state["include_debug"] = include_debug
        return _InternalResult()

    def close(self) -> None:
        self.state["closed_thread"] = threading.get_ident()


def test_in_process_query_uses_dedicated_thread_and_exact_filters(caplog) -> None:
    state: dict[str, object] = {}
    service = KnowledgeService(
        RagRuntimeSettings(),
        runtime_factory=lambda _settings: _RecordingRuntime(state),
    )

    async def scenario():
        with caplog.at_level(logging.INFO, logger="policy_platform.api.knowledge_query"):
            result = await service.query(
                "不应进入日志的问题",
                "platform-request-1",
                "HISTORICAL",
                "SELECTED",
                (8, 2, 8),
            )
        await service.close()
        return result

    result = asyncio.run(scenario())
    filters = state["filters"]
    assert isinstance(filters, SearchFilters)
    assert filters.document_ids == (2, 8)
    assert filters.document_statuses == ("repealed", "expired")
    assert state["created_thread"] == state["query_thread"] == state["closed_thread"]
    assert state["query_thread"] != threading.get_ident()
    assert result.request_id == "engine-request-1"
    assert result.contract_version == "rag_api_v1_1"
    assert result.quality_gate.version == "answer_quality_gate_v2"
    assert "knowledge_query_completed" in caplog.text
    assert "不应进入日志的问题" not in caplog.text


def test_current_all_query_only_filters_effective_status() -> None:
    state: dict[str, object] = {}
    service = KnowledgeService(
        RagRuntimeSettings(),
        runtime_factory=lambda _settings: _RecordingRuntime(state),
    )

    async def scenario():
        result = await service.query("现行制度", "platform-request-2")
        await service.close()
        return result

    asyncio.run(scenario())
    filters = state["filters"]
    assert isinstance(filters, SearchFilters)
    assert filters.document_ids == ()
    assert filters.document_statuses == ("effective",)


def test_runtime_failure_becomes_stable_error_without_leaking_details(caplog) -> None:
    class _FailingRuntime(_RecordingRuntime):
        def query(self, *args, **kwargs):
            raise RuntimeError("不应返回给用户的内部地址")

    service = KnowledgeService(
        RagRuntimeSettings(),
        runtime_factory=lambda _settings: _FailingRuntime({}),
    )

    async def scenario():
        with caplog.at_level(logging.INFO, logger="policy_platform.api.knowledge_query"):
            with pytest.raises(KnowledgeServiceError) as error:
                await service.query("测试问题", "platform-request-3")
        await service.close()
        return error.value

    error = asyncio.run(scenario())
    assert error.code == "KNOWLEDGE_SERVICE_UNAVAILABLE"
    assert error.http_status == 503
    assert error.retryable is True
    assert "不应返回给用户的内部地址" not in caplog.text


def test_selected_scope_requires_document_ids_without_starting_runtime() -> None:
    started = False

    def factory(_settings):
        nonlocal started
        started = True
        return _RecordingRuntime({})

    service = KnowledgeService(RagRuntimeSettings(), runtime_factory=factory)

    async def scenario():
        with pytest.raises(KnowledgeServiceError) as error:
            await service.query("测试", "platform-request-4", "CURRENT", "SELECTED", ())
        await service.close()
        return error.value

    error = asyncio.run(scenario())
    assert error.code == "KNOWLEDGE_QUERY_INVALID"
    assert error.http_status == 400
    assert started is False
