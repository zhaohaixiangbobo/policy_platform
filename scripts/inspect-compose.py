"""文件说明：P4只读巡检；不输出凭据/业务日志，不改变容器、数据库或索引。"""

import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "ingestion-worker", "learning-worker", "postgres", "qdrant", "web")


def docker(*args):
    result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise RuntimeError("Docker检查失败，请检查服务状态或执行权限；原始输出未展示")
    return result.stdout.strip()


def alerts_for(states, free_percent, connection_percent, pool_timeouts, *, min_free, max_connections):
    """纯规则函数，可模拟低空间及连接异常，不对真实服务施加故障。"""
    alerts = []
    for service in SERVICES:
        state = states.get(service, {})
        if state.get("status") != "running":
            alerts.append(f"{service}: 未运行，检查容器日志和迁移就绪状态")
        if state.get("health") in {"unhealthy", "starting"}:
            alerts.append(f"{service}: 健康检查尚未通过")
        if state.get("restarts", 0) > 0:
            alerts.append(f"{service}: 存在自动重启记录，核对退出原因")
    if free_percent < min_free:
        alerts.append("数据卷文件系统剩余空间不足，评估扩容；不要自动删除索引")
    if connection_percent >= max_connections:
        alerts.append("PostgreSQL连接占用达到阈值，检查长事务及连接池预算")
    if pool_timeouts:
        alerts.append("最近日志存在连接池等待超时，请检查事务及模型调用边界")
    return alerts


def inspect(min_free=15.0, max_connections=80.0):
    states = {}
    for service in SERVICES:
        print(f"event=inspection_step component={service}", flush=True)
        ids = docker("compose", "ps", "--all", "-q", service).splitlines()
        if len(ids) != 1:
            states[service] = {"status": "missing_or_multiple"}
            continue
        raw = json.loads(docker("inspect", ids[0], "--format",
                               '{"state":{{json .State}},"restarts":{{.RestartCount}}}'))
        states[service] = {"status": raw["state"]["Status"], "restarts": raw["restarts"],
                           "health": raw["state"].get("Health", {}).get("Status", "not_configured")}
    sql = "SELECT json_build_object('connections',(SELECT count(*) FROM pg_stat_activity),'active',(SELECT count(*) FROM pg_stat_activity WHERE state='active'),'max_connections',current_setting('max_connections')::int)"
    pg = json.loads(docker("compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "postgres", "-tAc", sql))
    # 查询容器所挂Linux卷的文件系统，而不是误用Windows项目盘空间。
    df = docker("compose", "exec", "-T", "qdrant", "df", "-Pk", "/qdrant/storage").splitlines()[-1].split()
    total_kb, free_kb = int(df[1]), int(df[3])
    used_kb = int(docker("compose", "exec", "-T", "qdrant", "du", "-sk", "/qdrant/storage").split()[0])
    query = "import json,urllib.request; d=json.load(urllib.request.urlopen('http://qdrant:6333/collections',timeout=5)); print(len(d['result']['collections']))"
    collections = int(docker("compose", "exec", "-T", "api", "python", "-c", query))
    logs = docker("compose", "logs", "--no-color", "--since", "1h", "--tail", "500", "api", "ingestion-worker", "learning-worker")
    pool_timeouts = sum("QueuePool limit" in line or "event=db_pool_timeout" in line for line in logs.splitlines())
    free_percent = 100 * free_kb / total_kb
    connection_percent = 100 * pg["connections"] / pg["max_connections"]
    pool_code = "import pathlib,json; print(json.dumps({p.stem:json.loads(p.read_text()) for p in pathlib.Path('/logs/db-pools').glob('*.json')}))"
    pools = json.loads(docker("compose", "exec", "-T", "api", "python", "-c", pool_code))
    alerts = alerts_for(states, free_percent, connection_percent, pool_timeouts,
                        min_free=min_free, max_connections=max_connections)
    for service in ("api", "ingestion-worker", "learning-worker"):
        sample = pools.get(service, {})
        if time.time() - sample.get("sampled_at", 0) > 60:
            alerts.append(f"{service}: 连接池采样缺失或过期，检查运行覆盖配置和日志卷")
        elif set(sample.get("pools", {})) != {"platform", "knowledge"}:
            alerts.append(f"{service}: 双库连接池采样不完整")
    return {"containers": states, "postgres": pg,
            "data_filesystem_free_percent": round(free_percent, 2), "qdrant_storage_kib": used_kb,
            "qdrant_collections": collections, "recent_pool_timeout_lines": pool_timeouts,
            "process_pools": pools, "alerts": alerts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-free-percent", type=float, default=15)
    parser.add_argument("--max-connection-percent", type=float, default=80)
    args = parser.parse_args()
    if not 0 <= args.min_free_percent <= 100 or not 0 < args.max_connection_percent <= 100:
        parser.error("阈值必须在百分比范围内")
    try:
        result = inspect(args.min_free_percent, args.max_connection_percent)
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError) as exc:
        print(json.dumps({"status": "inspection_failed", "error_type": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["alerts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
