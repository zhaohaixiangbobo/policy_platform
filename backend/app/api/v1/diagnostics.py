"""文件说明：暴露默认关闭且仅本机可用的公开快照诊断筛选接口。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_diagnostic_service, require_permission
from app.application.chat_service import ChatResourceNotFoundError
from app.application.diagnostic_service import DiagnosticService
from app.config import get_settings
from app.schemas.diagnostics import DiagnosticListResponse, DiagnosticRequestDetail

router = APIRouter(
    prefix="/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(require_permission("system.audit.read"))],
)


def _guard(request: Request) -> None:
    settings = get_settings()
    client_host = request.client.host if request.client else ""
    if not settings.rag_diagnostics_enabled or client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=404, detail="诊断功能未启用")


@router.get("/requests", response_model=DiagnosticListResponse)
def list_diagnostics(
    request: Request,
    request_id: str | None = Query(default=None, max_length=128),
    keyword: str | None = Query(default=None, max_length=200),
    answer_status: str | None = Query(
        default=None, pattern="^(ANSWER|INSUFFICIENT_EVIDENCE|CONFLICT)$"
    ),
    quality_gate_status: str | None = Query(
        default=None, pattern="^(PASS|DOWNGRADED|NOT_REQUIRED)$"
    ),
    has_down_feedback: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: DiagnosticService = Depends(get_diagnostic_service),
) -> DiagnosticListResponse:
    _guard(request)
    return service.list_requests(
        request_id=request_id,
        keyword=keyword,
        answer_status=answer_status,
        quality_gate_status=quality_gate_status,
        has_down_feedback=has_down_feedback,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/requests/{request_id}", response_model=DiagnosticRequestDetail)
def get_diagnostic(
    request_id: str,
    request: Request,
    service: DiagnosticService = Depends(get_diagnostic_service),
) -> DiagnosticRequestDetail:
    _guard(request)
    try:
        return service.get_request(request_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="诊断记录不存在") from exc
