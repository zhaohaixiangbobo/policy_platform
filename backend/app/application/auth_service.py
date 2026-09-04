"""文件说明：实现AuthProvider抽象、本地Argon2认证、服务端会话、RBAC和首个管理员初始化。"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import (
    AuthProvider,
    AuthSession,
    IdentityLink,
    LocalCredential,
    PlatformAuditLog,
    Role,
    UserAccount,
    UserRole,
    utc_now,
)


ROLE_PERMISSIONS = {
    "USER": ["chat.read", "chat.write", "knowledge.document.read"],
    "REVIEWER": [
        "chat.read", "chat.write", "knowledge.document.read", "admin.access",
        "knowledge.parse.review", "knowledge.chunk.review", "policy_relation.review",
        "policy_process.review", "knowledge.metadata.review",
    ],
    "ADMIN": [
        "chat.read", "chat.write", "knowledge.document.read", "admin.access",
        "knowledge.ingestion.manage", "knowledge.parse.review", "knowledge.chunk.review",
        "knowledge.metadata.manage", "knowledge.metadata.review", "knowledge.metadata.publish",
        "knowledge.parse.correct", "knowledge.batch.manage", "knowledge.index.publish",
        "policy_relation.manage", "policy_relation.review", "policy_process.manage", "policy_process.review",
        "policy_process.publish", "system.user.manage", "system.audit.read",
    ],
}


class AuthenticationError(RuntimeError):
    """登录凭据或会话无效。"""


class AuthorizationError(RuntimeError):
    """当前身份不具备所需权限。"""


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    must_change_password: bool
    auth_provider: str
    session_id: str
    csrf_token_hash: str


@dataclass(frozen=True)
class LoginResult:
    principal: Principal
    session_token: str
    csrf_token: str
    expires_at: datetime


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_auth_baseline(session: Session) -> AuthProvider:
    """幂等创建LOCAL/4A Provider和三类冻结角色。"""

    provider = session.scalar(select(AuthProvider).where(AuthProvider.provider_key == "LOCAL"))
    if provider is None:
        provider = AuthProvider(provider_key="LOCAL", provider_type="LOCAL", enabled=True)
        session.add(provider)
    four_a = session.scalar(select(AuthProvider).where(AuthProvider.provider_key == "FOUR_A"))
    if four_a is None:
        session.add(AuthProvider(provider_key="FOUR_A", provider_type="SSO", enabled=False))
    for code, permissions in ROLE_PERMISSIONS.items():
        role = session.scalar(select(Role).where(Role.code == code))
        if role is None:
            session.add(Role(code=code, name=code, permissions_json=json.dumps(permissions)))
        else:
            role.permissions_json = json.dumps(permissions)
    session.commit()
    session.refresh(provider)
    return provider


def bootstrap_local_user(
    session: Session, username: str, display_name: str, password: str, role_codes: list[str]
) -> UserAccount:
    """创建受控本地用户；仅供初始化脚本和管理员服务调用。"""

    if len(password) < 10:
        raise ValueError("初始密码至少10个字符")
    provider = ensure_auth_baseline(session)
    if session.scalar(select(UserAccount).where(UserAccount.username == username)):
        raise ValueError("用户名已经存在")
    roles = session.scalars(select(Role).where(Role.code.in_(role_codes))).all()
    if {item.code for item in roles} != set(role_codes):
        raise ValueError("包含未定义角色")
    user = UserAccount(username=username, display_name=display_name, must_change_password=True)
    session.add(user)
    session.flush()
    session.add(LocalCredential(user_id=user.id, password_hash=PasswordHasher().hash(password)))
    session.add(IdentityLink(provider_id=provider.id, external_subject=username, user_id=user.id))
    for role in roles:
        session.add(UserRole(user_id=user.id, role_id=role.id))
    session.add(PlatformAuditLog(request_id="bootstrap", actor_user_id=user.id, auth_provider="LOCAL", action="user.bootstrap", object_type="user_account", object_id=user.id, status="SUCCEEDED"))
    session.commit()
    return user


class AuthService:
    """当前使用LocalAuthProvider，接口边界可替换为未来FourAAuthProvider。"""

    def __init__(self, session: Session, session_ttl_hours: int) -> None:
        self._session = session
        self._ttl = timedelta(hours=session_ttl_hours)
        self._hasher = PasswordHasher()

    def login(self, username: str, password: str, ip_address: str | None, user_agent: str | None) -> LoginResult:
        provider = ensure_auth_baseline(self._session)
        user = self._session.scalar(select(UserAccount).where(UserAccount.username == username.strip()))
        credential = self._session.get(LocalCredential, user.id) if user else None
        if user is None or credential is None or user.status != "ACTIVE":
            raise AuthenticationError("用户名或密码错误")
        try:
            self._hasher.verify(credential.password_hash, password)
        except VerifyMismatchError as exc:
            credential.failed_attempts += 1
            self._session.commit()
            raise AuthenticationError("用户名或密码错误") from exc
        credential.failed_attempts = 0
        if self._hasher.check_needs_rehash(credential.password_hash):
            credential.password_hash = self._hasher.hash(password)
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = utc_now() + self._ttl
        auth_session = AuthSession(
            user_id=user.id, provider_id=provider.id, token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token), expires_at=expires_at,
            ip_address=ip_address, user_agent=(user_agent or "")[:500],
        )
        self._session.add(auth_session)
        self._session.commit()
        return LoginResult(self._principal(user, auth_session, "LOCAL"), session_token, csrf_token, expires_at)

    def authenticate(self, session_token: str | None) -> Principal:
        if not session_token:
            raise AuthenticationError("尚未登录")
        auth_session = self._session.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(session_token)))
        now = utc_now()
        if auth_session is None or auth_session.revoked_at is not None or self._expired(auth_session.expires_at, now):
            raise AuthenticationError("登录会话已失效")
        user = self._session.get(UserAccount, auth_session.user_id)
        if user is None or user.status != "ACTIVE":
            raise AuthenticationError("用户已停用")
        provider = self._session.get(AuthProvider, auth_session.provider_id)
        auth_session.last_seen_at = now
        self._session.commit()
        return self._principal(user, auth_session, provider.provider_key if provider else "UNKNOWN")

    def logout(self, principal: Principal) -> None:
        auth_session = self._session.get(AuthSession, principal.session_id)
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = utc_now()
            self._session.commit()

    def change_password(self, principal: Principal, current_password: str, new_password: str) -> None:
        """核验当前密码并完成首次强制修改，当前会话继续有效。"""

        if len(new_password) < 10 or new_password == current_password:
            raise AuthenticationError("新密码至少10个字符且不能与当前密码相同")
        credential = self._session.get(LocalCredential, principal.user_id)
        user = self._session.get(UserAccount, principal.user_id)
        if credential is None or user is None:
            raise AuthenticationError("当前身份不支持本地密码修改")
        try:
            self._hasher.verify(credential.password_hash, current_password)
        except VerifyMismatchError as exc:
            raise AuthenticationError("当前密码错误") from exc
        credential.password_hash = self._hasher.hash(new_password)
        credential.password_changed_at = utc_now()
        user.must_change_password = False
        self._session.add(PlatformAuditLog(request_id="password-change", actor_user_id=user.id, auth_provider="LOCAL", action="password.change", object_type="user_account", object_id=user.id, status="SUCCEEDED"))
        self._session.commit()

    def require_permission(self, principal: Principal, permission: str) -> None:
        if permission not in principal.permissions:
            raise AuthorizationError(permission)

    def _principal(self, user: UserAccount, auth_session: AuthSession, provider_key: str) -> Principal:
        roles = self._session.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)).all()
        permissions = {permission for role in roles for permission in json.loads(role.permissions_json)}
        return Principal(user.id, user.username, user.display_name, tuple(sorted(role.code for role in roles)), frozenset(permissions), user.must_change_password, provider_key, auth_session.id, auth_session.csrf_token_hash)

    @staticmethod
    def _expired(value: datetime, now: datetime) -> bool:
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized <= now
