"""文件说明：API/Worker只读核对双库版本与必要初始化，不执行DDL或业务回填。"""

from pathlib import Path
import os
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from app.infrastructure.db.session import get_engine
from knowledge.storage.repository import engine_for, database_url
from app.config import get_settings
from knowledge.config import KnowledgePaths

ROOT = Path(__file__).resolve().parents[3]


def expected_head(module):
    directory = "migrations" if module == "platform" else "knowledge_migrations"
    config = Config()
    config.set_main_option("script_location", str(ROOT / directory))
    return ScriptDirectory.from_config(config).get_current_head()


def check_readiness(*, check_files=True):
    for module, engine in (("platform", get_engine()), ("knowledge", engine_for(database_url()))):
        with engine.connect() as connection:
            heads = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if heads != [expected_head(module)]:
                raise RuntimeError(f"{module}数据库版本未就绪，请先执行独立迁移")
            if module == "platform":
                if connection.execute(text("SELECT count(*) FROM auth_provider WHERE provider_key='LOCAL'")).scalar() != 1:
                    raise RuntimeError("请先运行initialize-platform-pg.py初始化角色及认证配置")
    if check_files:
        settings = get_settings()
        paths = KnowledgePaths(settings.knowledge_data_root)
        for directory in (paths.source_documents, paths.accepted_documents, paths.pdf_documents,
                          paths.pending_documents, paths.temp_directory, settings.materials_root):
            if not directory.is_dir() or not os.access(directory, os.R_OK | os.W_OK):
                raise RuntimeError("业务文件目录未就绪，请先执行initialize-knowledge-pg.py并核对读写权限")
