"""文件说明：定义本地登录、当前身份和4A预留接口的公开数据契约。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class CurrentUserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    must_change_password: bool
    auth_provider: str


class LoginResponse(BaseModel):
    user: CurrentUserResponse
    expires_at: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class AuthProviderSummary(BaseModel):
    key: str
    type: str
    enabled: bool
    ready: bool
