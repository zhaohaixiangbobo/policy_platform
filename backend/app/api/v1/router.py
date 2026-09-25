"""文件说明：汇总Platform API v1路由。"""

from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.diagnostics import router as diagnostics_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.learning import router as learning_router
from app.config import get_settings
from fastapi import Depends
from app.api.dependencies import get_current_principal

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(diagnostics_router)
api_router.include_router(learning_router)


@api_router.get("/features", tags=["features"])
def features(_principal=Depends(get_current_principal)):
    """公开已登录用户可见的功能开关；关闭模块时无需访问其缓存表。"""
    settings = get_settings()
    return {"learning_assessment": settings.learning_assessment_enabled and "knowledge.document.read" in _principal.permissions,
            "learning_max_questions": settings.learning_assessment_max_questions,
            "learning_ttl_hours": settings.learning_assessment_ttl_hours}
