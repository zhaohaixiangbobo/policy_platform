"""文件说明：创建统一FastAPI应用并管理独立 RAG API 客户端生命周期。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.middleware import RequestIdMiddleware
from app.infrastructure.rag_api_client import RagApiClient, RagApiClientError
from knowledge.catalog import KnowledgeCatalogService
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from app.application.auth_service import ensure_auth_baseline
from app.infrastructure.db.session import get_session_factory


@asynccontextmanager
async def lifespan(application: FastAPI):
    """装配管理目录和 RAG HTTP 客户端，停止时统一释放连接。"""

    settings = get_settings()
    paths = KnowledgePaths(settings.knowledge_data_root)
    # 空库首次启动也必须得到稳定目录和独立索引配置，不依赖迁移测试数据。
    KnowledgeManagementService(paths).initialize_empty_baseline()
    with get_session_factory()() as session:
        ensure_auth_baseline(session)
    rag_client = RagApiClient(
        settings.rag_api_url,
        connect_timeout_seconds=settings.rag_api_connect_timeout_seconds,
    )
    application.state.knowledge_catalog = KnowledgeCatalogService(paths)
    application.state.rag_api_client = rag_client
    try:
        yield
    finally:
        await rag_client.close()


def create_app() -> FastAPI:
    """创建可供生产启动和测试独立复用的应用实例。"""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(RagApiClientError)
    async def handle_rag_api_client_error(
        request: Request, exc: RagApiClientError
    ) -> JSONResponse:
        """将 RAG API 错误转换为 Platform 稳定错误结构。"""

        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": exc.request_id or request.state.request_id,
                    "retryable": exc.retryable,
                }
            },
        )

    application.include_router(api_router)
    return application


app = create_app()
