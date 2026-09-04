"""文件说明：验证Platform API存活及其自有数据库就绪状态。"""

from fastapi.testclient import TestClient

from app.api.dependencies import get_health_service
from app.config import get_settings
from app.main import app
from app.schemas.health import ComponentHealth, HealthResponse


class FakeHealthService:
    """按测试场景返回固定依赖状态。"""

    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def readiness(self, request_id: str) -> HealthResponse:
        state = "ok" if self._ready else "unavailable"
        return HealthResponse(
            status="ok" if self._ready else "not_ready",
            service="制度知识智能服务平台",
            version="0.1.0-m1",
            request_id=request_id,
            components={
                "platform_database": ComponentHealth(status=state),
            },
        )


def test_live_returns_request_id() -> None:
    """live端点应在不探测外部依赖时稳定返回200。"""

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": "test-live-request"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-live-request"
    assert response.json()["request_id"] == "test-live-request"
    assert response.json()["status"] == "ok"


def test_ready_returns_200_when_dependencies_are_ready() -> None:
    """全部必要依赖可用时ready端点应返回200。"""

    app.dependency_overrides[get_health_service] = lambda: FakeHealthService(True)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["components"]["platform_database"]["status"] == "ok"


def test_ready_returns_503_when_dependency_is_unavailable() -> None:
    """任一必要依赖不可用时ready端点应返回稳定503业务结构。"""

    app.dependency_overrides[get_health_service] = lambda: FakeHealthService(False)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["platform_database"]["status"] == "unavailable"


def teardown_module() -> None:
    """清理缓存配置，避免影响同一解释器中的后续测试。"""

    get_settings.cache_clear()
