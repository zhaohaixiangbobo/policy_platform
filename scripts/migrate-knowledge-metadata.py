"""文件说明：显式执行历史正式制度元数据迁移；不会处理新上传或未发布文档。"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from knowledge.data_migrations import migrate_historical_published_metadata  # noqa: E402


if __name__ == "__main__":
    result = migrate_historical_published_metadata(get_settings().knowledge_database_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
