"""文件说明：将知识模块active目录转换为Platform制度公开响应。"""

from datetime import date
from pathlib import Path

from knowledge.catalog import (
    CatalogDocument,
    CatalogDocumentNotFoundError,
    CatalogFileUnavailableError,
    KnowledgeCatalogService,
)

from app.schemas.documents import (
    DocumentDetail,
    DocumentFacetsResponse,
    DocumentListResponse,
    DocumentNode,
    DocumentNodeListResponse,
    DocumentSummary,
)
from app.application.auth_service import Principal
from app.application.query_scope_service import DocumentAccessResolver


class DocumentNotFoundError(LookupError):
    """active制度不存在。"""


class DocumentFileUnavailableError(LookupError):
    """制度没有可安全访问的active PDF。"""


def _summary(document: CatalogDocument) -> DocumentSummary:
    return DocumentSummary.model_validate(document)


class DocumentService:
    """只通过知识目录服务读取active制度，不维护重复投影。"""

    def __init__(
        self,
        catalog: KnowledgeCatalogService,
        access_resolver: DocumentAccessResolver,
        principal: Principal,
    ) -> None:
        self._catalog = catalog
        self._access_resolver = access_resolver
        self._principal = principal

    def _allowed_document_ids(self) -> tuple[int, ...] | None:
        decision = self._access_resolver.resolve(self._principal)
        return None if decision.mode == "UNRESTRICTED" else tuple(decision.document_ids)

    def _ensure_access(self, document_id: int) -> None:
        if not self._access_resolver.resolve(self._principal).allows(document_id):
            raise DocumentNotFoundError

    def list_documents(
        self,
        *,
        keyword: str | None,
        status: str | None,
        query_scope: str | None,
        issuer: str | None,
        department: str | None,
        publish_date_from: date | None,
        publish_date_to: date | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> DocumentListResponse:
        documents, total = self._catalog.list_documents(
            keyword=keyword,
            status=status,
            query_scope=query_scope,
            issuer=issuer,
            department=department,
            publish_date_from=publish_date_from.isoformat() if publish_date_from else None,
            publish_date_to=publish_date_to.isoformat() if publish_date_to else None,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            allowed_document_ids=self._allowed_document_ids(),
        )
        return DocumentListResponse(
            items=[_summary(item) for item in documents],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_facets(self) -> DocumentFacetsResponse:
        return DocumentFacetsResponse.model_validate(
            self._catalog.list_facets(self._allowed_document_ids())
        )

    def get_document(self, document_id: int) -> DocumentDetail:
        self._ensure_access(document_id)
        try:
            return DocumentDetail.model_validate(self._catalog.get_document(document_id))
        except CatalogDocumentNotFoundError as exc:
            raise DocumentNotFoundError from exc

    def list_nodes(self, document_id: int) -> DocumentNodeListResponse:
        self._ensure_access(document_id)
        try:
            parse_run_id, nodes = self._catalog.list_nodes(document_id)
        except CatalogDocumentNotFoundError as exc:
            raise DocumentNotFoundError from exc
        return DocumentNodeListResponse(
            document_id=document_id,
            active_parse_run_id=parse_run_id,
            items=[DocumentNode.model_validate(item) for item in nodes],
        )

    def resolve_pdf(self, document_id: int) -> Path:
        self._ensure_access(document_id)
        try:
            return self._catalog.resolve_pdf(document_id)
        except CatalogDocumentNotFoundError as exc:
            raise DocumentNotFoundError from exc
        except CatalogFileUnavailableError as exc:
            raise DocumentFileUnavailableError from exc
