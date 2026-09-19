"""文件说明：调用8000 OpenAI兼容Generator并执行版本化传输契约。

客户端固定关闭thinking、启用严格JSON Schema，并只对连接异常、429和5xx执行有限
重试与连接重建。模块只返回模型JSON文本和审计元数据，不解析业务答案。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

import requests

from .config import GenerationConfig, GeneratorContract
from ..telemetry import call, timed, event


class GeneratorError(RuntimeError):
    """Generator调用或服务响应不符合契约。"""


class GeneratorTransportError(GeneratorError):
    """网络或可重试HTTP错误在有限尝试后仍失败。"""


class GeneratorContractError(GeneratorError):
    """服务返回结构、模型或thinking行为不符合冻结契约。"""


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class HttpSession(Protocol):
    trust_env: bool

    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class GeneratorResponse:
    """单次业务生成结果及传输审计信息。"""

    content: str
    response_model: str
    finish_reason: str | None
    usage: Mapping[str, Any]
    elapsed_seconds: float
    attempts: int
    reasoning_present: bool


class OpenAIGeneratorClient:
    """严格契约的OpenAI兼容Chat Completions客户端。"""

    def __init__(
        self,
        contract: GeneratorContract | None = None,
        config: GenerationConfig | None = None,
        *,
        api_key: str | None = "EMPTY",
        retry_backoff_seconds: float = 1.0,
        session_factory: Callable[[], HttpSession] | None = None,
    ) -> None:
        self.contract = contract or GeneratorContract()
        self.config = config or GenerationConfig()
        self.api_key = api_key or "EMPTY"
        self.retry_backoff_seconds = retry_backoff_seconds
        self._session_factory = session_factory or self._default_session
        self._session = self._session_factory()

    @staticmethod
    def _default_session() -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        return session

    @property
    def endpoint_url(self) -> str:
        return self.contract.base_url.rstrip("/") + "/" + self.contract.endpoint.lstrip("/")

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OpenAIGeneratorClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @timed("generator_total")
    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: Mapping[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> GeneratorResponse:
        """执行生成，并允许质量门禁传入独立Schema和更小输出预算。"""

        if not messages:
            raise ValueError("Generator messages不能为空")
        effective_max_tokens = self.config.max_tokens if max_tokens is None else max_tokens
        if effective_max_tokens <= 0:
            raise ValueError("Generator max_tokens必须大于0")
        request_body: dict[str, Any] = {
            "model": self.contract.model,
            "messages": [dict(item) for item in messages],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": effective_max_tokens,
            "response_format": dict(
                response_format or self.config.openai_response_format()
            ),
            **self.config.request_extra_body(),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        last_error: Exception | None = None
        total_attempts = self.config.max_retries + 1

        for attempt in range(1, total_attempts + 1):
            try:
                response = call("generator_http", self._session.post,
                    self.endpoint_url,
                    headers=headers,
                    json=request_body,
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise GeneratorTransportError(
                        f"Generator HTTP {response.status_code}: {response.text[:300]}"
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise GeneratorContractError(
                        f"Generator HTTP {response.status_code}: {response.text[:300]}"
                    )
                body = response.json()
                return self._parse_response(
                    body,
                    attempts=attempt,
                    elapsed_seconds=time.perf_counter() - started,
                )
            except GeneratorContractError:
                raise
            except (requests.RequestException, GeneratorTransportError, ValueError) as exc:
                last_error = exc
                if attempt >= total_attempts:
                    break
                self._rebuild_session()
                event("generator_retry", attempt=attempt, error_type=type(exc).__name__)
                call("generator_backoff", time.sleep, self.retry_backoff_seconds * attempt)

        elapsed = time.perf_counter() - started
        raise GeneratorTransportError(
            f"Generator在{total_attempts}次尝试后失败，耗时{elapsed:.3f}s：{last_error}"
        ) from last_error

    def _rebuild_session(self) -> None:
        self._session.close()
        self._session = self._session_factory()

    def _parse_response(
        self, body: Any, *, attempts: int, elapsed_seconds: float
    ) -> GeneratorResponse:
        if not isinstance(body, dict):
            raise GeneratorContractError("Generator响应根节点必须是对象")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise GeneratorContractError("Generator响应缺少choices[0]")
        first = choices[0]
        message = first.get("message")
        if not isinstance(message, dict):
            raise GeneratorContractError("Generator响应缺少message对象")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GeneratorContractError("Generator响应content为空或类型非法")

        reasoning_present = any(
            bool(value)
            for key, value in message.items()
            if "reason" in str(key).lower() or "analysis" in str(key).lower()
        )
        if not self.config.enable_thinking and reasoning_present:
            raise GeneratorContractError("服务在enable_thinking=false时仍返回非空reasoning")

        response_model = str(body.get("model") or "")
        if response_model and response_model != self.contract.model:
            raise GeneratorContractError(
                f"Generator响应模型不一致：{response_model} != {self.contract.model}"
            )
        usage = body.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        finish_reason = first.get("finish_reason")
        return GeneratorResponse(
            content=content,
            response_model=response_model or self.contract.model,
            finish_reason=None if finish_reason is None else str(finish_reason),
            usage=usage,
            elapsed_seconds=elapsed_seconds,
            attempts=attempts,
            reasoning_present=reasoning_present,
        )
