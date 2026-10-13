"""文件说明：集中读取统一Platform后端和知识模块的本机配置。"""

from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from pydantic import Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# POLICY_*由知识模块读取os.environ；外部注入变量始终优先于本机.env。
ENV_FILE = Path(os.getenv("PLATFORM_ENV_FILE", str(PROJECT_ROOT / ".env"))).resolve()
if os.getenv("PLATFORM_ENV_FILE") and not ENV_FILE.is_file():
    raise ValueError("指定的PLATFORM_ENV_FILE不存在，拒绝回退旧配置")
load_dotenv(ENV_FILE, override=False)
DEFAULT_PLATFORM_DATABASE = PROJECT_ROOT / "var" / "platform.db"
DEFAULT_KNOWLEDGE_DATA_ROOT = PROJECT_ROOT / "var" / "knowledge"


class Settings(BaseSettings):
    """统一后端可由环境变量覆盖的本机配置。"""

    app_name: str = "制度知识智能服务平台"
    app_version: str = "2.0.0-phase2"
    host: str = "127.0.0.1"
    port: int = 8020
    database_url: str = ""
    knowledge_data_root: Path = DEFAULT_KNOWLEDGE_DATA_ROOT
    rag_diagnostics_enabled: bool = False
    session_cookie_name: str = "policy_platform_session"
    session_ttl_hours: int = 8
    cookie_secure: bool = False
    process_reviewer_user_id: str | None = None
    materials_root: Path = PROJECT_ROOT / "var" / "materials"
    learning_assessment_enabled: bool = False
    learning_assessment_max_questions: int = Field(default=15, ge=1, le=15)
    learning_assessment_ttl_hours: int = Field(default=24, ge=1, le=24)
    learning_assessment_task_timeout_seconds: int = Field(default=1800, ge=300, le=3600)

    model_config = SettingsConfigDict(
        env_prefix="PLATFORM_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def knowledge_database_url(self) -> str:
        """数据库连接与业务文件目录独立配置。"""
        from knowledge.storage.repository import database_url
        return database_url()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """复用经过校验的只读配置实例。"""

    settings = Settings()
    if not settings.database_url.startswith("postgresql+psycopg://"):
        raise ValueError("请配置PostgreSQL URL；本版本已移除SQLite运行入口")
    return settings
