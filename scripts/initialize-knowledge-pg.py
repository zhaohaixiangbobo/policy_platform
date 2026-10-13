"""文件说明：显式初始化知识目录及索引profile；不创建表、不访问或复制旧业务文件。"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--inherit-runtime-settings", action="store_true", help="从旧.env仅继承模型/渲染/学习开关，保留新库、目录及Qdrant隔离配置")
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise ValueError("配置文件不存在，请先创建隔离环境")
    if args.inherit_runtime_settings:
        source = dotenv_values(ROOT / ".env")
        allowed_prefixes = ("POLICY_EMBEDDING_", "POLICY_RERANK_", "POLICY_GENERATOR_", "PLATFORM_LEARNING_ASSESSMENT_")
        allowed_keys = {"POLICY_DOCX_RENDER_ENGINE", "POLICY_LIBREOFFICE_PATH", "POLICY_QUALITY_GATE_ENABLED", "PLATFORM_RAG_DIAGNOSTICS_ENABLED"}
        for key, value in source.items():
            if value is not None and (key.startswith(allowed_prefixes) or key in allowed_keys):
                set_key(args.env_file, key, value, encoding="utf-8")
        print("已继承既有模型、渲染和学习配置；数据库、Qdrant命名和业务目录保持隔离")
    os.environ["PLATFORM_ENV_FILE"] = str(args.env_file.resolve())
    load_dotenv(args.env_file, override=False)
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import get_settings
    from app.infrastructure.db.readiness import check_readiness
    from knowledge.config import KnowledgePaths
    from knowledge.management import KnowledgeManagementService
    check_readiness(check_files=False)
    get_settings().materials_root.mkdir(parents=True, exist_ok=True)
    result = KnowledgeManagementService(KnowledgePaths(get_settings().knowledge_data_root)).initialize_empty_baseline()
    print(f"Knowledge目录与profile已初始化：{result['profile_name']}；未导入业务数据")


if __name__ == "__main__":
    main()
