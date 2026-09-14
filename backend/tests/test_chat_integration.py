"""文件说明：验证公开 RAG 响应三状态、查询范围和 Citation 快照写入 Platform 数据库。"""

import asyncio

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.chat_service import ChatService
from app.application.auth_service import Principal
from app.application.query_scope_service import ResolvedQueryScope
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import UserAccount
from knowledge.contracts import QueryResponse


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def response(status: str, index_run_id: int = 3) -> QueryResponse:
    answerable = status == "ANSWER"
    citations = []
    conflicts = []
    if status != "INSUFFICIENT_EVIDENCE":
        citations = [
            {
                "citation_version": "citation_v1",
                "evidence_uid_version": "evidence_uid_v1",
                "label": "[1]",
                "evidence_uid": "evidence-1",
                "document_id": 1,
                "primary_node_id": 2500,
                "parse_run_id": 38,
                "chunk_run_id": 11,
                "index_run_id": index_run_id,
                "chunk_id": 1,
                "document_title": "测试制度",
                "document_code": "TEST-001",
                "document_status": "effective",
                "source_reference": "source_documents/test.docx",
                "path_text": "第一条",
                "page_start": 1,
                "page_end": 1,
                "quote": "测试依据",
                "truncated": False,
                "snapshot_hash": f"sha256:{'a' * 64}",
            }
        ]
    if status == "CONFLICT":
        conflicts = [
            {
                "topic": "测试事项",
                "positions": [{"statement": "存在不同规定", "citations": ["[1]"]}],
            }
        ]
    return QueryResponse.model_validate(
        {
            "contract_version": "rag_api_v1_1",
            "request_id": f"knowledge-{status}",
            "status": status,
            "answerable": answerable,
            "answer": "测试回答" if answerable else "现有证据不足或存在冲突。",
            "citations": citations,
            "conflicts": conflicts,
            "warnings": [],
            "retrieval": {
                "index_run_id": index_run_id,
                "dense_count": 20,
                "rerank_count": 8,
                "rerank_returned_count": 1,
            },
            "quality_gate": {
                "version": "answer_quality_gate_v2",
                "status": "PASS" if answerable else "NOT_REQUIRED",
                "semantic_verification": "passed" if answerable else "not_required",
                "checked_claim_count": 1 if answerable else 0,
                "reason_codes": [],
                "verifier_schema_version": "verifier_schema_v1",
                "verifier_schema_hash": "controlled",
                "verifier_prompt_hash": "controlled",
            },
            "provenance": {
                "rag_version": "rag-test",
                "generator_model": "test-model",
                "generator_revision": "r1",
                "prompt_version": "p1",
                "prompt_schema_version": "ps1",
                "retrieval_config_hash": "retrieval",
                "context_config_hash": "context",
                "rewrite_used": False,
            },
            "latency_ms": {"total": 1, "retrieval": 0, "context": 0, "llm": 1},
        }
    )


class FakeKnowledgeService:
    def __init__(self, status: str, index_run_id: int = 3) -> None:
        self.status = status
        self.index_run_id = index_run_id

    async def query(
        self,
        query: str,
        request_id: str,
        query_scope: str = "CURRENT",
        document_scope_mode: str = "ALL",
        document_ids: tuple[int, ...] = (),
    ) -> QueryResponse:
        return response(self.status, self.index_run_id)


class FakeQueryScopeResolver:
    def resolve(
        self,
        principal: Principal,
        *,
        selection_mode: str,
        selected_document_ids: tuple[int, ...],
        query_scope: str,
    ) -> ResolvedQueryScope:
        document_ids = selected_document_ids if selection_mode == "SELECTED" else (1,)
        return ResolvedQueryScope(
            user_selection_mode=selection_mode,  # type: ignore[arg-type]
            rag_document_scope_mode="SELECTED" if selection_mode == "SELECTED" else "ALL",
            document_ids=document_ids,
            query_scope=query_scope,  # type: ignore[arg-type]
            index_run_id=3,
            access_policy_version="test-access-v1",
            scope_hash="a" * 64,
        )


def principal(user: UserAccount) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=("USER",),
        permissions=frozenset({"chat.read", "chat.write", "knowledge.document.read"}),
        must_change_password=False,
        auth_provider="LOCAL",
        session_id="test-session",
        csrf_token_hash="test-csrf",
    )


def test_chat_persists_three_statuses_and_citation_snapshot() -> None:
    session = make_session()
    user = UserAccount(username="chat-test", display_name="聊天测试用户", must_change_password=False)
    session.add(user)
    session.commit()
    observed = []
    for status in ("ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICT"):
        service = ChatService(
            session,
            FakeKnowledgeService(status),  # type: ignore[arg-type]
            principal(user),
            FakeQueryScopeResolver(),  # type: ignore[arg-type]
        )
        chat_session = service.create_session(status)
        turn = asyncio.run(service.send_message(chat_session.id, "测试问题", status))
        observed.append(turn.assistant_message.answer_status)
        assert turn.assistant_message.quality_gate is not None
        assert turn.assistant_message.quality_gate.version == "answer_quality_gate_v2"
        assert turn.user_message.query_scope == "CURRENT"
        assert turn.assistant_message.query_scope == "CURRENT"
    assert observed == ["ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICT"]
    session.close()


def test_chat_rejects_citation_outside_requested_scope() -> None:
    session = make_session()
    user = UserAccount(username="scope-test", display_name="范围测试用户", must_change_password=False)
    session.add(user)
    session.commit()
    service = ChatService(
        session,
        FakeKnowledgeService("ANSWER"),  # type: ignore[arg-type]
        principal(user),
        FakeQueryScopeResolver(),  # type: ignore[arg-type]
    )
    chat_session = service.create_session("历史查询")

    from knowledge.service import KnowledgeServiceError

    try:
        asyncio.run(service.send_message(chat_session.id, "历史规定", "scope", "HISTORICAL"))
        raise AssertionError("应拒绝现行制度 Citation")
    except KnowledgeServiceError as exc:
        assert exc.code == "RAG_SCOPE_MISMATCH"
    assert service.list_messages(chat_session.id) == []
    session.close()


def test_chat_persists_explicit_selected_document_scope() -> None:
    session = make_session()
    user = UserAccount(username="selected-test", display_name="指定制度用户", must_change_password=False)
    session.add(user)
    session.commit()
    service = ChatService(
        session,
        FakeKnowledgeService("ANSWER"),  # type: ignore[arg-type]
        principal(user),
        FakeQueryScopeResolver(),  # type: ignore[arg-type]
    )
    chat_session = service.create_session("指定制度")

    turn = asyncio.run(
        service.send_message(
            chat_session.id,
            "只查询制度1",
            "scope-selected",
            "CURRENT",
            "SELECTED",
            (1,),
        )
    )

    assert turn.user_message.document_selection_mode == "SELECTED"
    assert turn.user_message.selected_document_ids == [1]
    assert turn.assistant_message.access_scope_count == 1
    session.close()


def test_chat_rejects_response_from_a_switched_index_snapshot() -> None:
    session = make_session()
    user = UserAccount(username="index-test", display_name="索引切换用户", must_change_password=False)
    session.add(user)
    session.commit()
    service = ChatService(
        session,
        FakeKnowledgeService("ANSWER", index_run_id=4),  # type: ignore[arg-type]
        principal(user),
        FakeQueryScopeResolver(),  # type: ignore[arg-type]
    )
    chat_session = service.create_session("索引切换")

    from knowledge.service import KnowledgeServiceError

    with pytest.raises(KnowledgeServiceError) as error:
        asyncio.run(service.send_message(chat_session.id, "测试索引切换", "index-scope"))
    assert error.value.code == "RAG_INDEX_SCOPE_MISMATCH"
    assert error.value.retryable is True
    assert service.list_messages(chat_session.id) == []
    session.close()
