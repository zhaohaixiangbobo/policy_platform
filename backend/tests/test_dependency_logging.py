"""文件说明：验证外部依赖日志记录重试与耗时，同时不泄露请求正文或响应体。"""

import logging

import pytest

from knowledge.indexing.config import EmbeddingContract
from knowledge.indexing.embedding import EmbeddingServiceError, OpenAIEmbeddingClient
from knowledge.indexing.qdrant_store import QdrantVectorStore


class _UnavailableResponse:
    status_code = 503
    text = "不应进入日志的服务响应正文"


class _UnavailableSession:
    def post(self, *_args, **_kwargs):
        return _UnavailableResponse()


def test_embedding_retry_logs_are_safe(monkeypatch, caplog) -> None:
    client = OpenAIEmbeddingClient(
        "http://embedding.test/v1/embeddings",
        EmbeddingContract(dimension=2),
        max_retries=1,
    )
    client.session = _UnavailableSession()  # type: ignore[assignment]
    monkeypatch.setattr("knowledge.indexing.embedding.time.sleep", lambda _seconds: None)

    with caplog.at_level(logging.INFO, logger="policy_platform.worker.dependencies.embedding"):
        with pytest.raises(EmbeddingServiceError, match="查看Worker依赖日志"):
            client.embed(["不应进入日志的制度正文"])

    assert "dependency_call_retry" in caplog.text
    assert "dependency_call_failed" in caplog.text
    assert "不应进入日志的制度正文" not in caplog.text
    assert _UnavailableResponse.text not in caplog.text


def test_qdrant_call_logs_error_type_without_error_message(caplog) -> None:
    def failed_call():
        raise RuntimeError("不应进入日志的Qdrant内部详情")

    with caplog.at_level(logging.INFO, logger="policy_platform.worker.dependencies.qdrant"):
        with pytest.raises(RuntimeError):
            QdrantVectorStore._call(
                "test_operation", failed_call, collection_name="policy_test", item_count=2
            )

    assert "error_type=RuntimeError" in caplog.text
    assert "不应进入日志的Qdrant内部详情" not in caplog.text
