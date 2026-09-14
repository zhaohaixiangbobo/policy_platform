"""文件说明：验证查询范围按权限、用户选择、制度状态和active索引严格求交集。"""

import pytest

from app.application.auth_service import Principal
from app.application.query_scope_service import (
    DocumentAccessDecision,
    QueryScopeResolutionError,
    QueryScopeResolver,
)
from knowledge.catalog import QueryableDocument, QueryableIndexSnapshot


class FakeCatalog:
    """提供包含现行与历史制度的固定active索引快照。"""

    def queryable_index_snapshot(self) -> QueryableIndexSnapshot:
        return QueryableIndexSnapshot(
            index_run_id=12,
            documents=(
                QueryableDocument(id=1, status="effective"),
                QueryableDocument(id=2, status="repealed"),
                QueryableDocument(id=3, status="effective"),
            ),
        )


class RestrictedAccessResolver:
    """模拟未来4A身份映射后的具体制度授权集合。"""

    def resolve(self, _principal: Principal) -> DocumentAccessDecision:
        return DocumentAccessDecision(
            mode="RESTRICTED",
            document_ids=frozenset({1, 2}),
            policy_version="document_acl_test_v1",
        )


def principal() -> Principal:
    return Principal(
        user_id="user-1",
        username="scope-user",
        display_name="范围测试用户",
        roles=("USER",),
        permissions=frozenset({"knowledge.document.read", "chat.write"}),
        must_change_password=False,
        auth_provider="LOCAL",
        session_id="session-1",
        csrf_token_hash="csrf",
    )


def test_all_scope_intersects_access_status_and_active_index() -> None:
    resolver = QueryScopeResolver(FakeCatalog(), RestrictedAccessResolver())  # type: ignore[arg-type]

    current = resolver.resolve(
        principal(), selection_mode="ALL", selected_document_ids=(), query_scope="CURRENT"
    )
    historical = resolver.resolve(
        principal(), selection_mode="ALL", selected_document_ids=(), query_scope="HISTORICAL"
    )

    # 受限用户即使选择ALL，也必须向RAG发送解析后的具体制度集合。
    assert current.rag_document_scope_mode == "SELECTED"
    assert current.document_ids == (1,)
    assert historical.document_ids == (2,)
    assert current.index_run_id == 12
    assert current.access_policy_version == "document_acl_test_v1"


def test_selected_scope_never_expands_or_crosses_status_boundary() -> None:
    resolver = QueryScopeResolver(FakeCatalog(), RestrictedAccessResolver())  # type: ignore[arg-type]

    selected = resolver.resolve(
        principal(),
        selection_mode="SELECTED",
        selected_document_ids=(1,),
        query_scope="CURRENT",
    )
    assert selected.rag_document_scope_mode == "SELECTED"
    assert selected.document_ids == (1,)

    with pytest.raises(QueryScopeResolutionError) as status_error:
        resolver.resolve(
            principal(),
            selection_mode="SELECTED",
            selected_document_ids=(2,),
            query_scope="CURRENT",
        )
    assert status_error.value.code == "DOCUMENT_SCOPE_STATUS_MISMATCH"

    with pytest.raises(QueryScopeResolutionError) as permission_error:
        resolver.resolve(
            principal(),
            selection_mode="SELECTED",
            selected_document_ids=(3,),
            query_scope="CURRENT",
        )
    assert permission_error.value.code == "DOCUMENT_SCOPE_FORBIDDEN"


def test_capabilities_only_count_accessible_documents() -> None:
    resolver = QueryScopeResolver(FakeCatalog(), RestrictedAccessResolver())  # type: ignore[arg-type]

    capabilities = resolver.capabilities(principal())

    assert capabilities.index_run_id == 12
    assert capabilities.current_document_count == 1
    assert capabilities.historical_document_count == 1
