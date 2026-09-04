"""文件说明：集中读取统一Platform后端和知识模块的本机配置。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLATFORM_DATABASE = PROJECT_ROOT / "var" / "platform.db"
DEFAULT_KNOWLEDGE_DATA_ROOT = PROJECT_ROOT / "var" / "knowledge"


class Settings(BaseSettings):
    """统一后端可由环境变量覆盖的本机配置。"""

    app_name: str = "制度知识智能服务平台"
    app_version: str = "2.0.0-phase2"
    host: str = "127.0.0.1"
    port: int = 8020
    database_url: str = f"sqlite:///{DEFAULT_PLATFORM_DATABASE.as_posix()}"
    knowledge_data_root: Path = DEFAULT_KNOWLEDGE_DATA_ROOT
    rag_diagnostics_enabled: bool = False
    rag_api_url: str = "http://127.0.0.1:8010"
    rag_api_connect_timeout_seconds: float = 5.0
    session_cookie_name: str = "policy_platform_session"
    session_ttl_hours: int = 8
    cookie_secure: bool = False
    process_reviewer_user_id: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="PLATFORM_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def knowledge_database_path(self) -> Path:
        """返回统一知识数据根目录中的SQLite路径。"""

        return self.knowledge_data_root.resolve() / "policy_parser.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """复用经过校验的只读配置实例。"""

    return Settings()
