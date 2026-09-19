"""OpenAI-compatible Embedding 服务客户端。

客户端显式关闭环境代理继承，避免局域网模型地址被系统 HTTP 代理劫持；批量返回会按
index 恢复输入顺序，并校验数量、维度、有限值和零范数。
"""

from __future__ import annotations

import math
import logging
from ..telemetry import call
import time
from typing import Sequence

import requests

from .config import EmbeddingContract


LOGGER = logging.getLogger("policy_platform.worker.dependencies.embedding")


class EmbeddingServiceError(RuntimeError):
    """Embedding 服务返回或契约校验失败。"""


class OpenAIEmbeddingClient:
    """调用 `/v1/embeddings` 的轻量客户端。"""

    def __init__(
        self,
        endpoint: str,
        contract: EmbeddingContract,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        trust_env: bool = False,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.contract = contract
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.trust_env = trust_env
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def format_query(self, query: str) -> str:
        return self.contract.format_query(query)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成向量并执行严格契约校验。"""

        values = [str(text) for text in texts]
        if not values:
            return []
        if any(not text.strip() for text in values):
            raise EmbeddingServiceError("Embedding 输入中存在空文本")

        payload = {"model": self.contract.model, "input": values}
        last_error: Exception | None = None
        operation_started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            attempt_started = time.perf_counter()
            status_code: int | None = None
            LOGGER.info(
                "event=dependency_call_started dependency=embedding operation=embed attempt=%d max_attempts=%d batch_size=%d",
                attempt + 1, self.max_retries + 1, len(values),
            )
            try:
                response = call("embedding_http", self.session.post,
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                )
                status_code = response.status_code
                if response.status_code >= 500 or response.status_code == 429:
                    raise EmbeddingServiceError(
                        f"Embedding服务暂时失败：HTTP {response.status_code}"
                    )
                response.raise_for_status()
                data = response.json()
                vectors = self._validate_response(data, len(values))
                LOGGER.info(
                    "event=dependency_call_completed dependency=embedding operation=embed attempt=%d status_code=%s batch_size=%d elapsed_ms=%d",
                    attempt + 1, status_code, len(values), int((time.perf_counter() - attempt_started) * 1000),
                )
                return vectors
            except (requests.RequestException, ValueError, EmbeddingServiceError) as exc:
                last_error = exc
                # 4xx 契约错误不盲目重试，429 已在上面转为可重试错误。
                retryable = True
                if isinstance(exc, requests.HTTPError):
                    status = exc.response.status_code if exc.response is not None else None
                    if status is not None and 400 <= status < 500 and status != 429:
                        retryable = False
                if attempt < self.max_retries:
                    delay_seconds = min(2**attempt, 4)
                    if retryable:
                        LOGGER.warning(
                            "event=dependency_call_retry dependency=embedding operation=embed attempt=%d status_code=%s retry_in_ms=%d elapsed_ms=%d error_type=%s",
                            attempt + 1, status_code, delay_seconds * 1000,
                            int((time.perf_counter() - attempt_started) * 1000), type(exc).__name__,
                        )
                        call("embedding_backoff", time.sleep, delay_seconds)
                        continue
                break
        LOGGER.error(
            "event=dependency_call_failed dependency=embedding operation=embed attempts=%d batch_size=%d elapsed_ms=%d error_type=%s",
            attempt + 1, len(values), int((time.perf_counter() - operation_started) * 1000),
            type(last_error).__name__ if last_error else "UnknownError",
        )
        raise EmbeddingServiceError("Embedding请求失败，请查看Worker依赖日志") from last_error

    def _validate_response(self, data: object, expected_count: int) -> list[list[float]]:
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise EmbeddingServiceError("Embedding 返回缺少 data 数组")
        items = data["data"]
        if len(items) != expected_count:
            raise EmbeddingServiceError(
                f"Embedding 返回数量不匹配：expected={expected_count}, actual={len(items)}"
            )

        if all(isinstance(item, dict) and isinstance(item.get("index"), int) for item in items):
            items = sorted(items, key=lambda item: int(item["index"]))

        vectors: list[list[float]] = []
        for position, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise EmbeddingServiceError(f"第 {position} 条返回缺少 embedding")
            vector = [float(value) for value in item["embedding"]]
            if len(vector) != self.contract.dimension:
                raise EmbeddingServiceError(
                    f"第 {position} 条向量维度错误："
                    f"expected={self.contract.dimension}, actual={len(vector)}"
                )
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingServiceError(f"第 {position} 条向量包含 NaN 或 Inf")
            norm = math.sqrt(sum(value * value for value in vector))
            if norm <= 1e-12:
                raise EmbeddingServiceError(f"第 {position} 条向量为零范数")
            if self.contract.normalize_embeddings:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        return vectors
