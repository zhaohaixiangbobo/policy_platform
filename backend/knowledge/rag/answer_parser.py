"""文件说明：解析严格JSON答案并执行引用白名单与状态业务校验。

服务端JSON Schema只约束基本结构；本模块继续验证正文[E]引用、citations数组、
Citation Registry白名单及冲突分组。校验失败直接报错，由Pipeline执行一次有限重试。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .citation import CitationRegistry
from .models import AnswerStatus, ANSWER_JSON_SCHEMA, ANSWERABILITIES, REASON_CODES, MISSING_FIELDS


_CITATION_PATTERN = re.compile(r"\[(E[1-9][0-9]*)\]")
_ROOT_KEYS = set(ANSWER_JSON_SCHEMA["required"])


class AnswerValidationError(ValueError):
    """模型答案未通过程序业务校验。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ConflictPosition:
    statement: str
    citations: tuple[str, ...]


@dataclass(frozen=True)
class ConflictRecord:
    topic: str
    positions: tuple[ConflictPosition, ...]


@dataclass(frozen=True)
class ParsedAnswer:
    """已通过全部确定性程序校验的模型答案。"""

    status: AnswerStatus
    answer: str
    citations: tuple[str, ...]
    conflicts: tuple[ConflictRecord, ...]
    warnings: tuple[str, ...]
    answerability: str = "NONE"
    reason_code: str = "NO_RELEVANT_EVIDENCE"
    missing_fields: tuple[str, ...] = ()
    clarification_question: str | None = None

    @property
    def answerable(self) -> bool:
        return self.status != AnswerStatus.INSUFFICIENT_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "answerability": self.answerability,
            "reason_code": self.reason_code,
            "missing_fields": list(self.missing_fields),
            "clarification_question": self.clarification_question,
            "answer": self.answer,
            "answerable": self.answerable,
            "citations": list(self.citations),
            "conflicts": [asdict(item) for item in self.conflicts],
            "warnings": list(self.warnings),
        }


class AnswerParser:
    """将Generator JSON文本转换为已验证的ParsedAnswer。"""

    def parse(self, content: str, registry: CitationRegistry) -> ParsedAnswer:
        try:
            value = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AnswerValidationError("invalid_json", "响应不是合法JSON对象") from exc
        if not isinstance(value, dict):
            raise AnswerValidationError("invalid_root", "响应根节点必须是对象")
        actual_keys = set(value)
        if actual_keys != _ROOT_KEYS:
            missing = sorted(_ROOT_KEYS - actual_keys)
            extra = sorted(actual_keys - _ROOT_KEYS)
            raise AnswerValidationError(
                "invalid_fields", f"字段必须严格匹配Schema；missing={missing}, extra={extra}"
            )

        try:
            status = AnswerStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise AnswerValidationError("invalid_status", "status不属于三个合法状态") from exc
        answer = self._nonempty_string(value["answer"], "answer")
        citations = self._string_tuple(value["citations"], "citations", allow_empty=True)
        warnings = self._string_tuple(value["warnings"], "warnings", allow_empty=True)
        self._require_unique(citations, "citations")
        self._validate_labels(citations, registry, "citations")

        body_labels = tuple(dict.fromkeys(_CITATION_PATTERN.findall(answer)))
        if set(body_labels) != set(citations):
            raise AnswerValidationError(
                "citation_mismatch",
                f"正文引用{body_labels}必须与citations数组{citations}集合一致",
            )

        conflicts = self._parse_conflicts(value["conflicts"], registry, citations)
        if status == AnswerStatus.ANSWER:
            if not citations:
                raise AnswerValidationError("answer_without_citation", "ANSWER至少需要一个有效引用")
            if conflicts:
                raise AnswerValidationError("answer_with_conflict", "ANSWER不得携带conflicts")
        elif status == AnswerStatus.INSUFFICIENT_EVIDENCE:
            if conflicts:
                raise AnswerValidationError(
                    "insufficient_with_conflict", "INSUFFICIENT_EVIDENCE不得携带conflicts"
                )
        else:
            if not conflicts:
                raise AnswerValidationError("conflict_missing", "CONFLICT必须提供冲突结构")
            conflict_labels = {
                label
                for conflict in conflicts
                for position in conflict.positions
                for label in position.citations
            }
            if len(conflict_labels) < 2:
                raise AnswerValidationError(
                    "conflict_evidence_too_few", "CONFLICT至少需要两个不同证据编号"
                )

        ability = value["answerability"]
        reason = value["reason_code"]
        allowed = {
            AnswerStatus.ANSWER: ("SUFFICIENT", "PARTIAL"),
            AnswerStatus.INSUFFICIENT_EVIDENCE: ("PARTIAL", "NONE"),
            AnswerStatus.CONFLICT: ("SUFFICIENT", "PARTIAL"),
        }
        if ability not in ANSWERABILITIES or ability not in allowed[status]:
            raise AnswerValidationError("invalid_answerability", "status与answerability组合非法")
        if reason not in REASON_CODES[:6]:
            raise AnswerValidationError("invalid_reason", "reason_code不是模型可用原因码")
        missing = self._string_tuple(value["missing_fields"], "missing_fields", allow_empty=True)
        self._require_unique(missing, "missing_fields")
        if any(field not in MISSING_FIELDS for field in missing):
            raise AnswerValidationError("invalid_missing_fields", "包含未支持的澄清字段")
        question = value["clarification_question"]
        if question is not None:
            question = self._nonempty_string(question, "clarification_question")
            if _CITATION_PATTERN.search(question):
                raise AnswerValidationError("invalid_clarification", "追问只用于收集用户条件，不携带证据引用")
        if reason == "MISSING_USER_CONTEXT":
            if ability != "PARTIAL" or not missing or question is None:
                raise AnswerValidationError("invalid_clarification", "缺用户条件时须给出PARTIAL、字段和追问")
        elif missing or question is not None:
            raise AnswerValidationError("invalid_clarification", "只有缺用户条件时提供澄清字段和追问")
        if (reason == "COMPLETE") != (status == AnswerStatus.ANSWER and ability == "SUFFICIENT"):
            raise AnswerValidationError("invalid_reason", "完整回答使用COMPLETE")
        if (reason == "CONFLICTING_EVIDENCE") != (status == AnswerStatus.CONFLICT):
            raise AnswerValidationError("invalid_reason", "冲突状态与原因必须一致")
        if (reason == "NO_RELEVANT_EVIDENCE") != (ability == "NONE"):
            raise AnswerValidationError("invalid_reason", "无相关证据对应NONE")
        if ability == "PARTIAL" and not citations:
            raise AnswerValidationError("partial_without_citation", "部分答案须引用相关证据")
        return ParsedAnswer(status, answer, citations, conflicts, warnings, ability, reason, missing, question)

    def _parse_conflicts(
        self,
        value: Any,
        registry: CitationRegistry,
        top_level_citations: tuple[str, ...],
    ) -> tuple[ConflictRecord, ...]:
        if not isinstance(value, list):
            raise AnswerValidationError("invalid_conflicts", "conflicts必须是数组")
        parsed: list[ConflictRecord] = []
        for conflict_index, item in enumerate(value):
            if not isinstance(item, dict) or set(item) != {"topic", "positions"}:
                raise AnswerValidationError(
                    "invalid_conflict", f"conflicts[{conflict_index}]字段非法"
                )
            topic = self._nonempty_string(item["topic"], f"conflicts[{conflict_index}].topic")
            positions_value = item["positions"]
            if not isinstance(positions_value, list) or len(positions_value) < 2:
                raise AnswerValidationError(
                    "invalid_positions", f"conflicts[{conflict_index}]至少需要两个positions"
                )
            positions: list[ConflictPosition] = []
            for position_index, position in enumerate(positions_value):
                field = f"conflicts[{conflict_index}].positions[{position_index}]"
                if not isinstance(position, dict) or set(position) != {"statement", "citations"}:
                    raise AnswerValidationError("invalid_position", f"{field}字段非法")
                statement = self._nonempty_string(position["statement"], f"{field}.statement")
                labels = self._string_tuple(position["citations"], f"{field}.citations")
                self._require_unique(labels, f"{field}.citations")
                self._validate_labels(labels, registry, f"{field}.citations")
                if not set(labels).issubset(top_level_citations):
                    raise AnswerValidationError(
                        "conflict_citation_mismatch", f"{field}引用必须包含在顶层citations中"
                    )
                positions.append(ConflictPosition(statement, labels))
            parsed.append(ConflictRecord(topic, tuple(positions)))
        return tuple(parsed)

    @staticmethod
    def _nonempty_string(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AnswerValidationError("invalid_string", f"{field}必须是非空字符串")
        return value.strip()

    @classmethod
    def _string_tuple(
        cls, value: Any, field: str, *, allow_empty: bool = False
    ) -> tuple[str, ...]:
        if not isinstance(value, list) or (not allow_empty and not value):
            raise AnswerValidationError("invalid_array", f"{field}必须是字符串数组")
        result: list[str] = []
        for index, item in enumerate(value):
            result.append(cls._nonempty_string(item, f"{field}[{index}]"))
        return tuple(result)

    @staticmethod
    def _require_unique(values: tuple[str, ...], field: str) -> None:
        if len(values) != len(set(values)):
            raise AnswerValidationError("duplicate_values", f"{field}不允许重复")

    @staticmethod
    def _validate_labels(
        labels: tuple[str, ...], registry: CitationRegistry, field: str
    ) -> None:
        invalid = [label for label in labels if label not in registry]
        if invalid:
            raise AnswerValidationError(
                "unknown_citation", f"{field}包含本次证据白名单之外的编号：{invalid}"
            )
