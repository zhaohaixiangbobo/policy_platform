"""文件说明：有限次人工连接/输入对照诊断，不改变生产配置或重试策略。"""

import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge.rag.runtime import RagRuntimeSettings
from knowledge.rag.runtime import RagRuntime
from knowledge.retrieval import SearchFilters
from app.config import get_settings


def error_details(error):
    """仅提取连接异常链和系统错误码，不读取响应正文。"""
    output, seen, pending = [], set(), [error]
    while pending and len(output) < 10:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        output.append({"type": type(item).__name__, "errno": getattr(item, "errno", None), "winerror": getattr(item, "winerror", None)})
        pending.extend(value for value in (item.__cause__, item.__context__, getattr(item, "reason", None), *item.args) if isinstance(value, BaseException))
    return output


def main():
    settings = RagRuntimeSettings.from_environment(db_path=get_settings().knowledge_database_path)
    target = urlsplit(settings.rerank_url)
    payload = {"model": settings.rerank_model, "query": "奖金是税前还是税后？", "documents": ["本办法奖励均为税前金额。", "奖金由所在单位发放。"], "top_n": 2}
    input_comparison = "--input-comparison" in sys.argv
    real_candidates = "--real-candidates" in sys.argv or input_comparison
    if real_candidates:
        # 只召回候选，不调用答案Generator，不创建聊天记录。
        runtime = RagRuntime(settings)
        try:
            query = "省级一类个人一等奖奖励50000元，对吗？"
            candidates = runtime.dense.search(query, top_k=20, filters=SearchFilters(document_statuses=("effective",)))
            payload = {"model": settings.rerank_model, "query": query, "documents": [row["retrieval_text"] for row in candidates], "top_n": min(8, len(candidates))}
        finally:
            runtime.close()
    headers = {"Content-Type": "application/json"}
    if os.getenv("POLICY_RERANK_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["POLICY_RERANK_API_KEY"]
    output = Path(__file__).resolve().parents[2] / "outputs" / ("reranker-connections-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    print(f"OUTPUT={output}", flush=True)
    shared = requests.Session()
    shared.trust_env = False
    results = []
    try:
        modes = ("keep_alive",) * 6 if input_comparison else ("keep_alive", "fresh_close") * (2 if real_candidates else 3)
        # 固定同一批实际候选，交替原题、仅改金额、正常问题，隔离问题文本的影响。
        comparison_queries = ("省级一类个人一等奖奖励50000元，对吗？", "省级一类个人一等奖奖励10000元，对吗？", "获得个人一等奖以后，奖金是税前还是税后？")
        for index, mode in enumerate(modes, 1):
            if input_comparison:
                payload = {**payload, "query": comparison_queries[(index - 1) % 3]}
            session = shared if mode == "keep_alive" else requests.Session()
            session.trust_env = False
            request_headers = headers if mode == "keep_alive" else {**headers, "Connection": "close"}
            started = time.perf_counter()
            row = {"index": index, "mode": mode, "document_count": len(payload["documents"]), "time": time.strftime("%Y-%m-%d %H:%M:%S%z")}
            if input_comparison:
                row.update(query=payload["query"], candidate_characters=sum(map(len, payload["documents"])))
            print(f"START {index}/{len(modes)} {mode}", flush=True)
            try:
                response = session.post(settings.rerank_url, json=payload, headers=request_headers, timeout=(5, 15))
                row.update(status=response.status_code, server=response.headers.get("Server"), connection=response.headers.get("Connection"))
                if input_comparison and response.status_code == 200:
                    from knowledge.retrieval.reranker import OpenAIRerankClient
                    validator = OpenAIRerankClient(settings.rerank_url, runtime.reranker_contract, runtime.rerank_config)
                    try:
                        items, _ = validator._validate_response(response.json(), len(payload["documents"]), payload["top_n"])
                        row.update(valid_response=True, result_count=len(items))
                    finally:
                        validator.close()
                response.close()
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                row["errors"] = error_details(exc)
            finally:
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
                if mode == "fresh_close":
                    session.close()
            if "errors" in row:
                tcp_started = time.perf_counter()
                try:
                    with socket.create_connection((target.hostname, target.port or 80), timeout=3):
                        row["tcp_probe"] = "connected"
                except OSError as exc:
                    row["tcp_probe"] = error_details(exc)
                row["tcp_probe_ms"] = round((time.perf_counter() - tcp_started) * 1000, 3)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            if index < len(modes):
                time.sleep(1)
    finally:
        shared.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
