"""文件说明：在 Platform 进程内管理单线程 RAG Runtime 并输出稳定公开契约。

Runtime 及其 SQLite/HTTP 客户端始终在同一专用线程中创建、查询和关闭。
应用启动不连接 Qdrant 或模型服务，首次问答时才惰性初始化知识查询栈。
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Protocol

from pydantic import ValidationError

from knowledge.contracts import QueryResponse, public_query_response
from knowledge.rag.generator import GeneratorContractError, GeneratorTransportError
from knowledge.rag.runtime import RagRuntime, RagRuntimeSettings
from knowledge.retrieval import SearchFilters


LOGGER = logging.getLogger("policy_platform.api.knowledge_query")


class QueryRuntime(Protocol):
    """便于使用真实 RagRuntime 或确定性测试替身。"""

    def query(
        self,
        question: str,
        *,
        filters: SearchFilters | None = None,
        include_debug: bool = False,
    ) -> object: ...

    def close(self) -> None: ...


class KnowledgeServiceError(RuntimeError):
    """进程内知识查询失败时返回给 Platform 的稳定错误。"""

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


class KnowledgeService:
    """将同步 RagRuntime 封装成 FastAPI 可安全等待的进程内查询服务。"""

    def __init__(
        self,
        settings: RagRuntimeSettings,
        *,
        runtime_factory: Callable[[RagRuntimeSettings], QueryRuntime] = RagRuntime,
    ) -> None:
        self._settings = settings
        self._runtime_factory = runtime_factory
        self._runtime: QueryRuntime | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="policy-knowledge-query",
        )
        self._closed = False

    async def query(
        self,
        query: str,
        request_id: str,
        query_scope: str = "CURRENT",
        document_scope_mode: str = "ALL",
        document_ids: tuple[int, ...] = (),
    ) -> QueryResponse:
        """按 Platform 已解析的状态和制度范围执行进程内问答。"""

        normalized_query = str(query).strip()
        normalized_scope = str(query_scope).upper()
        normalized_mode = str(document_scope_mode).upper()
        normalized_ids = tuple(sorted(set(int(value) for value in document_ids)))
        if not normalized_query:
            raise self._input_error("问题不能为空", request_id)
        if normalized_scope not in {"CURRENT", "HISTORICAL"}:
            raise self._input_error("查询范围只支持CURRENT或HISTORICAL", request_id)
        if normalized_mode not in {"ALL", "SELECTED"}:
            raise self._input_error("制度范围只支持ALL或SELECTED", request_id)
        if normalized_mode == "SELECTED" and not normalized_ids:
            raise self._input_error("指定制度查询必须包含document_id", request_id)
        if any(document_id <= 0 for document_id in normalized_ids):
            raise self._input_error("document_id必须是正整数", request_id)
        if self._closed:
            raise KnowledgeServiceError(
                code="KNOWLEDGE_SERVICE_CLOSED",
                message="制度知识服务已停止",
                request_id=request_id,
                retryable=True,
                http_status=503,
            )

        started = time.perf_counter()
        LOGGER.info(
            "event=knowledge_query_started request_id=%s query_scope=%s document_scope_mode=%s document_scope_count=%d",
            request_id,
            normalized_scope,
            normalized_mode,
            len(normalized_ids),
        )
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._query_in_worker,
                normalized_query,
                request_id,
                normalized_scope,
                normalized_mode,
                normalized_ids,
            )
        except KnowledgeServiceError:
            raise
        except (ValidationError, KeyError, TypeError, ValueError, GeneratorContractError) as exc:
            self._log_failure(request_id, normalized_scope, started, exc)
            raise KnowledgeServiceError(
                code="KNOWLEDGE_RESPONSE_INVALID",
                message="制度知识查询结果未通过契约校验",
                request_id=request_id,
                retryable=False,
                http_status=502,
            ) from exc
        except GeneratorTransportError as exc:
            self._log_failure(request_id, normalized_scope, started, exc)
            raise KnowledgeServiceError(
                code="KNOWLEDGE_MODEL_UNAVAILABLE",
                message="制度知识模型服务暂不可用",
                request_id=request_id,
                retryable=True,
                http_status=503,
            ) from exc
        except Exception as exc:
            self._log_failure(request_id, normalized_scope, started, exc)
            raise KnowledgeServiceError(
                code="KNOWLEDGE_SERVICE_UNAVAILABLE",
                message="制度知识服务暂不可用",
                request_id=request_id,
                retryable=True,
                http_status=503,
            ) from exc

        LOGGER.info(
            "event=knowledge_query_completed request_id=%s query_scope=%s result_status=%s elapsed_ms=%d",
            request_id,
            normalized_scope,
            result.status,
            int((time.perf_counter() - started) * 1000),
        )
        return result

    def _query_in_worker(
        self,
        question: str,
        request_id: str,
        query_scope: str,
        document_scope_mode: str,
        document_ids: tuple[int, ...],
    ) -> QueryResponse:
        """Runtime的创建、SQLite访问和资源释放均限定在专用线程。"""

        if self._runtime is None:
            self._runtime = self._runtime_factory(self._settings)
        filters = SearchFilters(
            document_ids=document_ids if document_scope_mode == "SELECTED" else (),
            document_statuses=("effective",)
            if query_scope == "CURRENT"
            else ("repealed", "expired"),
        )
        internal = self._runtime.query(question, filters=filters, include_debug=False)
        engine_request_id = str(getattr(internal, "request_id", request_id))
        return public_query_response(internal, engine_request_id)

    async def close(self) -> None:
        """先在专用线程释放 Runtime，再停止执行器。"""

        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._close_in_worker)
        self._executor.shutdown(wait=True)

    def _close_in_worker(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
            self._runtime = None

    @staticmethod
    def _input_error(message: str, request_id: str) -> KnowledgeServiceError:
        return KnowledgeServiceError(
            code="KNOWLEDGE_QUERY_INVALID",
            message=message,
            request_id=request_id,
            retryable=False,
            http_status=400,
        )

    @staticmethod
    def _log_failure(
        request_id: str,
        query_scope: str,
        started: float,
        error: BaseException,
    ) -> None:
        LOGGER.error(
            "event=knowledge_query_failed request_id=%s query_scope=%s elapsed_ms=%d error_type=%s",
            request_id,
            query_scope,
            int((time.perf_counter() - started) * 1000),
            type(error).__name__,
        )


__all__ = ["KnowledgeService", "KnowledgeServiceError"]
