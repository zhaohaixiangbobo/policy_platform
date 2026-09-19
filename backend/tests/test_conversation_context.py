"""文件说明：验证S3确定性补全、用户条件来源、范围隔离和失败重试；不调用真实模型。"""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.application.conversation_context import explicit_values, resolve_context
from app.application.chat_service import ChatService, ChatResourceNotFoundError
from app.infrastructure.db.models import UserAccount, ChatMessage
from knowledge.service import KnowledgeServiceError
from tests.test_chat_integration import make_session, principal, FakeQueryScopeResolver, response


@pytest.mark.parametrize("text,expected", [
    ("一类，个人一等奖", {"competition_category": "一类", "recipient_type": "个人", "award_level": "一等奖"}),
    ("补充信息：一类，个人一等奖", {"competition_category": "一类", "recipient_type": "个人", "award_level": "一等奖"}),
    ("一等奖", {"award_level": "一等奖"}),
    ("改为二类", {"competition_category": "二类"}),
    ("部门：财务部", {"department": "财务部"}),
    ("日期：2026-09-19", {"applicable_date": "2026-09-19"}),
    ("日期：2026-02-30", {}), ("一类或二类", {}),
    ("不是一类", {}), ("一类，另外住房补贴多少", {}), ("都行", {}),
])
def test_explicit_values(text, expected):
    assert explicit_values(text) == expected


class RecordingClient:
    def __init__(self):
        self.queries = []
        self.fail = False

    async def query(self, question, *args):
        self.queries.append((question, args))
        if self.fail:
            raise KnowledgeServiceError(code="TEST", message="测试失败", request_id="test", retryable=True, http_status=503)
        return response("ANSWER").model_copy(update={
            "contract_version": "rag_api_v1_2", "answerability": "PARTIAL", "reason_code": "MISSING_USER_CONTEXT",
            "missing_fields": ["competition_category", "award_level", "recipient_type"],
            "clarification_question": "请补充类别、等级和个人或团队。",
        })


def setup_service():
    session = make_session()
    user = UserAccount(username="s3", display_name="S3", must_change_password=False)
    session.add(user)
    session.commit()
    client = RecordingClient()
    service = ChatService(session, client, principal(user), FakeQueryScopeResolver())
    return session, user, client, service


def test_multi_turn_provenance_correction_topic_and_scope_reset():
    session, user, client, service = setup_service()
    chat = service.create_session("S3")
    def send(text, **kw):
        return asyncio.run(service.send_message(chat.id, text, "s3", **kw))
    first = send("行业竞赛一等奖多少钱")
    assert first.assistant_message.rewrite_used is False
    second = send("一类")
    assert second.user_message.content == "一类"
    assert "行业竞赛一等奖多少钱" in client.queries[-1][0]
    assert second.assistant_message.rewrite_used is True
    third = send("个人一等奖")
    context = third.assistant_message.conversation_context.model_dump()
    assert context["root_message_id"] == first.user_message.id
    assert context["confirmed"]["competition_category"]["source_message_id"] == second.user_message.id
    assert context["confirmed"]["award_level"]["source_message_id"] == third.user_message.id
    fourth = send("改为二类")
    assert fourth.assistant_message.conversation_context.confirmed["competition_category"].value == "二类"
    assert "竞赛类别：一类" not in client.queries[-1][0]
    # 用户转入新话题后，旧确认条件不继续继承。
    changed = send("住房补贴如何申请")
    assert changed.assistant_message.rewrite_used is False
    assert changed.assistant_message.conversation_context.confirmed == {}
    scoped = send("一类", document_selection_mode="SELECTED", selected_document_ids=(1,))
    assert scoped.assistant_message.rewrite_used is False
    assert client.queries[-1][1][-1] == (1,)
    assert len(client.queries) == 6
    session.close()


def test_scope_identity_index_and_access_change_reset():
    session, user, client, service = setup_service()
    chat = service.create_session("S3")
    asyncio.run(service.send_message(chat.id, "奖金多少", "first"))
    rows = session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat.id).order_by(ChatMessage.created_at)).all()
    scope = FakeQueryScopeResolver().resolve(principal(user), selection_mode="ALL", selected_document_ids=(), query_scope="CURRENT")
    for changed in (replace(scope, index_run_id=4), replace(scope, scope_hash="changed"), replace(scope, query_scope="HISTORICAL"), replace(scope, access_policy_version="new")):
        query, state = resolve_context("一类", "new", rows[-1], rows[0], changed, ())
        assert query == "一类"
        assert state["confirmed"] == {}
    another = UserAccount(username="another", display_name="另一个用户", must_change_password=False)
    session.add(another)
    session.commit()
    other = ChatService(session, client, principal(another), FakeQueryScopeResolver())
    with pytest.raises(ChatResourceNotFoundError):
        asyncio.run(other.send_message(chat.id, "一类", "other"))
    assert len(client.queries) == 1
    session.close()


def test_failure_does_not_commit_confirmations():
    session, user, client, service = setup_service()
    chat = service.create_session("S3")
    asyncio.run(service.send_message(chat.id, "奖金多少", "first"))
    client.fail = True
    with pytest.raises(KnowledgeServiceError):
        asyncio.run(service.send_message(chat.id, "二类", "failed"))
    client.fail = False
    result = asyncio.run(service.send_message(chat.id, "一类", "retry"))
    assert "竞赛类别：二类" not in result.assistant_message.retrieval_query
    assert len(service.list_messages(chat.id)) == 4
    session.close()
