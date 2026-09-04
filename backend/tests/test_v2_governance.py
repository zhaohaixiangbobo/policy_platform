"""文件说明：验证V2制度系列、元数据修订和正式发布前置约束。"""

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError
from knowledge.indexing.config import EmbeddingContract, IndexConfig
from knowledge.indexing.indexer import PolicyIndexer
from knowledge.parser.review import ReviewService as ParseReviewService


def test_metadata_revision_requires_explicit_status_confirmation() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    now = "2026-08-31T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO policy_document (
                title, source_file, file_name, mime_type, file_size, parser_status,
                review_status, checksum, created_at, updated_at
            ) VALUES ('测试制度', 'pending/test.docx', 'test.docx',
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      100, 'succeeded', 'passed', 'v2-test-checksum', ?, ?)
            """,
            (now, now),
        )

    with KnowledgeMetadataService(paths.database_path) as service:
        item = service.list_documents()[0]
        revision_id = int(item["latest_metadata_revision_id"])
        service.update_draft(1, revision_id, {
            "issuing_org": "测试发布机构",
            "owner_department": "测试责任部门",
            "publish_date": "2026-08-31",
            "status": "unknown",
        })
        with pytest.raises(MetadataConflictError, match="保留原因"):
            service.submit(1, revision_id)
        service.update_draft(1, revision_id, {
            "status_confirmation_note": "原文件未明确效力状态，待业务部门确认",
        })
        pending = service.submit(1, revision_id)
        assert pending["lifecycle_status"] == "PENDING_REVIEW"
        approved = service.review(1, revision_id, True, "reviewer", "核对通过")
        assert approved["lifecycle_status"] == "APPROVED"
        assert service.detail(1)["document"]["approved_metadata_revision_id"] == revision_id


def test_initial_metadata_draft_uses_upload_declaration() -> None:
    """首次草稿采用上传声明值，后续是否生效仍由元数据审核和 Alias 发布决定。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    now = "2026-09-03T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO policy_document (
                title, source_file, file_name, mime_type, file_size, parser_status,
                review_status, checksum, created_at, updated_at
            ) VALUES ('历史制度', 'pending/history.docx', 'history.docx',
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      100, 'succeeded', 'passed', 'upload-status-test', ?, ?)
            """,
            (now, now),
        )

    with KnowledgeMetadataService(paths.database_path) as service:
        draft = service.ensure_draft(
            1,
            "uploader",
            source_type="PARSE_EXTRACTED",
            initial_document_status="repealed",
        )
        assert draft["status"] == "repealed"
        assert draft["lifecycle_status"] == "DRAFT"


def test_policy_document_is_a_version_under_policy_series() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    now = "2026-08-31T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        for index in (1, 2):
            connection.execute(
                """
                INSERT INTO policy_document (
                    title, source_file, file_name, mime_type, file_size, parser_status,
                    review_status, checksum, created_at, updated_at
                ) VALUES (?, ?, ?, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                          100, 'succeeded', 'passed', ?, ?, ?)
                """,
                (f"测试制度第{index}版", f"pending/{index}.docx", f"{index}.docx", f"series-checksum-{index}", now, now),
            )

    with KnowledgeMetadataService(paths.database_path) as service:
        first_series = int(service.list_documents()[1]["series_id"])
        second = service.assign_series(2, series_id=first_series, canonical_title="测试制度")
        assert second["series_id"] == first_series
        assert second["document_version_no"] == 2
        series = next(item for item in service.list_series() if item["id"] == first_series)
        assert series["document_count"] == 2


def test_manual_parse_correction_requires_node_confirmation_and_keeps_history() -> None:
    """结构修正应派生新运行，确认修正节点后才能批准，源运行保持不变。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    management = KnowledgeManagementService(paths)
    management.initialize_empty_baseline()
    now = "2026-08-31T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO policy_document (
                id,title,source_file,file_name,mime_type,file_size,parser_status,
                review_status,checksum,active_parse_run_id,latest_parse_run_id,created_at,updated_at
            ) VALUES (1,'测试制度','pending/test.docx','test.docx',
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      100,'succeeded','passed','correction-test',1,1,?,?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO parse_run (
                id,document_id,parser_version,config_hash,status,current_stage,started_at,
                finished_at,review_status,reviewed_by,reviewed_at
            ) VALUES (1,1,'test','parse','succeeded','completed',?,?,'approved','reviewer',?)
            """,
            (now, now, now),
        )
        connection.execute(
            """
            INSERT INTO policy_node (
                id,document_id,parse_run_id,temp_key,node_type,node_number,title,raw_text,
                content,normalized_content,level,path,path_text,page_start,page_end,order_no,
                parser_confidence,decision_method,review_status,created_at,updated_at
            ) VALUES (1,1,1,'node-1','article','第一条','旧标题','原文','原文','原文',1,
                      '1','第一条',1,1,1,1.0,'rule','confirmed',?,?)
            """,
            (now, now),
        )

    created = management.create_parse_correction(1, 1, {"title": "修正标题"}, "admin")
    derived_run_id = int(created["id"])
    derived_node_id = int(created["corrected_node_id"])
    with sqlite3.connect(paths.database_path) as connection:
        connection.row_factory = sqlite3.Row
        source = connection.execute("SELECT * FROM parse_run WHERE id=1").fetchone()
        derived = connection.execute("SELECT * FROM parse_run WHERE id=?", (derived_run_id,)).fetchone()
        node = connection.execute("SELECT * FROM policy_node WHERE id=?", (derived_node_id,)).fetchone()
        assert source["review_status"] == "approved"
        assert derived["parent_parse_run_id"] == 1
        assert derived["run_kind"] == "MANUAL_CORRECTION"
        assert node["title"] == "修正标题"
        assert node["review_status"] == "pending"

    with ParseReviewService(paths.database_path) as review:
        pending = review.refresh_state(derived_run_id)
        assert pending["nodes"] == 1
        ready = review.decide(
            run_id=derived_run_id,
            target_type="node",
            target_id=derived_node_id,
            action="confirm",
            reviewed_by="reviewer",
        )
        assert ready["review_status"] == "ready_for_approval"
        approved = review.approve_run(derived_run_id, "reviewer")
        assert approved["review_status"] == "approved"


class _UnusedEmbedding:
    def embed(self, texts):  # pragma: no cover - 激活测试不调用Embedding
        raise AssertionError(texts)


class _AliasStore:
    def __init__(self, target: str, fail: bool) -> None:
        self.target = target
        self.fail = fail

    def switch_alias(self, _alias_name: str, collection_name: str) -> None:
        if self.fail:
            raise RuntimeError("模拟Alias切换失败")
        self.target = collection_name

    def alias_target(self, _alias_name: str) -> str:
        return self.target


def test_alias_failure_keeps_old_metadata_and_old_index_active() -> None:
    """Alias切换失败时，不得提前发布候选元数据或切换SQLite active指针。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    now = "2026-08-31T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO policy_series (id,series_key,canonical_title,status,created_at,updated_at)
            VALUES (1,'series-1','测试制度','ACTIVE',?,?)
            """, (now, now),
        )
        connection.execute(
            """
            INSERT INTO policy_document (
                id,title,status,source_file,file_name,mime_type,file_size,parser_status,
                review_status,checksum,active_parse_run_id,active_chunk_run_id,series_id,
                approved_metadata_revision_id,active_metadata_revision_id,created_at,updated_at
            ) VALUES (1,'旧标题','effective','pending/test.docx','test.docx',
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      100,'succeeded','passed','alias-test',1,1,1,2,1,?,?)
            """, (now, now),
        )
        for revision_id, title, lifecycle in ((1, "旧标题", "PUBLISHED"), (2, "新标题", "APPROVED")):
            connection.execute(
                """
                INSERT INTO document_metadata_revision (
                    id,document_id,revision_no,source_type,title,status,lifecycle_status,
                    content_hash,created_at,updated_at
                ) VALUES (?,?,?,'MANUAL_CORRECTION',?,'effective',?,'hash',?,?)
                """, (revision_id, 1, revision_id, title, lifecycle, now, now),
            )
        connection.execute(
            "INSERT INTO parse_run (id,document_id,parser_version,config_hash,status,started_at,review_status) VALUES (1,1,'test','parse','succeeded',?,'approved')",
            (now,),
        )
        connection.execute(
            """
            INSERT INTO chunk_run (
                id,document_id,parse_run_id,chunker_version,strategy,config_json,config_hash,
                status,review_status,source_scope,started_at,created_at
            ) VALUES (1,1,1,'test','test','{}','chunk','succeeded','approved','active',?,?)
            """, (now, now),
        )
        profile_id = connection.execute("SELECT id FROM index_profile WHERE profile_name='policy_platform_dense'").fetchone()[0]
        base = (profile_id, "provider", "model", "rev", "{}", "contract", 8, "Cosine", "dense", "policy_platform_dense_active", "v1", "{}", "config", "test", "succeeded", now, now)
        connection.execute(
            """
            INSERT INTO index_run (
                id,profile_id,source_manifest_hash,embedding_provider,embedding_model,
                embedding_model_revision,embedding_contract_json,embedding_contract_hash,
                dimension,distance_metric,vector_name,collection_name,alias_name,
                point_schema_version,config_json,config_hash,indexer_version,status,
                activation_status,started_at,created_at
            ) VALUES (1,?,'old',?,?,?,?,?,?,?,?, 'collection-old',?,?,?,?,?,?,'active',?,?)
            """, base,
        )
        connection.execute(
            """
            INSERT INTO index_run (
                id,profile_id,source_manifest_hash,embedding_provider,embedding_model,
                embedding_model_revision,embedding_contract_json,embedding_contract_hash,
                dimension,distance_metric,vector_name,collection_name,alias_name,
                point_schema_version,config_json,config_hash,indexer_version,status,
                activation_status,started_at,created_at
            ) VALUES (2,?,'new',?,?,?,?,?,?,?,?, 'collection-new',?,?,?,?,?,?,'inactive',?,?)
            """, base,
        )
        for run_id, revision_id in ((1, 1), (2, 2)):
            connection.execute(
                """
                INSERT INTO index_run_source (
                    index_run_id,document_id,parse_run_id,chunk_run_id,metadata_revision_id,
                    retrievable_count,source_digest,created_at
                ) VALUES (?,1,1,1,?,1,?,?)
                """, (run_id, revision_id, f"digest-{run_id}", now),
            )
        connection.execute("UPDATE index_profile SET active_index_run_id=1,latest_index_run_id=2 WHERE id=?", (profile_id,))

    store = _AliasStore("collection-old", fail=True)
    with PolicyIndexer(paths.database_path, embedding_client=_UnusedEmbedding(), vector_store=store, contract=EmbeddingContract(dimension=8), config=IndexConfig(strict_source_freshness=True)) as indexer:
        with pytest.raises(RuntimeError, match="模拟Alias切换失败"):
            indexer.activate(2)
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT active_index_run_id FROM index_profile").fetchone()[0] == 1
        assert connection.execute("SELECT active_metadata_revision_id,title FROM policy_document WHERE id=1").fetchone() == (1, "旧标题")
        assert connection.execute("SELECT lifecycle_status FROM document_metadata_revision WHERE id=2").fetchone()[0] == "APPROVED"

    store.fail = False
    with PolicyIndexer(paths.database_path, embedding_client=_UnusedEmbedding(), vector_store=store, contract=EmbeddingContract(dimension=8), config=IndexConfig(strict_source_freshness=True)) as indexer:
        indexer.activate(2)
    with sqlite3.connect(paths.database_path) as connection:
        assert store.target == "collection-new"
        assert connection.execute("SELECT active_index_run_id FROM index_profile").fetchone()[0] == 2
        assert connection.execute("SELECT active_metadata_revision_id,title FROM policy_document WHERE id=1").fetchone() == (2, "新标题")
        assert connection.execute("SELECT lifecycle_status FROM document_metadata_revision WHERE id=1").fetchone()[0] == "SUPERSEDED"
        assert connection.execute("SELECT lifecycle_status FROM document_metadata_revision WHERE id=2").fetchone()[0] == "PUBLISHED"
