"""文件说明：发布恢复默认只预览；执行须指定请求并确认旧Worker及其外部调用已结束。"""

import argparse
import json
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "var/postgres-dev/platform.env")
    parser.add_argument("--request-id")
    parser.add_argument("--job-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--action", choices=["publish-finish", "build-retry", "ingestion-fail"], default="publish-finish")
    parser.add_argument("--confirm-executor-stopped", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise ValueError("必须指定存在的PG配置文件")
    os.environ["PLATFORM_ENV_FILE"] = str(args.env_file.resolve())
    load_dotenv(args.env_file, override=True)
    sys.path.insert(0, str(ROOT / "backend"))
    from app.infrastructure.db.readiness import check_readiness
    from app.infrastructure.db.session import get_session_factory
    from app.application.publication_recovery import pending_recovery, recover_publication, requeue_interrupted_build
    from app.application.ingestion_recovery import pending_ingestion_recovery, mark_interrupted_ingestion
    from app.config import get_settings
    from knowledge.config import KnowledgePaths
    from knowledge.management import KnowledgeManagementService
    check_readiness()
    factory = get_session_factory()
    with factory() as session:
        print(json.dumps({"publications": pending_recovery(session), "ingestion": pending_ingestion_recovery(session)},
                         ensure_ascii=False, indent=2))
    if args.execute:
        target = args.job_id if args.action == "ingestion-fail" else args.request_id
        if not target or not args.confirm_executor_stopped:
            raise ValueError("执行需要对应任务ID和--confirm-executor-stopped")
        paths = KnowledgePaths(get_settings().knowledge_data_root)
        if args.action == "ingestion-fail":
            mark_interrupted_ingestion(factory, paths, args.job_id, executor_stopped=True)
            print("已登记中断原因；人工重试/返工仍通过既有业务流程")
        elif args.action == "build-retry":
            requeue_interrupted_build(factory, paths, args.request_id, executor_stopped=True)
            print("已重排同一冻结构建请求；Worker将校验来源并幂等构建，不自动确认发布")
        else:
            recover_publication(factory, KnowledgeManagementService(paths), paths, args.request_id,
                                executor_stopped=True)
            print("已核验当前Alias并完成发布收尾；未执行Embedding或切换Alias")


if __name__ == "__main__":
    main()
