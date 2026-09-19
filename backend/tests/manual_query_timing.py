"""文件说明：人工启动的三个慢问题真实复测，复用KnowledgeService并写独立诊断产物。

不创建聊天、不构建索引、不更改Alias；不由pytest自动运行。
"""

import asyncio
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.logging_config import configure_rotating_logger
from knowledge.rag.runtime import RagRuntimeSettings
from knowledge.service import KnowledgeService

QUESTIONS = (
    "行业级一等奖和省级一等奖的奖励标准一样吗？",
    "获得个人一等奖以后，奖金是税前还是税后？",
    "省级一类个人一等奖奖励50000元，对吗？",
)


async def main():
    """顺序复用同一Runtime，第一题含冷初始化；失败即停止。"""
    output = Path(__file__).resolve().parents[2] / "outputs" / ("query-timing-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    print(f"OUTPUT={output}", flush=True)
    configure_rotating_logger("policy_platform.api", level_name="INFO", log_file=str(output / "timing.log"), max_bytes=10000000, backup_count=1)
    service = KnowledgeService(RagRuntimeSettings.from_environment(db_path=get_settings().knowledge_database_path))
    results = []
    try:
        for index, question in enumerate(QUESTIONS, 1):
            request_id = "timing-" + uuid.uuid4().hex
            print(f"START {index}/3 request_id={request_id}", flush=True)
            result = await service.query(question, request_id, "CURRENT", "ALL")
            results.append({"request_id": request_id, "question": question, "response": result.model_dump()})
            (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"DONE {index}/3 seconds={result.latency_ms.total/1000:.3f} status={result.status}", flush=True)
    finally:
        await service.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
