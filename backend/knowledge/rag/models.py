"""文件说明：定义Context、Citation和严格LLM输出的不可变数据模型。

模型只保存程序可验证的数据。LLM在后续阶段只能返回E编号，制度名、文号、
条款和页码始终由Citation Registry从SQLite权威记录生成。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from ..indexing.config import canonical_json, sha256_text


CITATION_CONTRACT_VERSION = "citation_v1"


class AnswerStatus(StrEnum):
    """第一版答案状态，不引入复杂置信度模型。"""

    ANSWER = "ANSWER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICT = "CONFLICT"


ANSWER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "answer", "citations", "conflicts", "warnings"],
    "properties": {
        "status": {"type": "string", "enum": [status.value for status in AnswerStatus]},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {"type": "string", "pattern": r"^E[1-9][0-9]*$"},
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["topic", "positions"],
                "properties": {
                    "topic": {"type": "string"},
                    "positions": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["statement", "citations"],
                            "properties": {
                                "statement": {"type": "string"},
                                "citations": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {
                                        "type": "string",
                                        "pattern": r"^E[1-9][0-9]*$",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class SourceNodeSpan:
    """Chunk到来源Node及双方字符区间的确定性映射。"""

    node_id: int
    source_order: int
    contribution_role: str
    node_char_start: int | None
    node_char_end: int | None
    chunk_char_start: int | None
    chunk_char_end: int | None
    mapping_type: str
    source_text_hash: str
    is_primary: bool
    node_type: str | None = None
    node_number: str | None = None
    node_title: str | None = None
    node_path_text: str | None = None
    node_page_start: int | None = None
    node_page_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceRecord:
    """传给LLM并可由程序渲染为引用的单条证据。"""

    citation_label: str
    evidence_uid: str
    index_run_id: int
    chunk_run_id: int
    parse_run_id: int
    chunk_id: int
    chunk_key: str
    document_id: int
    document_title: str
    document_code: str | None
    document_status: str
    source_reference: str
    path_text: str | None
    page_start: int | None
    page_end: int | None
    primary_node_id: int | None
    source_nodes: tuple[SourceNodeSpan, ...]
    raw_text_hash: str
    dense_rank: int
    dense_score: float
    rerank_rank: int
    rerank_score: float
    text: str
    estimated_tokens: int
    group_key: str
    truncated: bool = False
    citation_version: str = CITATION_CONTRACT_VERSION
    evidence_uid_version: str = "evidence_uid_v1"

    def to_dict(self, *, include_debug: bool = False) -> dict[str, Any]:
        """生成API友好结构，公开审计链并隐藏检索分数与内部映射细节。"""

        value: dict[str, Any] = {
            "citation_version": self.citation_version,
            "evidence_uid_version": self.evidence_uid_version,
            "label": self.citation_label,
            "evidence_uid": self.evidence_uid,
            "document_id": self.document_id,
            "primary_node_id": self.primary_node_id,
            "parse_run_id": self.parse_run_id,
            "chunk_run_id": self.chunk_run_id,
            "index_run_id": self.index_run_id,
            "chunk_id": self.chunk_id,
            "document_title": self.document_title,
            "document_code": self.document_code,
            "document_status": self.document_status,
            "source_reference": self.source_reference,
            "path_text": self.path_text,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "quote": self.text,
            "truncated": self.truncated,
        }
        snapshot_fields = {
            key: value[key]
            for key in (
                "citation_version",
                "evidence_uid_version",
                "label",
                "evidence_uid",
                "document_id",
                "primary_node_id",
                "parse_run_id",
                "chunk_run_id",
                "index_run_id",
                "chunk_id",
                "document_title",
                "document_code",
                "document_status",
                "source_reference",
                "path_text",
                "page_start",
                "page_end",
                "quote",
                "truncated",
            )
        }
        value["snapshot_hash"] = "sha256:" + sha256_text(
            canonical_json(snapshot_fields)
        )
        if include_debug:
            value.update(
                {
                    "chunk_key": self.chunk_key,
                    "source_nodes": [item.to_dict() for item in self.source_nodes],
                    "raw_text_hash": self.raw_text_hash,
                    "dense_rank": self.dense_rank,
                    "dense_score": self.dense_score,
                    "rerank_rank": self.rerank_rank,
                    "rerank_score": self.rerank_score,
                    "estimated_tokens": self.estimated_tokens,
                    "group_key": self.group_key,
                }
            )
        return value


@dataclass(frozen=True)
class EvidenceGroup:
    """同制度、同条款证据的展示分组，不合并或改写证据正文。"""

    group_key: str
    document_id: int
    document_title: str
    document_code: str | None
    path_text: str | None
    evidence_labels: tuple[str, ...]


@dataclass(frozen=True)
class OmittedEvidence:
    """被去重、Top8截断或Token预算排除的候选诊断。"""

    chunk_id: int | None
    reason: str
    rerank_rank: int | None = None


@dataclass(frozen=True)
class ContextBundle:
    """Context Builder的统一输出。"""

    question: str
    index_run_id: int
    retrieval_config_hash: str
    context_config_hash: str
    estimator_version: str
    evidence_budget_tokens: int
    estimated_tokens: int
    evidences: tuple[EvidenceRecord, ...]
    groups: tuple[EvidenceGroup, ...]
    omitted: tuple[OmittedEvidence, ...]
    rendered_context: str

    @property
    def citation_labels(self) -> tuple[str, ...]:
        return tuple(item.citation_label for item in self.evidences)

    def to_dict(self, *, include_debug: bool = False) -> dict[str, Any]:
        """生成可保存的Context诊断结构。"""

        return {
            "question": self.question,
            "index_run_id": self.index_run_id,
            "retrieval_config_hash": self.retrieval_config_hash,
            "context_config_hash": self.context_config_hash,
            "estimator_version": self.estimator_version,
            "evidence_budget_tokens": self.evidence_budget_tokens,
            "estimated_tokens": self.estimated_tokens,
            "evidences": [
                item.to_dict(include_debug=include_debug) for item in self.evidences
            ],
            "groups": [asdict(item) for item in self.groups],
            "omitted": [asdict(item) for item in self.omitted],
            "rendered_context": self.rendered_context,
        }
