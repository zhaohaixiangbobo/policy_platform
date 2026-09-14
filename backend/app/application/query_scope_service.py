"""文件说明：统一解析制度访问权限、用户选择、状态范围和当前可查询索引。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from app.application.auth_service import Principal
from knowledge.catalog import KnowledgeCatalogService, QueryableIndexSnapshot


@dataclass(frozen=True, slots=True)
class DocumentAccessDecision:
    """用户可访问制度集合；UNRESTRICTED与空集合具有不同业务语义。"""

    mode: Literal["UNRESTRICTED", "RESTRICTED"]
    document_ids: frozenset[int]
    policy_version: str

    def allows(self, document_id: int) -> bool:
        return self.mode == "UNRESTRICTED" or document_id in self.document_ids


class DocumentAccessResolver(Protocol):
    """未来可替换为基于4A组织、群组和Platform ACL的解析实现。"""

    def resolve(self, principal: Principal) -> DocumentAccessDecision: ...


class OpenDocumentAccessResolver:
    """当前阶段默认允许具备制度读取权限的用户访问全部正式制度。"""

    def resolve(self, principal: Principal) -> DocumentAccessDecision:
        if "knowledge.document.read" not in principal.permissions:
            return DocumentAccessDecision(
                mode="RESTRICTED",
                document_ids=frozenset(),
                policy_version="document_access_open_v1",
            )
        return DocumentAccessDecision(
            mode="UNRESTRICTED",
            document_ids=frozenset(),
            policy_version="document_access_open_v1",
        )


@dataclass(frozen=True, slots=True)
class ResolvedQueryScope:
    """Platform传给RAG并用于Citation复核的不可变查询范围。"""

    user_selection_mode: Literal["ALL", "SELECTED"]
    rag_document_scope_mode: Literal["ALL", "SELECTED"]
    document_ids: tuple[int, ...]
    query_scope: Literal["CURRENT", "HISTORICAL"]
    index_run_id: int
    access_policy_version: str
    scope_hash: str


@dataclass(frozen=True, slots=True)
class QueryScopeCapabilities:
    """前端只依赖计数判断状态范围是否真实可查询。"""

    index_run_id: int
    current_document_count: int
    historical_document_count: int


class QueryScopeResolutionError(RuntimeError):
    """查询范围无法安全解析时返回稳定业务错误。"""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class QueryScopeResolver:
    """以单一入口计算用户本次能够查询的具体document_id集合。"""

    _STATUSES = {
        "CURRENT": frozenset({"effective"}),
        "HISTORICAL": frozenset({"repealed", "expired"}),
    }

    def __init__(
        self,
        catalog: KnowledgeCatalogService,
        access_resolver: DocumentAccessResolver,
    ) -> None:
        self._catalog = catalog
        self._access_resolver = access_resolver

    def capabilities(self, principal: Principal) -> QueryScopeCapabilities:
        snapshot = self._snapshot()
        access = self._access_resolver.resolve(principal)
        visible = [item for item in snapshot.documents if access.allows(item.id)]
        return QueryScopeCapabilities(
            index_run_id=snapshot.index_run_id,
            current_document_count=sum(item.status == "effective" for item in visible),
            historical_document_count=sum(
                item.status in {"repealed", "expired"} for item in visible
            ),
        )

    def resolve(
        self,
        principal: Principal,
        *,
        selection_mode: Literal["ALL", "SELECTED"],
        selected_document_ids: Sequence[int],
        query_scope: Literal["CURRENT", "HISTORICAL"],
    ) -> ResolvedQueryScope:
        snapshot = self._snapshot()
        access = self._access_resolver.resolve(principal)
        indexed = {item.id: item.status for item in snapshot.documents}
        allowed_statuses = self._STATUSES[query_scope]
        selected = tuple(sorted(set(int(value) for value in selected_document_ids)))

        if selection_mode == "SELECTED":
            unauthorized = [document_id for document_id in selected if not access.allows(document_id)]
            if unauthorized:
                raise QueryScopeResolutionError(
                    "DOCUMENT_SCOPE_FORBIDDEN",
                    "选择范围中包含当前用户不可访问的制度",
                    403,
                )
            unavailable = [document_id for document_id in selected if document_id not in indexed]
            if unavailable:
                raise QueryScopeResolutionError(
                    "DOCUMENT_NOT_QUERYABLE",
                    "选择范围中包含尚未进入当前正式索引的制度",
                    409,
                )
            wrong_status = [
                document_id
                for document_id in selected
                if indexed[document_id] not in allowed_statuses
            ]
            if wrong_status:
                raise QueryScopeResolutionError(
                    "DOCUMENT_SCOPE_STATUS_MISMATCH",
                    "选择的制度版本与当前检索范围不一致",
                    409,
                )
            document_ids = selected
            rag_mode: Literal["ALL", "SELECTED"] = "SELECTED"
        else:
            document_ids = tuple(
                sorted(
                    document_id
                    for document_id, status in indexed.items()
                    if status in allowed_statuses and access.allows(document_id)
                )
            )
            rag_mode = "ALL" if access.mode == "UNRESTRICTED" else "SELECTED"

        if not document_ids:
            raise QueryScopeResolutionError(
                "NO_QUERYABLE_DOCUMENTS",
                "当前范围内没有可查询的正式制度",
                409,
            )

        scope_payload = {
            "access_policy_version": access.policy_version,
            "document_ids": document_ids,
            "index_run_id": snapshot.index_run_id,
            "query_scope": query_scope,
            "rag_document_scope_mode": rag_mode,
            "user_selection_mode": selection_mode,
        }
        scope_hash = hashlib.sha256(
            json.dumps(
                scope_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ResolvedQueryScope(
            user_selection_mode=selection_mode,
            rag_document_scope_mode=rag_mode,
            document_ids=document_ids,
            query_scope=query_scope,
            index_run_id=snapshot.index_run_id,
            access_policy_version=access.policy_version,
            scope_hash=scope_hash,
        )

    def _snapshot(self) -> QueryableIndexSnapshot:
        """把知识库的底层缺失状态转换成稳定的平台业务错误。"""

        try:
            return self._catalog.queryable_index_snapshot()
        except RuntimeError as exc:
            raise QueryScopeResolutionError(
                "QUERY_INDEX_UNAVAILABLE",
                "当前没有可查询的正式索引，请联系管理员完成发布",
                503,
            ) from exc
