"""文件说明：验证 Platform 只通过公开 HTTP 契约调用 RAG 并透传查询范围。"""

import asyncio

import httpx

from app.infrastructure.rag_api_client import RagApiClient, RagApiClientError
from tests.test_chat_integration import response


def test_rag_api_client_posts_query_scope_and_validates_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode("utf-8")
        captured["request_id"] = request.headers.get("X-Request-ID")
        return httpx.Response(200, json=response("ANSWER").model_dump(mode="json"))

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="http://rag.test", transport=transport)
    client = RagApiClient("http://ignored", client=http_client)
    result = asyncio.run(client.query("历史规定", "platform-1", "HISTORICAL"))
    asyncio.run(http_client.aclose())

    assert captured["path"] == "/v1/rag/query"
    assert '"query_scope":"HISTORICAL"' in str(captured["body"]).replace(" ", "")
    assert captured["request_id"] == "platform-1"
    assert result.contract_version == "rag_api_v1_1"


def test_rag_api_client_preserves_public_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"code": "RAG_BUSY", "message": "服务繁忙", "request_id": "rag-2", "retryable": True}},
        )

    http_client = httpx.AsyncClient(base_url="http://rag.test", transport=httpx.MockTransport(handler))
    client = RagApiClient("http://ignored", client=http_client)
    try:
        asyncio.run(client.query("测试", "platform-2"))
        raise AssertionError("应抛出公开错误")
    except RagApiClientError as exc:
        assert exc.code == "RAG_BUSY"
        assert exc.request_id == "rag-2"
        assert exc.http_status == 503
    asyncio.run(http_client.aclose())
