"""文件说明：暴露active制度列表、详情、Node正文和受控PDF接口。"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.dependencies import get_document_service, require_permission
from app.application.document_service import (
    DocumentFileUnavailableError,
    DocumentNotFoundError,
    DocumentService,
)
from app.schemas.documents import (
    DocumentDetail,
    DocumentFacetsResponse,
    DocumentListResponse,
    DocumentNodeListResponse,
)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_permission("knowledge.document.read"))],
)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    keyword: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=80),
    query_scope: Literal["CURRENT", "HISTORICAL"] | None = None,
    issuer: str | None = Query(default=None, max_length=300),
    department: str | None = Query(default=None, max_length=300),
    publish_date_from: date | None = None,
    publish_date_to: date | None = None,
    sort_by: str = Query(
        default="updated_at",
        pattern="^(updated_at|title|document_code|issuer|publish_date|effective_date|status|responsibility_department)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    return service.list_documents(
        keyword=keyword,
        status=status,
        query_scope=query_scope,
        issuer=issuer,
        department=department,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/facets", response_model=DocumentFacetsResponse)
def list_document_facets(
    service: DocumentService = Depends(get_document_service),
) -> DocumentFacetsResponse:
    """返回制度库 Select 使用的真实候选值。"""

    return service.list_facets()


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int, service: DocumentService = Depends(get_document_service)
) -> DocumentDetail:
    try:
        return service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="制度不存在") from exc


@router.get("/{document_id}/nodes", response_model=DocumentNodeListResponse)
def list_document_nodes(
    document_id: int, service: DocumentService = Depends(get_document_service)
) -> DocumentNodeListResponse:
    try:
        return service.list_nodes(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="制度不存在") from exc


@router.get("/{document_id}/pdf", response_class=FileResponse)
def get_document_pdf(
    document_id: int, service: DocumentService = Depends(get_document_service)
) -> FileResponse:
    try:
        path = service.resolve_pdf(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="制度不存在") from exc
    except DocumentFileUnavailableError as exc:
        raise HTTPException(status_code=404, detail="制度PDF不可用") from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"document-{document_id}.pdf",
        content_disposition_type="inline",
    )
