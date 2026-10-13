"""文件说明：资料v3自然问句、原文片段与聊天分流最小隔离测试，不调用真实模型。"""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

from app.application.material_search import SupportMaterialSearchService, material_intent
from app.application.chat_service import ChatService
from app.infrastructure.db.models import UserAccount
from tests.test_chat_integration import make_session, principal, FakeQueryScopeResolver


def test_natural_query_and_literal_excerpt():
    search = SupportMaterialSearchService()
    fields = {"title": "违规宴请问题", "problem_types": ["违反中央八项规定精神"],
              "original": "与主题无关的开头。违反中央八项规定精神，接受宴请。"}
    for query in ["有违反八项规定的案例吗", "八项规定 典型案例", "违反了八项规定会如何处理"]:
        result = search.match(query, fields, "CASE")
        assert result["score"] >= 6
        assert result["match_excerpt"] in fields["original"]
        assert result["match_reason"]
    assert search.score("公款吃喝", fields, "CASE", recommend=True) == 0
    assert search.score("处分", fields, "CASE", recommend=True) == 0
    duplicate = fields | {"title": "违反中央八项规定精神案例"}
    assert search.score("八项规定", duplicate, "CASE", recommend=True) == search.score("八项规定", fields, "CASE", recommend=True)


def test_material_intent_boundaries():
    assert material_intent("有违反八项规定的案例吗") == "CASE"
    assert material_intent("信访举报流程图") == "IMAGE"
    for query in ["结合案例解释八项规定", "公款吃喝如何处理", "信访举报流程是什么"]:
        assert material_intent(query) is None


def test_chat_material_route_permissions_and_followup(monkeypatch):
    with make_session() as session:
        user = UserAccount(username="materials-v3", display_name="测试", must_change_password=False)
        session.add(user); session.commit()
        identity = replace(principal(user), permissions=principal(user).permissions | {"material.read"})
        # 没有query方法：纯资料请求误调用RAG将直接失败。
        service = ChatService(session, SimpleNamespace(), identity, FakeQueryScopeResolver())
        chat = service.create_session("资料测试")
        first = asyncio.run(service.send_message(chat.id, "八项规定典型案例", "m1"))
        assert first.assistant_message.reason_code == "MATERIAL_SEARCH"
        assert first.assistant_message.citations == []
        assert "未匹配" in first.assistant_message.content
        followup = asyncio.run(service.send_message(chat.id, "还有相关案例吗", "m2"))
        assert "八项规定" in followup.assistant_message.retrieval_query
        changed = asyncio.run(service.send_message(chat.id, "信访举报流程图", "m3"))
        assert "八项规定" not in changed.assistant_message.retrieval_query
        scoped = asyncio.run(service.send_message(chat.id, "八项规定案例", "m4", document_selection_mode="SELECTED", selected_document_ids=(1,)))
        assert "尚未建立" in scoped.assistant_message.content
        denied = ChatService(session, SimpleNamespace(), principal(user), FakeQueryScopeResolver())
        turn = asyncio.run(denied.send_message(chat.id, "八项规定案例", "m5"))
        assert "没有" in turn.assistant_message.content
        monkeypatch.setattr("app.application.chat_service.MaterialService.recommend", lambda self, query, kind=None: {"items": [{"id": "found"}]})
        found = asyncio.run(service.send_message(chat.id, "八项规定案例", "m6"))
        assert "找到" in found.assistant_message.content
        assert found.assistant_message.engine_request_id is None
