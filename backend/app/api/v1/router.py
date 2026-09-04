"""文件说明：汇总Platform API v1路由。"""

from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.diagnostics import router as diagnostics_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(diagnostics_router)
