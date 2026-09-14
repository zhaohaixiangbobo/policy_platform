"""文件说明：创建统一FastAPI应用并管理进程内知识查询服务生命周期。"""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.middleware import RequestIdMiddleware
from app.logging_config import configure_rotating_logger
from knowledge.catalog import KnowledgeCatalogService
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.rag.runtime import RagRuntimeSettings
from knowledge.service import KnowledgeService, KnowledgeServiceError
from app.application.auth_service import ensure_auth_baseline
from app.application.query_scope_service import OpenDocumentAccessResolver
from app.infrastructure.db.session import get_session_factory


@asynccontextmanager
async def lifespan(application: FastAPI):
    """装配管理目录和惰性进程内RAG服务，停止时统一释放资源。"""

    settings = get_settings()
    configure_rotating_logger(
        "policy_platform.api",
        level_name=os.getenv("PLATFORM_API_LOG_LEVEL", "INFO"),
        log_file=os.getenv(
            "PLATFORM_API_LOG_FILE",
            str(Path(__file__).resolve().parents[2] / "logs" / "api.log"),
        ),
        max_bytes=int(os.getenv("PLATFORM_API_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        backup_count=int(os.getenv("PLATFORM_API_LOG_BACKUP_COUNT", "5")),
    )
    paths = KnowledgePaths(settings.knowledge_data_root)
    # 空库首次启动也必须得到稳定目录和独立索引配置，不依赖迁移测试数据。
    KnowledgeManagementService(paths).initialize_empty_baseline()
    with get_session_factory()() as session:
        ensure_auth_baseline(session)
    knowledge_service = KnowledgeService(
        RagRuntimeSettings.from_environment(db_path=paths.database_path)
    )
    application.state.knowledge_catalog = KnowledgeCatalogService(paths)
    application.state.document_access_resolver = OpenDocumentAccessResolver()
    application.state.knowledge_service = knowledge_service
    try:
        yield
    finally:
        await knowledge_service.close()


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

    @application.exception_handler(KnowledgeServiceError)
    async def handle_knowledge_service_error(
        request: Request, exc: KnowledgeServiceError
    ) -> JSONResponse:
        """将进程内知识查询错误转换为 Platform 稳定错误结构。"""

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
