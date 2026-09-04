"""文件说明：检查Platform自身业务库，不额外调用Knowledge Engine健康端点。"""

import asyncio
from collections.abc import Callable

from app.config import Settings
from app.schemas.health import ComponentHealth, HealthResponse


class HealthService:
    """生成不泄露内部地址、路径和异常栈的健康响应。"""

    def __init__(
        self,
        settings: Settings,
        database_check: Callable[[], bool],
    ) -> None:
        self._settings = settings
        self._database_check = database_check

    async def readiness(self, request_id: str) -> HealthResponse:
        """检查Platform自身数据库；Knowledge Engine只在真实问答时调用。"""

        database_ready = await asyncio.to_thread(self._database_check)

        return HealthResponse(
            status="ok" if database_ready else "not_ready",
            service=self._settings.app_name,
            version=self._settings.app_version,
            request_id=request_id,
            components={
                "platform_database": ComponentHealth(
                    status="ok" if database_ready else "unavailable"
                ),
            },
        )
