"""文件说明：生成P4独立空环境配置与首次建库SQL；不连接Docker/数据库，不覆盖现有配置。"""

import argparse
import json
from pathlib import Path
import secrets

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "var/compose-p4"
MODEL_PREFIXES = ("POLICY_EMBEDDING_", "POLICY_RERANK_", "POLICY_GENERATOR_")
RUNTIME_KEYS = {"POLICY_QUALITY_GATE_ENABLED", "PLATFORM_RAG_DIAGNOSTICS_ENABLED",
                "PLATFORM_LEARNING_ASSESSMENT_ENABLED", "PLATFORM_LEARNING_ASSESSMENT_MAX_QUESTIONS",
                "PLATFORM_LEARNING_ASSESSMENT_TTL_HOURS", "PLATFORM_LEARNING_ASSESSMENT_TASK_TIMEOUT_SECONDS"}


def env_text(values):
    """使用dotenv单引号格式，保留模型参数中的空格及特殊字符。"""
    return "".join(f"{key}='{str(value).replace(chr(92), chr(92)*2).replace(chr(39), chr(92)+chr(39))}'\n"
                   for key, value in values.items())


def prepare(source: Path, destination: Path, *, stage: str = "p4"):
    if stage not in ("p4", "p5"):
        raise ValueError("仅支持p4/p5部署配置")
    if destination.exists():
        raise ValueError("配置目录已存在，保留凭据及现有数据；升级直接复用，不重新初始化")
    if not source.is_file():
        raise ValueError("请提供现有运行配置，仅继承模型与学习开关，不复制业务数据")
    inherited = dotenv_values(source)
    for key in ("POLICY_EMBEDDING_URL", "POLICY_RERANK_URL", "POLICY_GENERATOR_URL"):
        if not inherited.get(key):
            raise ValueError(f"原运行配置缺少{key}，请先核对配置")
    passwords = {key: secrets.token_hex(24) for key in (
        "postgres", "platform_owner", "platform_app", "knowledge_owner", "knowledge_app")}
    # 每次独立部署具有唯一身份；后续迁移沿用同一标识，不与旧开发库混用。
    identity = "policy-platform-compose-" + secrets.token_hex(8)
    namespace = f"policy_platform_{stage}_" + secrets.token_hex(4)
    runtime = {key: value for key, value in inherited.items() if value is not None and (
        key.startswith(MODEL_PREFIXES) or key in RUNTIME_KEYS)}
    runtime.update({
        "PLATFORM_DATABASE_URL": f"postgresql+psycopg://platform_app:{passwords['platform_app']}@postgres:5432/platform",
        "KNOWLEDGE_DATABASE_URL": f"postgresql+psycopg://knowledge_app:{passwords['knowledge_app']}@postgres:5432/knowledge",
        "PLATFORM_KNOWLEDGE_DATA_ROOT": "/data/knowledge", "PLATFORM_MATERIALS_ROOT": "/data/materials",
        "PLATFORM_API_LOG_FILE": "/logs/api.log", "PLATFORM_WORKER_LOG_FILE": "/logs/worker.log",
        "PLATFORM_LEARNING_LOG_FILE": "/logs/learning.log", "PLATFORM_COOKIE_SECURE": "false",
        "POLICY_DOCX_RENDER_ENGINE": "libreoffice", "POLICY_LIBREOFFICE_PATH": "/usr/bin/soffice",
        "POLICY_QDRANT_URL": "http://qdrant:6333", "POLICY_INDEX_PROFILE": namespace,
        "POLICY_INDEX_ALIAS": namespace + "_active", "POLICY_COLLECTION_PREFIX": namespace,
    })
    migration = {}
    sql = ["-- 文件说明：仅由PostgreSQL空卷首次初始化执行；已有卷不会执行此文件。"]
    for database in ("platform", "knowledge"):
        owner, app = f"{database}_owner", f"{database}_app"
        marker = f"{identity}:{database}"
        migration[f"{database.upper()}_MIGRATION_URL"] = f"postgresql+psycopg://{owner}:{passwords[owner]}@postgres:5432/{database}"
        migration[f"{database.upper()}_DATABASE_MARKER"] = marker
        sql.extend([
            f"CREATE ROLE {owner} LOGIN PASSWORD '{passwords[owner]}';",
            f"CREATE ROLE {app} LOGIN PASSWORD '{passwords[app]}';",
            f"CREATE DATABASE {database} OWNER {owner};",
            f"REVOKE ALL ON DATABASE {database} FROM PUBLIC;",
            f"GRANT CONNECT ON DATABASE {database} TO {owner}, {app};",
            f"COMMENT ON DATABASE {database} IS '{marker}';",
            f"\\connect {database}",
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC;",
            f"GRANT USAGE ON SCHEMA public TO {app};",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app};",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app};",
            "\\connect postgres",
        ])
    destination.mkdir(parents=True, mode=0o700)
    # 外部Qdrant仅用于本地开发覆盖配置，仍使用新命名空间，不能接管旧索引。
    external_runtime = dict(runtime, POLICY_QDRANT_URL="http://host.docker.internal:6333")
    files = {"runtime.env": env_text(runtime), "runtime-external.env": env_text(external_runtime), "migration.env": env_text(migration),
             "postgres-password": passwords["postgres"] + "\n", "init.sql": "\n".join(sql) + "\n"}
    if stage == "p5":
        # 生产配置保留模型契约，仅生成新库身份；不提供连接本机旧Qdrant的配置。
        runtime["POLICY_LIBREOFFICE_PATH"] = "/usr/local/bin/soffice"
        files["runtime.env"] = env_text(runtime)
        del files["runtime-external.env"]
    for name, content in files.items():
        # 排他创建：部分写入失败也保留现场，不覆盖凭据。目录权限是主要保护边界。
        with (destination / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return {"directory": str(destination), "identity": identity, "namespace": namespace,
            "learning_enabled": runtime.get("PLATFORM_LEARNING_ASSESSMENT_ENABLED", "false")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=("p4", "p5"), default="p4")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    destination = args.destination or ROOT / f"var/compose-{args.stage}"
    if not args.execute:
        print(f"预览：生成{destination}配置；新凭据/新命名空间；不连接数据库、不复制文件、不启动容器。")
        return
    print(json.dumps(prepare(args.source_env, destination, stage=args.stage), ensure_ascii=False))


if __name__ == "__main__":
    main()
