"""文件说明：公开Platform API存活与就绪检查端点。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies import get_health_service
from app.application.health_service import HealthService
from app.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """只证明Platform API进程可响应，不探测外部依赖。"""

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        request_id=request.state.request_id,
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def ready(
    request: Request,
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    """验证Platform业务库就绪；不会调用RAG查询之外的端点。"""

    result = await service.readiness(request.state.request_id)
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
