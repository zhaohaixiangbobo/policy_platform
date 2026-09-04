"""OpenAI-compatible Embedding 服务客户端。

客户端显式关闭环境代理继承，避免局域网模型地址被系统 HTTP 代理劫持；批量返回会按
index 恢复输入顺序，并校验数量、维度、有限值和零范数。
"""

from __future__ import annotations

import math
import time
from typing import Sequence

import requests

from .config import EmbeddingContract


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
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 500 or response.status_code == 429:
                    raise EmbeddingServiceError(
                        f"Embedding 服务暂时失败：HTTP {response.status_code} {response.text[:500]}"
                    )
                response.raise_for_status()
                data = response.json()
                return self._validate_response(data, len(values))
            except (requests.RequestException, ValueError, EmbeddingServiceError) as exc:
                last_error = exc
                # 4xx 契约错误不盲目重试，429 已在上面转为可重试错误。
                if isinstance(exc, requests.HTTPError):
                    status = exc.response.status_code if exc.response is not None else None
                    if status is not None and 400 <= status < 500 and status != 429:
                        break
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 4))
        raise EmbeddingServiceError(f"Embedding 请求失败：{last_error}") from last_error

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
