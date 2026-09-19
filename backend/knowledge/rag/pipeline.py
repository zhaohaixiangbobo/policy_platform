"""文件说明：编排Dense→Rerank→Context→Generator→Parser完整只读问答链路。

Pipeline不修改SQLite、Qdrant或任何latest/active指针。引用元数据由程序从Citation
Registry生成；模型输出校验失败时仅重试一次，最终仍失败或证据不支撑时保守降级。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence

from ..indexing.config import sha256_text

from .answer_parser import AnswerParser, AnswerValidationError, ParsedAnswer
from .citation import CitationRegistry
from .config import GenerationConfig, GeneratorContract, RagPipelineConfig
from .generator import GeneratorResponse
from .models import AnswerStatus, ContextBundle
from .prompt import PromptContract, messages_hash
from .quality_gate import AnswerQualityGate
from ..telemetry import event, timed


class TwoStageRetriever(Protocol):
    retrieval_config_hash: str
    config: Any

    def search(self, query: str, *, filters: Any = None) -> list[dict[str, Any]]: ...


class EvidenceContextBuilder(Protocol):
    config: Any

    def build(
        self,
        question: str,
        reranked_results: Sequence[Mapping[str, Any]],
        *,
        retrieval_config_hash: str | None = None,
    ) -> ContextBundle: ...


class AnswerGenerator(Protocol):
    contract: GeneratorContract
    config: GenerationConfig

    def generate(self, messages: Sequence[Mapping[str, str]]) -> GeneratorResponse: ...


@dataclass(frozen=True)
class RagResponse:
    """可审计但默认不泄露内部Prompt和失败原文的端到端响应。"""

    request_id: str
    query: str
    answer: ParsedAnswer
    citation_records: tuple[dict[str, Any], ...]
    retrieval: Mapping[str, Any]
    context: Mapping[str, Any]
    generation: Mapping[str, Any]
    quality_gate: Mapping[str, Any]
    latency_ms: Mapping[str, float]
    validation_failures: tuple[dict[str, Any], ...]

    def to_dict(self, *, include_debug: bool = False) -> dict[str, Any]:
        generation = dict(self.generation)
        quality_gate = dict(self.quality_gate)
        if not include_debug:
            generation.pop("draft_response_sha256s", None)
            quality_gate.pop("claim_bindings", None)
            quality_gate.pop("verdicts", None)
        output = {
            "request_id": self.request_id,
            "query": self.query,
            "status": self.answer.status.value,
            "answerable": self.answer.answerable,
            "answer": self.answer.answer,
            "answerability": self.answer.answerability,
            "reason_code": self.answer.reason_code,
            "missing_fields": list(self.answer.missing_fields),
            "clarification_question": self.answer.clarification_question,
            "citation_labels": list(self.answer.citations),
            "citations": list(self.citation_records),
            "conflicts": [asdict(item) for item in self.answer.conflicts],
            "warnings": list(self.answer.warnings),
            "retrieval": dict(self.retrieval),
            "context": dict(self.context),
            "generation": generation,
            "quality_gate": quality_gate,
            "latency_ms": dict(self.latency_ms),
        }
        if include_debug:
            output["validation_failures"] = list(self.validation_failures)
        elif self.validation_failures:
            generation["validation_failure_count"] = len(
                self.validation_failures
            )
        return output


class RagPipeline:
    """第一版制度RAG端到端编排器。"""

    def __init__(
        self,
        retriever: TwoStageRetriever,
        context_builder: EvidenceContextBuilder,
        generator: AnswerGenerator,
        *,
        prompt: PromptContract | None = None,
        parser: AnswerParser | None = None,
        quality_gate: AnswerQualityGate | None = None,
        config: RagPipelineConfig | None = None,
    ) -> None:
        self.retriever = retriever
        self.context_builder = context_builder
        self.generator = generator
        self.prompt = prompt or PromptContract()
        self.parser = parser or AnswerParser()
        self.quality_gate = quality_gate or AnswerQualityGate()
        self.config = config or RagPipelineConfig()

    @timed("pipeline_total")
    def query(
        self, question: str, *, filters: Any = None, include_debug: bool = False
    ) -> RagResponse:
        normalized_question = " ".join(question.split())
        if not normalized_question:
            raise ValueError("Question不能为空")
        total_started = time.perf_counter()

        retrieval_started = time.perf_counter()
        reranked_results = self.retriever.search(normalized_question, filters=filters)
        retrieval_ms = (time.perf_counter() - retrieval_started) * 1000

        context_started = time.perf_counter()
        bundle = self.context_builder.build(
            normalized_question,
            reranked_results,
            retrieval_config_hash=self.retriever.retrieval_config_hash,
        )
        context_ms = (time.perf_counter() - context_started) * 1000
        registry = CitationRegistry(bundle.evidences)

        validation_failures: list[dict[str, Any]] = []
        generator_responses: list[GeneratorResponse] = []
        request_message_hashes: list[str] = []
        parser_failure_code: str | None = None

        if not bundle.evidences:
            parsed = ParsedAnswer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer="现有证据不足，无法根据当前制度资料确定。",
                citations=(),
                conflicts=(),
                warnings=("检索与上下文构建未产生可用证据",),
            )
        else:
            base_messages = self.prompt.build_messages(
                normalized_question, bundle.rendered_context
            )
            messages = base_messages
            parsed = None
            max_validation_attempts = self.config.answer_validation_retries + 1
            for validation_attempt in range(1, max_validation_attempts + 1):
                request_message_hashes.append(messages_hash(messages))
                response = self.generator.generate(messages)
                generator_responses.append(response)
                try:
                    parsed = self.parser.parse(response.content, registry)
                    break
                except AnswerValidationError as exc:
                    event("answer_validation_failed", attempt=validation_attempt, error_code=exc.code)
                    validation_failures.append(
                        {
                            "validation_attempt": validation_attempt,
                            "error_code": exc.code,
                            "error": exc.message,
                            "raw_response": response.content,
                            "raw_response_sha256": sha256_text(response.content),
                            "generator_elapsed_seconds": response.elapsed_seconds,
                            "transport_attempts": response.attempts,
                        }
                    )
                    if validation_attempt >= max_validation_attempts:
                        parser_failure_code = exc.code
                        break
                    messages = self.prompt.build_validation_retry_messages(
                        base_messages, response.content, str(exc)
                    )
        if parsed is None:
            decision = self.quality_gate.parser_failure(
                f"answer_parser_{parser_failure_code or 'unknown_failure'}"
            )
        else:
            decision = self.quality_gate.evaluate(
                normalized_question,
                parsed,
                registry,
            )
        parsed = decision.answer
        event("generation_summary", validation_attempts=len(generator_responses), transport_attempts=sum(item.attempts for item in generator_responses), verifier_attempts=decision.audit.verifier_attempts)
        quality_gate_audit = decision.audit.to_dict(include_debug=include_debug)

        llm_ms = (
            sum(item.elapsed_seconds for item in generator_responses)
            + decision.audit.verifier_elapsed_seconds
        ) * 1000
        configured_dense_count = int(
            getattr(getattr(self.retriever, "config", None), "candidate_top_k", 20)
        )
        configured_rerank_count = int(
            getattr(getattr(self.retriever, "config", None), "output_top_k", 8)
        )
        retrieval_audit = {
            "index_run_id": bundle.index_run_id,
            "dense_configured_count": configured_dense_count,
            "rerank_configured_count": configured_rerank_count,
            "rerank_returned_count": len(reranked_results),
            "retrieval_config_hash": bundle.retrieval_config_hash,
        }
        context_audit = {
            "evidence_count": len(bundle.evidences),
            "estimated_tokens": bundle.estimated_tokens,
            "evidence_budget_tokens": bundle.evidence_budget_tokens,
            "omitted_count": len(bundle.omitted),
            "context_builder_version": self.context_builder.config.builder_version,
            "context_config_hash": bundle.context_config_hash,
            "token_estimator_version": bundle.estimator_version,
        }
        generation_audit = {
            "skipped": not generator_responses,
            "model": self.generator.contract.model,
            "model_revision": self.generator.contract.model_revision,
            "generator_contract_hash": self.generator.contract.contract_hash,
            "generation_config_hash": self.generator.config.config_hash,
            "prompt_version": self.prompt.prompt_version,
            "prompt_hash": self.prompt.prompt_hash,
            "schema_version": self.generator.config.schema_version,
            "schema_hash": self.generator.config.schema_hash,
            "pipeline_version": self.config.pipeline_version,
            "pipeline_config_hash": self.config.config_hash,
            "validation_attempts": len(generator_responses),
            "transport_attempts": sum(item.attempts for item in generator_responses),
            "request_message_hashes": request_message_hashes,
            "finish_reasons": [item.finish_reason for item in generator_responses],
            "usage": [dict(item.usage) for item in generator_responses],
        }
        if include_debug:
            # 受控诊断只保留草稿哈希；有效草稿正文不会进入公开响应或普通查询日志。
            generation_audit["draft_response_sha256s"] = [
                sha256_text(item.content) for item in generator_responses
            ]
        total_ms = (time.perf_counter() - total_started) * 1000
        citations = tuple(
            registry.api_citations(parsed.citations, include_debug=include_debug)
        )
        return RagResponse(
            request_id=str(uuid.uuid4()),
            query=normalized_question,
            answer=parsed,
            citation_records=citations,
            retrieval=retrieval_audit,
            context=context_audit,
            generation=generation_audit,
            quality_gate=quality_gate_audit,
            latency_ms={
                "total": round(total_ms, 3),
                "retrieval": round(retrieval_ms, 3),
                "context": round(context_ms, 3),
                "llm": round(llm_ms, 3),
            },
            validation_failures=tuple(validation_failures),
        )
