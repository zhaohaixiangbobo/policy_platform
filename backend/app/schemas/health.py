"""文件说明：定义Platform API健康检查的稳定公开响应。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    """单个内部依赖的公开可用状态。"""

    status: Literal["ok", "unavailable"]

    model_config = ConfigDict(extra="forbid")


class HealthResponse(BaseModel):
    """live和ready端点共用的最小响应契约。"""

    status: Literal["ok", "not_ready"]
    service: str
    version: str
    request_id: str
    components: dict[str, ComponentHealth] | None = None

    model_config = ConfigDict(extra="forbid")
