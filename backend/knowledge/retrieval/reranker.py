"""文件说明：8004 vLLM Qwen3 Reranker 的正式 HTTP 客户端。

客户端只发送 OpenAPI 明确支持的 model/query/documents/top_n，禁止 instruction、
activation 和 truncate 等未支持字段；同时校验返回数量、索引、分数和模型标识。
"""

from __future__ import annotations
from ..telemetry import call

import math
import time
from dataclasses import dataclass
from typing import Any, Sequence

import requests

from ..indexing.config import RerankConfig, RerankerContract


class RerankerServiceError(RuntimeError):
    """Reranker 请求失败或返回不符合冻结契约。"""


@dataclass(frozen=True)
class RerankItem:
    """一条候选在 Reranker 返回中的原始索引和分数。"""

    index: int
    score: float


@dataclass(frozen=True)
class RerankResponse:
    """一次经过严格校验的 Reranker 响应。"""

    items: tuple[RerankItem, ...]
    response_model: str | None
    elapsed_seconds: float
    attempts: int


class OpenAIRerankClient:
    """调用 `/v1/rerank`，并在连接重置时有限重试和重建会话。"""

    def __init__(
        self,
        endpoint: str,
        contract: RerankerContract,
        config: RerankConfig,
        *,
        api_key: str | None = None,
        trust_env: bool = False,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.contract = contract
        self.config = config
        self.api_key = api_key
        self.trust_env = trust_env
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        if config.connection_mode == "close":
            self.headers["Connection"] = "close"
        self.session = self._new_session()

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.trust_env = self.trust_env
        return session

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "OpenAIRerankClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> RerankResponse:
        """仅按冻结字段构造请求，并返回按分数降序排列的结果。"""

        normalized_query = " ".join(str(query).split())
        values = [str(document) for document in documents]
        if not normalized_query:
            raise RerankerServiceError("Reranker query 不能为空")
        if not values or any(not document.strip() for document in values):
            raise RerankerServiceError("Reranker documents 不能为空或包含空文本")
        if not 1 <= top_n <= len(values):
            raise RerankerServiceError("top_n 必须位于 1 到 documents 数量之间")

        # 这里故意不接收 **kwargs，从函数签名层面禁止未支持字段进入请求。
        payload = {
            "model": self.contract.model,
            "query": normalized_query,
            "documents": values,
            "top_n": top_n,
        }
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = call("reranker_http", self.session.post,
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=self.config.request_timeout_seconds,
                )
                if response.status_code >= 500 or response.status_code == 429:
                    raise RerankerServiceError(
                        f"Reranker 服务暂时失败：HTTP {response.status_code} "
                        f"{response.text[:500]}"
                    )
                response.raise_for_status()
                body = response.json()
                items, response_model = self._validate_response(body, len(values), top_n)
                return RerankResponse(
                    items=tuple(items),
                    response_model=response_model,
                    elapsed_seconds=round(time.perf_counter() - started, 6),
                    attempts=attempt + 1,
                )
            except (requests.RequestException, ValueError, RerankerServiceError) as exc:
                last_error = exc
                if isinstance(exc, requests.HTTPError):
                    status = exc.response.status_code if exc.response is not None else None
                    if status is not None and 400 <= status < 500 and status != 429:
                        break
                if attempt < self.config.max_retries:
                    # 主动断连后重建连接池，避免复用已经失效的 keep-alive 连接。
                    self.session.close()
                    self.session = self._new_session()
                    call("reranker_backoff", time.sleep, self.config.retry_backoff_seconds * (2**attempt))
        raise RerankerServiceError(f"Reranker 请求失败：{last_error}") from last_error

    def _validate_response(
        self, body: object, document_count: int, expected_count: int
    ) -> tuple[list[RerankItem], str | None]:
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise RerankerServiceError("Reranker 返回缺少 results 数组")
        rows = body["results"]
        if len(rows) != expected_count:
            raise RerankerServiceError(
                f"Reranker 返回数量错误：expected={expected_count}, actual={len(rows)}"
            )
        items: list[RerankItem] = []
        seen: set[int] = set()
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                raise RerankerServiceError(f"第 {position} 条 Reranker 结果不是对象")
            index = row.get("index")
            score = row.get("relevance_score", row.get("score"))
            if not isinstance(index, int) or not 0 <= index < document_count:
                raise RerankerServiceError(f"第 {position} 条 index 非法：{index}")
            if index in seen:
                raise RerankerServiceError(f"Reranker 返回重复 index：{index}")
            if not isinstance(score, (int, float)) or not math.isfinite(score):
                raise RerankerServiceError(f"第 {position} 条 score 非法：{score}")
            seen.add(index)
            items.append(RerankItem(index=index, score=float(score)))
        items.sort(key=lambda item: item.score, reverse=True)
        response_model = body.get("model")
        if response_model is not None and response_model != self.contract.model:
            raise RerankerServiceError(
                f"Reranker 响应模型不一致：{response_model} != {self.contract.model}"
            )
        return items, response_model if isinstance(response_model, str) else None
