"""文件说明：集中组装 Platform 数据库、目录读取和进程内知识服务依赖。"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from knowledge.catalog import KnowledgeCatalogService
from knowledge.service import KnowledgeService

from app.application.chat_service import ChatService
from app.application.diagnostic_service import DiagnosticService
from app.application.document_service import DocumentService
from app.application.health_service import HealthService
from app.application.auth_service import AuthService, AuthenticationError, AuthorizationError, Principal, hash_token
from app.application.query_scope_service import QueryScopeResolver
from app.config import get_settings
from app.infrastructure.db.session import check_database, get_db_session


def get_current_principal(
    request: Request, session: Session = Depends(get_db_session)
) -> Principal:
    """解析HttpOnly服务端会话并返回统一内部身份。"""

    settings = get_settings()
    try:
        return AuthService(session, settings.session_ttl_hours).authenticate(
            request.cookies.get(settings.session_cookie_name)
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_permission(permission: str, *, csrf: bool = False):
    """生成明确权限码依赖，并为Cookie管理写操作执行CSRF校验。"""

    def dependency(
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: Session = Depends(get_db_session),
    ) -> Principal:
        try:
            AuthService(session, get_settings().session_ttl_hours).require_permission(principal, permission)
        except AuthorizationError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足") from exc
        if csrf:
            token = request.headers.get("X-CSRF-Token")
            if not token or hash_token(token) != principal.csrf_token_hash:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF校验失败")
        return principal

    return dependency


def get_health_service() -> HealthService:
    """按当前配置创建健康检查应用服务。"""

    settings = get_settings()
    return HealthService(
        settings=settings,
        database_check=check_database,
    )


def get_knowledge_service(request: Request) -> KnowledgeService:
    """返回应用生命周期内复用的进程内知识查询服务。"""

    return request.app.state.knowledge_service


def get_knowledge_catalog(request: Request) -> KnowledgeCatalogService:
    """返回只读取active制度的知识目录服务。"""

    return request.app.state.knowledge_catalog


def get_document_service(
    request: Request,
    catalog: KnowledgeCatalogService = Depends(get_knowledge_catalog),
    principal: Principal = Depends(require_permission("knowledge.document.read")),
) -> DocumentService:
    """创建直接读取知识目录的制度服务。"""

    resolver = request.app.state.document_access_resolver
    return DocumentService(catalog, resolver, principal)


def get_chat_service(
    request: Request,
    session: Session = Depends(get_db_session),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    principal: Principal = Depends(require_permission("chat.read")),
    catalog: KnowledgeCatalogService = Depends(get_knowledge_catalog),
) -> ChatService:
    """创建会话服务，并注入唯一进程内知识查询入口。"""

    access_resolver = request.app.state.document_access_resolver
    scope_resolver = QueryScopeResolver(catalog, access_resolver)
    return ChatService(session, knowledge_service, principal, scope_resolver)


def get_diagnostic_service(session: Session = Depends(get_db_session)) -> DiagnosticService:
    """创建仅查询Platform公开响应快照的诊断服务。"""

    return DiagnosticService(session)
