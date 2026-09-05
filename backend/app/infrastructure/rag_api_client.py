"""文件说明：通过公开 HTTP 契约调用独立 RAG 服务，不访问其内部存储或模型依赖。"""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import ValidationError

from knowledge.contracts import ErrorResponse, QueryResponse


LOGGER = logging.getLogger("policy_platform.api.dependencies.rag_api")


class RagApiClientError(RuntimeError):
    """RAG API 调用失败时供 Platform 统一转换的稳定错误。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        request_id: str,
        retryable: bool,
        http_status: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retryable = retryable
        self.http_status = http_status


class RagApiClient:
    """复用异步 HTTP 连接并校验 rag_api_v1_1 公开响应。"""

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=None,
                write=30.0,
                pool=connect_timeout_seconds,
            ),
        )

    async def query(
        self, query: str, request_id: str, query_scope: str = "CURRENT"
    ) -> QueryResponse:
        """调用唯一公开查询端点；不在 Platform 侧叠加重试。"""

        started = time.perf_counter()
        LOGGER.info(
            "event=dependency_call_started dependency=rag_api operation=query request_id=%s query_scope=%s",
            request_id, query_scope,
        )
        try:
            response = await self._client.post(
                "/v1/rag/query",
                json={"query": query, "query_scope": query_scope},
                headers={"X-Request-ID": request_id},
            )
        except httpx.RequestError as exc:
            LOGGER.error(
                "event=dependency_call_failed dependency=rag_api operation=query request_id=%s query_scope=%s elapsed_ms=%d error_code=RAG_API_UNAVAILABLE error_type=%s",
                request_id, query_scope, int((time.perf_counter() - started) * 1000), type(exc).__name__,
            )
            raise RagApiClientError(
                code="RAG_API_UNAVAILABLE",
                message="制度知识服务暂不可用",
                request_id=request_id,
                retryable=True,
                http_status=503,
            ) from exc

        if response.is_error:
            try:
                detail = ErrorResponse.model_validate(response.json()).error
                LOGGER.warning(
                    "event=dependency_call_failed dependency=rag_api operation=query request_id=%s query_scope=%s status_code=%d elapsed_ms=%d error_code=%s",
                    request_id, query_scope, response.status_code,
                    int((time.perf_counter() - started) * 1000), detail.code,
                )
                raise RagApiClientError(
                    code=detail.code,
                    message=detail.message,
                    request_id=detail.request_id or request_id,
                    retryable=detail.retryable,
                    http_status=response.status_code,
                )
            except (ValueError, ValidationError) as exc:
                LOGGER.error(
                    "event=dependency_response_invalid dependency=rag_api operation=query request_id=%s query_scope=%s status_code=%d elapsed_ms=%d",
                    request_id, query_scope, response.status_code,
                    int((time.perf_counter() - started) * 1000),
                )
                raise RagApiClientError(
                    code="RAG_API_ERROR_RESPONSE_INVALID",
                    message="制度知识服务返回了无效错误响应",
                    request_id=request_id,
                    retryable=response.status_code >= 500,
                    http_status=502,
                ) from exc

        try:
            result = QueryResponse.model_validate(response.json())
            LOGGER.info(
                "event=dependency_call_completed dependency=rag_api operation=query request_id=%s query_scope=%s status_code=%d elapsed_ms=%d result_status=%s",
                request_id, query_scope, response.status_code,
                int((time.perf_counter() - started) * 1000), result.status,
            )
            return result
        except (ValueError, ValidationError) as exc:
            LOGGER.error(
                "event=dependency_response_invalid dependency=rag_api operation=query request_id=%s query_scope=%s status_code=%d elapsed_ms=%d",
                request_id, query_scope, response.status_code,
                int((time.perf_counter() - started) * 1000),
            )
            raise RagApiClientError(
                code="RAG_API_RESPONSE_INVALID",
                message="制度知识服务响应未通过公开契约校验",
                request_id=request_id,
                retryable=False,
                http_status=502,
            ) from exc

    async def close(self) -> None:
        """仅关闭由当前实例创建的连接池。"""

        if self._owns_client:
            await self._client.aclose()
