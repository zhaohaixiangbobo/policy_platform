"""文件说明：从FastAPI应用导出确定性的UTF-8 OpenAPI契约快照。"""

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
OUTPUT_PATH = REPOSITORY_ROOT / "docs" / "api" / "openapi.json"

# 脚本不安装后端包，只把仓库内backend加入当前解释器的模块路径。
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    """生成带中文内容且无ASCII转义的OpenAPI JSON。"""

    content = json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    OUTPUT_PATH.write_text(f"{content}\n", encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
