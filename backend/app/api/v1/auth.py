"""文件说明：暴露本地登录、服务端会话、CSRF和未来4A能力探测接口。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.application.auth_service import AuthService, AuthenticationError, Principal
from app.api.dependencies import require_permission
from app.config import get_settings
from app.infrastructure.db.session import get_db_session
from app.schemas.auth import AuthProviderSummary, ChangePasswordRequest, CurrentUserResponse, LoginRequest, LoginResponse
from app.infrastructure.db.models import AuthProvider

router = APIRouter(prefix="/auth", tags=["auth"])


def to_user(principal: Principal) -> CurrentUserResponse:
    return CurrentUserResponse(id=principal.user_id, username=principal.username, display_name=principal.display_name, roles=list(principal.roles), permissions=sorted(principal.permissions), must_change_password=principal.must_change_password, auth_provider=principal.auth_provider)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response, session: Session = Depends(get_db_session)) -> LoginResponse:
    settings = get_settings()
    try:
        result = AuthService(session, settings.session_ttl_hours).login(payload.username, payload.password, request.client.host if request.client else None, request.headers.get("user-agent"))
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    response.set_cookie(settings.session_cookie_name, result.session_token, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/", max_age=settings.session_ttl_hours * 3600)
    response.set_cookie("policy_platform_csrf", result.csrf_token, httponly=False, secure=settings.cookie_secure, samesite="lax", path="/", max_age=settings.session_ttl_hours * 3600)
    return LoginResponse(user=to_user(result.principal), expires_at=result.expires_at.isoformat())


@router.get("/me", response_model=CurrentUserResponse)
def me(request: Request, session: Session = Depends(get_db_session)) -> CurrentUserResponse:
    settings = get_settings()
    try:
        principal = AuthService(session, settings.session_ttl_hours).authenticate(request.cookies.get(settings.session_cookie_name))
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return to_user(principal)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: Session = Depends(get_db_session)) -> Response:
    settings = get_settings()
    service = AuthService(session, settings.session_ttl_hours)
    try:
        service.logout(service.authenticate(request.cookies.get(settings.session_cookie_name)))
    except AuthenticationError:
        pass
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("policy_platform_csrf", path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("chat.read", csrf=True))) -> Response:
    try:
        AuthService(session, get_settings().session_ttl_hours).change_password(principal, payload.current_password, payload.new_password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers", response_model=list[AuthProviderSummary])
def providers(session: Session = Depends(get_db_session)) -> list[AuthProviderSummary]:
    items = session.scalars(select(AuthProvider).order_by(AuthProvider.provider_key)).all()
    return [AuthProviderSummary(key=item.provider_key, type=item.provider_type, enabled=item.enabled, ready=item.provider_key == "LOCAL" and item.enabled) for item in items]
