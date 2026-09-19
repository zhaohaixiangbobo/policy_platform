"""文件说明：验证S2答案契约、单次生成、门禁覆盖和历史快照兼容，无真实模型调用。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from knowledge.rag.answer_parser import AnswerParser, AnswerValidationError
from knowledge.rag.config import ContextBuilderConfig, GenerationConfig, GeneratorContract
from knowledge.rag.generator import GeneratorResponse
from knowledge.rag.models import ContextBundle, EvidenceRecord
from knowledge.rag.pipeline import RagPipeline
from knowledge.rag.quality_gate import AnswerQualityGate
from knowledge.contracts import public_query_response
from app.application.chat_service import ChatService
from app.infrastructure.db.models import UserAccount
from tests.test_chat_integration import make_session, principal, FakeQueryScopeResolver, response


def payload(**updates):
    value = dict(status="ANSWER", answerability="PARTIAL", reason_code="MISSING_USER_CONTEXT",
                 answer="若为一类，奖励不超过10000元。[E1]", citations=["E1"], conflicts=[], warnings=[],
                 missing_fields=["competition_category"], clarification_question="请提供竞赛类别。")
    value.update(updates)
    return value


def parse(**updates):
    return AnswerParser().parse(json.dumps(payload(**updates)), {"E1", "E2"})


@pytest.mark.parametrize("updates", [
    {"answerability": "NONE"}, {"reason_code": "COMPLETE"},
    {"missing_fields": []}, {"missing_fields": ["invented"]},
    {"clarification_question": None}, {"reason_code": "SUPPORT_CHECK_FAILED"},
    {"answer": "奖励10000元。[E9]", "citations": ["E9"]},
    {"citations": []},
])
def test_invalid_metadata_and_citations(updates):
    with pytest.raises(AnswerValidationError):
        parse(**updates)


def test_valid_status_combinations():
    assert parse().answerability == "PARTIAL"
    assert parse(status="INSUFFICIENT_EVIDENCE").answerability == "PARTIAL"
    assert parse(answerability="SUFFICIENT", reason_code="COMPLETE", missing_fields=[], clarification_question=None).answerable
    assert parse(reason_code="POLICY_LIMIT_ONLY", missing_fields=[], clarification_question=None).reason_code == "POLICY_LIMIT_ONLY"
    conflict = parse(status="CONFLICT", reason_code="CONFLICTING_EVIDENCE", missing_fields=[], clarification_question=None,
                     answer="期限分别为5日[E1]和10日[E2]。", citations=["E1", "E2"],
                     conflicts=[{"topic": "期限", "positions": [{"statement": "5日", "citations": ["E1"]}, {"statement": "10日", "citations": ["E2"]}]}])
    assert conflict.status == "CONFLICT"


def test_partial_gate_checks_facts_but_not_separate_question():
    gate = AnswerQualityGate(enabled=True)
    assert gate.evaluate("多少钱", parse(status="INSUFFICIENT_EVIDENCE"), {"E1"}).audit.checked_claim_count == 1
    result = gate.evaluate("多少钱", parse(answer="若为一类，奖励不超过10000元。[E1]保证发足。"), {"E1"})
    assert result.answer.reason_code == "SUPPORT_CHECK_FAILED"
    assert result.answer.answerability == "NONE"
    assert result.answer.clarification_question is None
    calls = []
    def verify(*args):
        calls.append(args)
        raise RuntimeError("模拟语义服务故障")
    decision = AnswerQualityGate(SimpleNamespace(verify=verify), enabled=True).evaluate("多少钱", parse(), {"E1"})
    assert len(calls) == 1
    assert decision.answer.reason_code == "SUPPORT_CHECK_FAILED"
    assert AnswerQualityGate().evaluate("多少钱", parse(), {"E1"}).answer == parse()


@pytest.mark.parametrize("filename,columns", [
    ("0009_chat_answerability.py", ("answerability", "reason_code", "missing_fields_json", "clarification_question")),
    ("0010_conversation_context.py", ("retrieval_query", "rewrite_strategy_version", "conversation_context_json")),
])
def test_additive_migration_preserves_old_answer(monkeypatch, filename, columns):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location("s2_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE chat_message (id INTEGER PRIMARY KEY, content TEXT)"))
        connection.execute(text("INSERT INTO chat_message VALUES (1, '原回答')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        row = connection.execute(text("SELECT * FROM chat_message")).mappings().one()
        assert row["content"] == "原回答"
        assert all(row[key] is None for key in columns)
    engine.dispose()


def evidence():
    return EvidenceRecord(citation_label="E1", evidence_uid="e1", index_run_id=3, chunk_run_id=2,
        parse_run_id=1, chunk_id=1, chunk_key="c1", document_id=1, document_title="奖励办法",
        document_code=None, document_status="effective", source_reference="test.docx", path_text="第四条",
        page_start=1, page_end=1, primary_node_id=1, source_nodes=(), raw_text_hash="a"*64,
        dense_rank=1, dense_score=1.0, rerank_rank=1, rerank_score=1.0,
        text="若为一类，奖励不超过10000元。", estimated_tokens=20, group_key="g1")


@pytest.mark.parametrize("has_evidence,invalid", [(False, False), (True, False), (True, True)])
def test_pipeline_single_generation_or_none_shortcut(has_evidence, invalid):
    calls = []
    config = ContextBuilderConfig()
    bundle = ContextBundle("多少钱", 3, "retrieval", config.config_hash, config.token_estimator_version,
                           8000, 20, (evidence(),) if has_evidence else (), (), (), "奖励证据")
    def generate(messages):
        calls.append(messages)
        return GeneratorResponse(json.dumps(payload(answerability="NONE") if invalid else payload()), "model", "stop", {}, 0.01, 1, False)
    pipeline = RagPipeline(
        SimpleNamespace(search=lambda *a, **k: [], retrieval_config_hash="retrieval", config=None),
        SimpleNamespace(build=lambda *a, **k: bundle, config=config),
        SimpleNamespace(generate=generate, config=GenerationConfig(), contract=GeneratorContract()),
    )
    result = public_query_response(pipeline.query("多少钱"), "request")
    assert len(calls) == (2 if invalid else int(has_evidence))
    assert result.contract_version == "rag_api_v1_2"
    if invalid:
        assert result.answerability == "NONE"
        assert result.reason_code == "ANSWER_VALIDATION_FAILED"
        assert result.citations == []
        assert "10000" not in result.answer
        return
    assert result.answerability == ("PARTIAL" if has_evidence else "NONE")
    assert result.reason_code == ("MISSING_USER_CONTEXT" if has_evidence else "NO_RELEVANT_EVIDENCE")


def test_chat_new_metadata_and_legacy_null_roundtrip():
    session = make_session()
    user = UserAccount(username="s2", display_name="S2测试", must_change_password=False)
    session.add(user)
    session.commit()
    for modern in (False, True):
        value = response("ANSWER")
        if modern:
            value = value.model_copy(update=dict(contract_version="rag_api_v1_2", answerability="PARTIAL",
                reason_code="MISSING_USER_CONTEXT", missing_fields=["competition_category"], clarification_question="请提供类别。"))
        async def query(*args, **kwargs):
            return value
        service = ChatService(session, SimpleNamespace(query=query), principal(user), FakeQueryScopeResolver())
        chat = service.create_session("S2")
        asyncio.run(service.send_message(chat.id, "多少钱", "s2"))
        session.expire_all()
        answer = service.list_messages(chat.id)[-1]
        assert answer.answerability == ("PARTIAL" if modern else None)
        assert answer.missing_fields == (["competition_category"] if modern else None)
        assert answer.clarification_question == ("请提供类别。" if modern else None)
    session.close()
