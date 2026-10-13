"""文件说明：仅初始化隔离的本地PG17开发实例；凭据保存到git忽略目录，保护既有容器和卷。"""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "var/postgres-dev"
CONTAINER = "policy-platform-pg17-dev"
VOLUME = "policy-platform-pg17-dev-data"
IMAGE = "postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"


def docker(*args, input=None, env=None):
    result = subprocess.run(["docker", *args], input=input, text=True, encoding="utf-8", capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError(f"Docker操作失败：{args[0]}（退出码{result.returncode}），请检查容器日志；凭据不输出")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"container": CONTAINER, "volume": VOLUME, "port": "127.0.0.1:55432", "databases": ["platform", "knowledge"], "image": IMAGE}))
        return
    names = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    if CONTAINER in names or VOLUME in docker("volume", "ls", "--format", "{{.Name}}").splitlines() or STATE.exists():
        raise ValueError("隔离资源或凭据目录已存在，请检查后续阶段；禁止覆盖或重新初始化")
    info = json.loads(docker("image", "inspect", IMAGE))[0]
    if info["Architecture"] != "amd64" or info["Os"] != "linux":
        raise ValueError("本机P1镜像身份不匹配")
    credentials = {name: secrets.token_hex(24) for name in ("postgres", "platform_owner", "platform_app", "knowledge_owner", "knowledge_app")}
    STATE.mkdir(parents=True)
    # 本机凭据仅留在忽略目录；不写入源码、工具输出或命令行参数。
    (STATE / "credentials.json").write_text(json.dumps(credentials), encoding="utf-8")
    env = dict(os.environ, POSTGRES_PASSWORD=credentials["postgres"])
    docker("run", "-d", "--pull=never", "--name", CONTAINER, "--label", "policy-platform.purpose=pg17-dev",
           "-p", "127.0.0.1:55432:5432", "--mount", f"type=volume,source={VOLUME},target=/var/lib/postgresql/data",
           "-e", "POSTGRES_PASSWORD", "--restart", "unless-stopped", IMAGE, env=env)
    for _ in range(30):
        ready = subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-U", "postgres"], capture_output=True)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PG尚未就绪；保留现场，不自动删容器或卷")
    for database in ("platform", "knowledge"):
        owner, app = database + "_owner", database + "_app"
        sql = f"CREATE ROLE {owner} LOGIN PASSWORD '{credentials[owner]}'; CREATE ROLE {app} LOGIN PASSWORD '{credentials[app]}'; CREATE DATABASE {database} OWNER {owner}; REVOKE ALL ON DATABASE {database} FROM PUBLIC; GRANT CONNECT ON DATABASE {database} TO {owner},{app}; COMMENT ON DATABASE {database} IS 'policy-platform-pg17-dev:{database}';"
        docker("exec", "-i", CONTAINER, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", input=sql)
        sql = f"REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO {app}; ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {app}; ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {app};"
        docker("exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", input=sql)
    lines = [f"PLATFORM_DATABASE_URL=postgresql+psycopg://platform_app:{credentials['platform_app']}@127.0.0.1:55432/platform",
             f"PLATFORM_MIGRATION_URL=postgresql+psycopg://platform_owner:{credentials['platform_owner']}@127.0.0.1:55432/platform",
             f"KNOWLEDGE_DATABASE_URL=postgresql+psycopg://knowledge_app:{credentials['knowledge_app']}@127.0.0.1:55432/knowledge",
             f"KNOWLEDGE_MIGRATION_URL=postgresql+psycopg://knowledge_owner:{credentials['knowledge_owner']}@127.0.0.1:55432/knowledge",
             "POLICY_INDEX_PROFILE=policy_platform_pg17_dev", "POLICY_INDEX_ALIAS=policy_platform_pg17_dev_active",
             "POLICY_COLLECTION_PREFIX=policy_platform_pg17_dev", "POLICY_QDRANT_URL=http://127.0.0.1:6333",
             f"PLATFORM_KNOWLEDGE_DATA_ROOT={(STATE / 'knowledge-p2').as_posix()}",
             f"PLATFORM_MATERIALS_ROOT={(STATE / 'materials').as_posix()}",
             f"PLATFORM_WORKER_LOCK_DIR={(STATE / 'worker-locks').as_posix()}"]
    (STATE / "platform.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("已建立隔离PG17容器、双库及独立角色；配置在var/postgres-dev/platform.env；Knowledge尚未迁移，禁止启动混合业务链路。")


if __name__ == "__main__":
    main()
