"""文件说明：统一提供制度导入、解析、审核、分块、索引和问答命令。

CLI只负责参数解析和结果输出，所有核心行为复用knowledge模块服务；默认不自动激活
ParseRun、ChunkRun或IndexRun。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .chunking.chunker import ChunkerConfig, PolicyChunker
from .chunking.review import ChunkReviewService
from .config import KnowledgePaths
from .indexing.config import EmbeddingContract, IndexConfig
from .indexing.embedding import OpenAIEmbeddingClient
from .indexing.indexer import PolicyIndexer
from .indexing.qdrant_store import QdrantVectorStore
from .parser.pipeline import ParserConfig, PolicyParserPipeline
from .parser.review import ReviewService
from .rag.runtime import RagRuntime, RagRuntimeSettings


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    return Path(
        os.getenv("POLICY_KNOWLEDGE_DATA_ROOT", PROJECT_ROOT / "var" / "knowledge")
    ).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="制度知识模块统一命令行")
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    commands = parser.add_subparsers(dest="command", required=True)

    import_command = commands.add_parser("import", help="复制原始DOCX到受控目录")
    import_command.add_argument("source", type=Path)

    parse_command = commands.add_parser("parse", help="创建ParseRun")
    parse_command.add_argument("input", type=Path)
    parse_command.add_argument("--no-render", action="store_true")
    parse_command.add_argument(
        "--auto-activate", action="store_true",
        help="兼容参数，正式激活已禁用；请使用review-parse显式批准",
    )

    parse_review = commands.add_parser("review-parse", help="审核ParseRun")
    parse_review.add_argument("--run-id", type=int, required=True)
    parse_review.add_argument("--reviewed-by", default="local-admin")
    parse_review.add_argument("--comment")
    parse_review.add_argument("--approve-run", action="store_true")
    parse_review.add_argument("--target-type", choices=("issue", "field", "node"))
    parse_review.add_argument("--target-id", type=int)
    parse_review.add_argument("--action", choices=("confirm", "reject", "ignore", "correct"))
    parse_review.add_argument("--corrected-value")

    chunk_command = commands.add_parser("chunk", help="创建ChunkRun")
    selector = chunk_command.add_mutually_exclusive_group(required=True)
    selector.add_argument("--all-active", action="store_true")
    selector.add_argument("--document-id", type=int)
    selector.add_argument("--parse-run-id", type=int)
    chunk_command.add_argument("--allow-unreviewed", action="store_true")
    chunk_command.add_argument(
        "--activate", action="store_true",
        help="兼容参数，正式激活已禁用；请使用review-chunk显式批准",
    )

    chunk_review = commands.add_parser("review-chunk", help="审核ChunkRun")
    chunk_review.add_argument("--run-id", type=int, required=True)
    chunk_review.add_argument("--reviewed-by", default="local-admin")
    chunk_review.add_argument("--comment")
    chunk_review.add_argument("--approve-run", action="store_true")
    chunk_review.add_argument("--reject-run", action="store_true")
    chunk_review.add_argument("--target-type", choices=("chunk_issue", "chunk"))
    chunk_review.add_argument("--target-id", type=int)
    chunk_review.add_argument("--action", choices=("confirm", "ignore", "reject"))

    index_command = commands.add_parser("index", help="构建或发布IndexRun")
    index_command.add_argument("--embedding-url", default=os.getenv("POLICY_EMBEDDING_URL"))
    index_command.add_argument(
        "--embedding-model", default=os.getenv("POLICY_EMBEDDING_MODEL", "qwen3-embedding-4b")
    )
    index_command.add_argument(
        "--embedding-revision",
        default=os.getenv("POLICY_EMBEDDING_REVISION", "deployment-unreported"),
    )
    index_command.add_argument(
        "--qdrant-url", default=os.getenv("POLICY_QDRANT_URL", "http://127.0.0.1:6333")
    )
    index_command.add_argument("--publish", action="store_true")
    index_command.add_argument("--activate-run", type=int)

    query_command = commands.add_parser("query", help="执行一次完整制度问答")
    query_command.add_argument("question")
    query_command.add_argument("--debug", action="store_true")
    return parser


def import_document(paths: KnowledgePaths, source: Path) -> dict[str, Any]:
    source = source.resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise ValueError("只允许导入存在的DOCX文件")
    paths.source_documents.mkdir(parents=True, exist_ok=True)
    destination = (paths.source_documents / source.name).resolve()
    if not destination.is_relative_to(paths.source_documents):
        raise ValueError("DOCX文件名超出受控目录")
    source_hash = sha256_file(source)
    if destination.exists() and sha256_file(destination) != source_hash:
        destination = paths.source_documents / f"{source.stem}__{source_hash[:12]}.docx"
    shutil.copy2(source, destination)
    return {"path": destination.relative_to(paths.data_root).as_posix(), "sha256": source_hash}


def run(args: argparse.Namespace) -> Any:
    paths = KnowledgePaths(args.data_root)
    if args.command == "import":
        return import_document(paths, args.source)
    if args.command == "parse":
        source = args.input
        if not source.is_absolute():
            source = paths.source_documents / source
        with PolicyParserPipeline(
            paths.database_path,
            paths.data_root,
            ParserConfig(
                render_pdf=not args.no_render,
                auto_activate=args.auto_activate,
            ),
        ) as pipeline:
            return pipeline.parse(source)
    if args.command == "review-parse":
        with ReviewService(paths.database_path) as service:
            if args.approve_run:
                return service.approve_run(args.run_id, args.reviewed_by, args.comment)
            if args.target_type is None or args.target_id is None or args.action is None:
                raise ValueError("非批准操作必须提供target-type、target-id和action")
            return service.decide(
                run_id=args.run_id,
                target_type=args.target_type,
                target_id=args.target_id,
                action=args.action,
                reviewed_by=args.reviewed_by,
                comment=args.comment,
                corrected_value=args.corrected_value,
            )
    if args.command == "chunk":
        with PolicyChunker(paths.database_path, ChunkerConfig()) as chunker:
            if args.all_active:
                return chunker.run_all_active(activate=args.activate)
            if args.document_id is not None:
                return chunker.run_document(args.document_id, activate=args.activate)
            return chunker.run_parse_run(
                args.parse_run_id,
                allow_unreviewed=args.allow_unreviewed,
                activate=args.activate,
            )
    if args.command == "review-chunk":
        with ChunkReviewService(paths.database_path) as service:
            if args.approve_run:
                return service.approve_run(args.run_id, args.reviewed_by, args.comment)
            if args.reject_run:
                return service.reject_run(args.run_id, args.reviewed_by, args.comment)
            if args.target_type is None or args.target_id is None or args.action is None:
                raise ValueError("审核对象操作必须提供target-type、target-id和action")
            return service.decide(
                chunk_run_id=args.run_id,
                target_type=args.target_type,
                target_id=args.target_id,
                action=args.action,
                reviewed_by=args.reviewed_by,
                comment=args.comment,
            )
    if args.command == "index":
        if not args.embedding_url:
            raise ValueError("必须设置POLICY_EMBEDDING_URL或--embedding-url")
        contract = EmbeddingContract(
            model=args.embedding_model,
            model_revision=args.embedding_revision,
            dimension=2560,
        )
        config = IndexConfig(
            profile_name="policy_platform_dense",
            alias_name="policy_platform_dense_active",
            collection_prefix="policy_platform_dense",
        )
        embedding = OpenAIEmbeddingClient(args.embedding_url, contract)
        store = QdrantVectorStore(args.qdrant_url)
        with PolicyIndexer(
            paths.database_path,
            embedding_client=embedding,
            vector_store=store,
            contract=contract,
            config=config,
        ) as indexer:
            if args.activate_run is not None:
                return indexer.activate(args.activate_run)
            return indexer.build(activate=args.publish)
    if args.command == "query":
        settings = RagRuntimeSettings.from_environment(db_path=paths.database_path)
        with RagRuntime(settings) as runtime:
            return runtime.query(args.question, include_debug=args.debug).to_dict(
                include_debug=args.debug
            )
    raise ValueError(f"未知命令：{args.command}")


def main() -> int:
    args = build_parser().parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
