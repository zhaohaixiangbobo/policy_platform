"""文件说明：验证质量门禁默认关闭、环境开关解析和关闭时的回答透传语义。"""

from pathlib import Path

import pytest

from knowledge.rag.answer_parser import ParsedAnswer
from knowledge.rag.citation import CitationRegistry
from knowledge.rag.models import AnswerStatus
from knowledge.rag.quality_gate import AnswerQualityGate, QualityGateStatus
from knowledge.rag.runtime import RagRuntimeSettings


def test_quality_gate_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLICY_QUALITY_GATE_ENABLED", raising=False)

    settings = RagRuntimeSettings.from_environment(db_path=Path("knowledge.db"))

    assert settings.quality_gate_enabled is False


def test_quality_gate_can_be_enabled_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_QUALITY_GATE_ENABLED", "true")

    settings = RagRuntimeSettings.from_environment(db_path=Path("knowledge.db"))

    assert settings.quality_gate_enabled is True


def test_disabled_quality_gate_skips_claim_coverage_evaluation() -> None:
    answer = ParsedAnswer(
        status=AnswerStatus.ANSWER,
        answer="已通过基础响应契约的回答。",
        citations=(),
        conflicts=(),
        warnings=(),
    )

    decision = AnswerQualityGate(enabled=False).evaluate(
        "测试问题",
        answer,
        CitationRegistry(()),
    )

    assert decision.answer is answer
    assert decision.audit.status == QualityGateStatus.NOT_REQUIRED
    assert decision.audit.semantic_verification == "DISABLED"
    assert decision.audit.reason_codes == ("quality_gate_disabled",)


def test_quality_gate_rejects_ambiguous_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_QUALITY_GATE_ENABLED", "enable")

    with pytest.raises(ValueError, match="POLICY_QUALITY_GATE_ENABLED"):
        RagRuntimeSettings.from_environment(db_path=Path("knowledge.db"))
