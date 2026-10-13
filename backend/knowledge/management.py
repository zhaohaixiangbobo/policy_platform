"""文件说明：封装空知识基线和受控导入流水线的唯一管理服务边界。"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import os
from pathlib import Path
from typing import Any, Callable

from knowledge.config import KnowledgePaths
from knowledge.indexing.config import EmbeddingContract, IndexConfig
from knowledge.indexing.database import IndexDatabase
from knowledge.indexing.embedding import OpenAIEmbeddingClient
from knowledge.indexing.indexer import PolicyIndexer
from knowledge.indexing.qdrant_store import QdrantVectorStore
from knowledge.metadata_rules import status_transition_error
from knowledge.parser.database import ParserDatabase
from knowledge.parser.pipeline import ParserConfig, PolicyParserPipeline
from knowledge.parser.review import ReviewService as ParseReviewService
from knowledge.metadata_service import KnowledgeMetadataService
from knowledge.parse_correction import ParseCorrectionService
from knowledge.chunking.chunker import ChunkerConfig, PolicyChunker
from knowledge.chunking.review import ChunkReviewService


class KnowledgeManagementService:
    """供CLI和单Worker复用，API路由通过服务访问知识库与Qdrant。"""

    def __init__(self, paths: KnowledgePaths, progress: Callable[[str], None] | None = None) -> None:
        self.paths = paths
        self.progress = progress or (lambda _message: None)

    def initialize_empty_baseline(self) -> dict[str, Any]:
        """独立初始化命令使用：创建受控目录及索引配置，不创建数据库表。"""

        directories = (
            self.paths.source_documents,
            self.paths.accepted_documents,
            self.paths.pdf_documents,
            self.paths.pending_documents,
            self.paths.temp_directory,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        parser_database = ParserDatabase(self.paths.database_url)
        parser_database.close()
        config = IndexConfig.from_environment()
        with IndexDatabase(self.paths.database_url) as index_database:
            profile = index_database.get_or_create_profile(config.profile_name, config.alias_name)
        return {
            "database": "knowledge-postgresql",
            "profile_name": profile["profile_name"],
            "alias_name": profile["alias_name"],
            "active_index_run_id": profile["active_index_run_id"],
        }

    def parse_pending_document(self, source: Path) -> dict[str, Any]:
        """创建不自动激活的ParseRun；审核通过前正式active指针保持不变。"""

        controlled_source = source.resolve()
        if not controlled_source.is_relative_to(self.paths.pending_documents.resolve()):
            raise ValueError("待解析文件不在受控pending目录")
        with PolicyParserPipeline(
            self.paths.database_url,
            self.paths.data_root,
            ParserConfig(
                render_pdf=True,
                render_engine=os.getenv("POLICY_DOCX_RENDER_ENGINE", "auto_headless"),
                libreoffice_path=os.getenv("POLICY_LIBREOFFICE_PATH"),
                auto_activate=False,
            ),
            progress=self.progress,
        ) as pipeline:
            return pipeline.parse(controlled_source)

    def approve_parse_run(self, run_id: int, reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """批准ParseRun并由知识模块原子切换active ParseRun。"""

        with ParseReviewService(self.paths.database_url) as service:
            return service.approve_run(run_id, reviewer_user_id, comment)

    def decide_parse_item(self, run_id: int, target_type: str, target_id: int, action: str, reviewer_user_id: str, comment: str | None, corrected_value: str | None = None) -> dict[str, Any]:
        """确认、忽略、驳回或更正单个ParseRun审核对象。"""

        with ParseReviewService(self.paths.database_url) as service:
            return service.decide(run_id=run_id, target_type=target_type, target_id=target_id, action=action, reviewed_by=reviewer_user_id, comment=comment, corrected_value=corrected_value)

    def decide_parse_items(self, run_id: int, target_type: str, target_ids: list[int], action: str, reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """原子批量处置当前ParseRun中的同类待审对象。"""

        with ParseReviewService(self.paths.database_url) as service:
            return service.decide_many(run_id=run_id, target_type=target_type, target_ids=target_ids, action=action, reviewed_by=reviewer_user_id, comment=comment)

    def decide_parse_article_title(self, run_id: int, node_id: int, mode: str, reviewer_user_id: str, title: str | None, comment: str | None) -> dict[str, Any]:
        """确认启发式条标题，或将对应文字恢复为条文正文。"""

        with ParserReviewService(self.paths.database_url) as service:
            return service.decide_article_title(
                run_id=run_id, node_id=node_id, mode=mode,
                reviewed_by=reviewer_user_id, title=title, comment=comment,
            )

    def ensure_metadata_draft(
        self,
        document_id: int,
        actor_user_id: str,
        initial_document_status: str = "effective",
    ) -> dict[str, Any]:
        """ParseRun通过后建立独立元数据草稿，等待专门页面确认。"""

        with KnowledgeMetadataService(self.paths.database_url) as service:
            return service.ensure_draft(
                document_id,
                actor_user_id,
                source_type="PARSE_EXTRACTED",
                change_reason="ParseRun结构审核通过后确认制度元数据；制度状态采用上传声明值",
                initial_document_status=initial_document_status,
            )

    def create_parse_correction(
        self,
        source_run_id: int,
        source_node_id: int,
        changes: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        """创建不覆盖历史的MANUAL_CORRECTION派生ParseRun。"""

        with ParseCorrectionService(self.paths.database_url) as service:
            return service.create(source_run_id, source_node_id, changes, actor_user_id)

    def build_chunk_run(self, document_id: int) -> dict[str, Any]:
        """基于已审核active ParseRun创建不自动激活的ChunkRun。"""

        with PolicyChunker(self.paths.database_url, ChunkerConfig()) as chunker:
            return chunker.run_document(document_id, activate=False)

    def approve_chunk_run(self, run_id: int, reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """批准ChunkRun并由知识模块原子切换active ChunkRun。"""

        with ChunkReviewService(self.paths.database_url) as service:
            return service.approve_run(run_id, reviewer_user_id, comment)

    def decide_chunk_item(self, run_id: int, target_type: str, target_id: int, action: str, reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """确认、忽略或驳回单个ChunkRun审核对象。"""

        with ChunkReviewService(self.paths.database_url) as service:
            return service.decide(chunk_run_id=run_id, target_type=target_type, target_id=target_id, action=action, reviewed_by=reviewer_user_id, comment=comment)

    def decide_chunk_items(self, run_id: int, target_ids: list[int], reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """原子批量接受当前ChunkRun中的普通质量问题。"""

        with ChunkReviewService(self.paths.database_url) as service:
            return service.decide_many(chunk_run_id=run_id, target_ids=target_ids, reviewed_by=reviewer_user_id, comment=comment)

    def reject_chunk_run(self, run_id: int, reviewer_user_id: str, comment: str | None) -> dict[str, Any]:
        """在知识库保留可审计的ChunkRun驳回结果。"""

        with ChunkReviewService(self.paths.database_url) as service:
            return service.reject_run(run_id, reviewer_user_id, comment)

    def build_index_run(
        self,
        required_document_ids: list[int] | None = None,
        frozen_sources: list[dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        """构建并核验IndexRun，不切换alias，等待管理员发布。"""

        endpoint = os.getenv("POLICY_EMBEDDING_URL", "http://10.9.7.1:8001/v1/embeddings")
        contract = EmbeddingContract(
            model=os.getenv("POLICY_EMBEDDING_MODEL", "qwen3-embedding-4b"),
            model_revision=os.getenv("POLICY_EMBEDDING_REVISION", "deployment-unreported"),
            dimension=int(os.getenv("POLICY_EMBEDDING_DIMENSION", "2560")),
        )
        config = IndexConfig.from_environment()
        embedding = OpenAIEmbeddingClient(
            endpoint,
            contract,
            api_key=os.getenv("POLICY_EMBEDDING_API_KEY"),
            timeout_seconds=config.request_timeout_seconds,
            max_retries=config.max_retries,
        )
        store = QdrantVectorStore(
            os.getenv("POLICY_QDRANT_URL", "http://127.0.0.1:6333"),
            api_key=os.getenv("POLICY_QDRANT_API_KEY"),
            timeout_seconds=config.request_timeout_seconds,
        )
        with PolicyIndexer(
            self.paths.database_url,
            embedding_client=embedding,
            vector_store=store,
            contract=contract,
            config=config,
        ) as indexer:
            return indexer.build(
                activate=False,
                required_document_ids=required_document_ids,
                frozen_sources=frozen_sources,
            )

    def active_index_snapshot(self) -> dict[str, Any]:
        """读取当前Alias对应IndexRun的完整来源，作为下一次发布的稳定基线。"""

        with IndexDatabase(self.paths.database_url) as database:
            profile = database.repository.run(sql_text('SELECT active_index_run_id FROM index_profile WHERE profile_name=:p0'), {'p0': IndexConfig.from_environment().profile_name}).mappings().fetchone()
            run_id = int(profile["active_index_run_id"]) if profile and profile["active_index_run_id"] is not None else None
            if run_id is None:
                return {"index_run_id": None, "sources": []}
            run = database.repository.run(sql_text('SELECT status,activation_status FROM index_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
            if run is None or run["status"] != "succeeded" or run["activation_status"] != "active":
                raise ValueError("当前active IndexRun状态异常，不能创建下一次发布请求")
            return {"index_run_id": run_id, "sources": self.index_run_sources(run_id)}

    def index_run_sources(self, run_id: int) -> list[dict[str, Any]]:
        """返回IndexRun冻结的精确来源版本，供Platform发布编排核对绑定。"""

        with IndexDatabase(self.paths.database_url) as database:
            rows = database.repository.run(sql_text("""
                SELECT document_id,parse_run_id,chunk_run_id,metadata_revision_id,
                       retrievable_count,source_digest
                FROM index_run_source WHERE index_run_id=:p0 ORDER BY document_id
                """), {'p0': run_id}).mappings().fetchall()
            return [dict(row) for row in rows]

    def publication_source(self, document_id: int, metadata_revision_id: int) -> dict[str, int]:
        """解析待发布修订对应的精确active ParseRun与ChunkRun版本。"""

        with ParserDatabase(self.paths.database_url) as database:
            row = database.repository.run(sql_text("""
                SELECT d.id AS document_id,d.active_parse_run_id,d.active_chunk_run_id,
                       mr.id AS metadata_revision_id,mr.parse_run_id AS metadata_parse_run_id,
                       mr.lifecycle_status,mr.source_type AS metadata_source_type,
                       mr.status AS metadata_document_status,cr.parse_run_id AS chunk_parse_run_id,
                       cr.status AS chunk_status,cr.review_status AS chunk_review_status
                FROM policy_document d
                JOIN document_metadata_revision mr ON mr.id=:p0 AND mr.document_id=d.id
                JOIN chunk_run cr ON cr.id=d.active_chunk_run_id
                WHERE d.id=:p1
                """), {'p0': metadata_revision_id, 'p1': document_id}).mappings().fetchone()
            if row is None:
                raise ValueError(f"制度 {document_id} 缺少待发布元数据或active ChunkRun")
            if row["lifecycle_status"] not in {"APPROVED", "PUBLISHED"}:
                raise ValueError(f"元数据修订 {metadata_revision_id} 尚未审核通过")
            if any(
                row[name] is None
                for name in ("active_parse_run_id", "metadata_parse_run_id", "chunk_parse_run_id")
            ):
                raise ValueError(f"制度 {document_id} 缺少完整的ParseRun来源")
            run_ids = {
                int(row["active_parse_run_id"]),
                int(row["metadata_parse_run_id"]),
                int(row["chunk_parse_run_id"]),
            }
            if len(run_ids) != 1:
                raise ValueError(f"制度 {document_id} 的ParseRun、ChunkRun和元数据版本不一致")
            if row["chunk_status"] != "succeeded" or row["chunk_review_status"] != "approved":
                raise ValueError(f"制度 {document_id} 的active ChunkRun尚未审核通过")
            transition_error = status_transition_error(
                str(row["metadata_source_type"]), row["metadata_document_status"]
            )
            if transition_error:
                raise ValueError(f"制度 {document_id} 的元数据生命周期不一致：{transition_error}")
            return {
                "document_id": int(row["document_id"]),
                "parse_run_id": int(row["active_parse_run_id"]),
                "chunk_run_id": int(row["active_chunk_run_id"]),
                "metadata_revision_id": int(row["metadata_revision_id"]),
            }

    def publish_index_run(self, run_id: int, *, recover_base=None, recover=False) -> dict[str, Any]:
        """管理员确认后原子切换Platform独立alias和active IndexRun。"""

        contract = EmbeddingContract(
            model=os.getenv("POLICY_EMBEDDING_MODEL", "qwen3-embedding-4b"),
            model_revision=os.getenv("POLICY_EMBEDDING_REVISION", "deployment-unreported"),
            dimension=int(os.getenv("POLICY_EMBEDDING_DIMENSION", "2560")),
        )
        config = IndexConfig.from_environment()
        embedding = OpenAIEmbeddingClient(
            os.getenv("POLICY_EMBEDDING_URL", "http://10.9.7.1:8001/v1/embeddings"),
            contract,
            api_key=os.getenv("POLICY_EMBEDDING_API_KEY"),
            timeout_seconds=config.request_timeout_seconds,
            max_retries=config.max_retries,
        )
        store = QdrantVectorStore(
            os.getenv("POLICY_QDRANT_URL", "http://127.0.0.1:6333"),
            api_key=os.getenv("POLICY_QDRANT_API_KEY"),
            timeout_seconds=config.request_timeout_seconds,
        )
        with PolicyIndexer(
            self.paths.database_url,
            embedding_client=embedding,
            vector_store=store,
            contract=contract,
            config=config,
        ) as indexer:
            if recover:
                return indexer.recover_activation(run_id, base_run_id=recover_base)
            return indexer.activate(run_id)
