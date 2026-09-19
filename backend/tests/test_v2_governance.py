"""文件说明：验证V2制度系列、元数据修订和正式发布前置约束。"""

import os
import sqlite3
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError
from knowledge.indexing.config import EmbeddingContract, IndexConfig
from knowledge.indexing.database import IndexDatabase
from knowledge.indexing.indexer import PolicyIndexer
from knowledge.parser.database import ParserDatabase
from knowledge.parser.review import ReviewService as ParseReviewService


def _insert_reviewable_document(paths: KnowledgePaths, title: str, checksum: str) -> int:
    """按正常建档路径建立带active ParseRun的最小制度。"""

    with ParserDatabase(paths.database_path) as database:
        document_id = database.get_or_create_document({
            "source_file": f"pending/{checksum}.docx",
            "file_name": f"{checksum}.docx",
            "file_size": 100,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "checksum": checksum,
        })
        parse_run_id = database.create_parse_run(document_id, "test", f"parse-{checksum}")
        database.update_run(parse_run_id, status="succeeded", review_status="approved")
        database.update_document(
            document_id,
            title=title,
            parser_status="succeeded",
            review_status="passed",
            latest_parse_run_id=parse_run_id,
            active_parse_run_id=parse_run_id,
        )
        return document_id


def _publish_initial_metadata(paths: KnowledgePaths, document_id: int) -> int:
    """建立可供废止/失效测试使用的现行有效正式元数据。"""

    with KnowledgeMetadataService(paths.database_path) as service:
        draft = service.ensure_draft(
            document_id,
            "uploader",
            source_type="PARSE_EXTRACTED",
            initial_document_status="effective",
        )
        revision_id = int(draft["id"])
        service.update_draft(document_id, revision_id, {
            "issuing_org": "测试发布机构",
            "owner_department": "测试责任部门",
            "publish_date": "2026-09-14",
        })
        service.submit(document_id, revision_id)
        service.review(document_id, revision_id, True, "reviewer", "初始元数据通过")
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            "UPDATE document_metadata_revision SET lifecycle_status='PUBLISHED' WHERE id=?",
            (revision_id,),
        )
        connection.execute(
            "UPDATE policy_document SET active_metadata_revision_id=? WHERE id=?",
            (revision_id, document_id),
        )
    return revision_id


def test_metadata_revision_requires_explicit_status_confirmation() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "测试制度", "v2-test-checksum")

    with KnowledgeMetadataService(paths.database_path) as service:
        draft = service.ensure_draft(
            document_id, "uploader", source_type="PARSE_EXTRACTED", initial_document_status="effective"
        )
        revision_id = int(draft["id"])
        service.update_draft(document_id, revision_id, {
            "issuing_org": "测试发布机构",
            "owner_department": "测试责任部门",
            "publish_date": "2026-08-31",
            "status": "unknown",
        })
        with pytest.raises(MetadataConflictError, match="保留原因"):
            service.submit(document_id, revision_id)
        service.update_draft(document_id, revision_id, {
            "status_confirmation_note": "原文件未明确效力状态，待业务部门确认",
        })
        pending = service.submit(document_id, revision_id)
        assert pending["lifecycle_status"] == "PENDING_REVIEW"
        approved = service.review(document_id, revision_id, True, "reviewer", "核对通过")
        assert approved["lifecycle_status"] == "APPROVED"
        assert service.detail(document_id)["document"]["approved_metadata_revision_id"] == revision_id


def test_initial_metadata_draft_uses_upload_declaration() -> None:
    """首次草稿采用上传声明值，后续是否生效仍由元数据审核和 Alias 发布决定。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "历史制度", "upload-status-test")

    with KnowledgeMetadataService(paths.database_path) as service:
        draft = service.ensure_draft(
            document_id,
            "uploader",
            source_type="PARSE_EXTRACTED",
            initial_document_status="repealed",
        )
        assert draft["status"] == "repealed"
        assert draft["lifecycle_status"] == "DRAFT"


def test_repeal_and_expiry_use_separate_forced_status_flows() -> None:
    """生命周期草稿不继承effective，且服务端拒绝把动作保存成错误状态。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()

    repeal_document_id = _insert_reviewable_document(paths, "待废止制度", "repeal-flow")
    _publish_initial_metadata(paths, repeal_document_id)
    with KnowledgeMetadataService(paths.database_path) as service:
        repeal = service.ensure_draft(
            repeal_document_id, "admin", source_type="REPEAL", change_reason="登记制度废止"
        )
        assert repeal["status"] == "repealed"
        assert repeal["repeal_date"] == date.today().isoformat()
        with pytest.raises(MetadataConflictError, match="必须为已废止"):
            service.update_draft(
                repeal_document_id, int(repeal["id"]), {"status": "effective"}
            )
        service.update_draft(
            repeal_document_id, int(repeal["id"]), {"repeal_date": None}
        )
        with pytest.raises(MetadataConflictError, match="废止日期"):
            service.submit(repeal_document_id, int(repeal["id"]))
        service.update_draft(repeal_document_id, int(repeal["id"]), {
            "repeal_date": "2026/09/14",
            "repeal_reason": "测试废止流程",
            "repeal_evidence": "测试审批依据",
        })
        with pytest.raises(MetadataConflictError, match="YYYY-MM-DD"):
            service.submit(repeal_document_id, int(repeal["id"]))
        service.update_draft(repeal_document_id, int(repeal["id"]), {
            "repeal_date": "2026-09-14",
            "repeal_reason": "测试废止流程",
            "repeal_evidence": "测试审批依据",
        })
        pending = service.submit(repeal_document_id, int(repeal["id"]))
        assert pending["lifecycle_status"] == "PENDING_REVIEW"
        approved = service.review(
            repeal_document_id, int(repeal["id"]), True, "reviewer", "废止信息通过"
        )
        assert approved["status"] == "repealed"

    expiry_document_id = _insert_reviewable_document(paths, "待失效制度", "expiry-flow")
    _publish_initial_metadata(paths, expiry_document_id)
    with KnowledgeMetadataService(paths.database_path) as service:
        expiry = service.ensure_draft(expiry_document_id, "admin", source_type="EXPIRY")
        assert expiry["status"] == "expired"
        with pytest.raises(MetadataConflictError, match="失效日期"):
            service.submit(expiry_document_id, int(expiry["id"]))
        service.update_draft(expiry_document_id, int(expiry["id"]), {
            "expiry_date": "2026.12.31",
            "change_reason": "有效期届满",
        })
        with pytest.raises(MetadataConflictError, match="YYYY-MM-DD"):
            service.submit(expiry_document_id, int(expiry["id"]))
        service.update_draft(expiry_document_id, int(expiry["id"]), {
            "expiry_date": "2026-12-31",
            "change_reason": "有效期届满",
        })
        assert service.submit(expiry_document_id, int(expiry["id"]))["status"] == "expired"


def test_manual_correction_cannot_replace_lifecycle_actions() -> None:
    """普通元数据修订不能绕过废止或失效的专用审核流程。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "现行制度", "correction-status")
    _publish_initial_metadata(paths, document_id)

    with KnowledgeMetadataService(paths.database_path) as service:
        correction = service.ensure_draft(
            document_id, "admin", source_type="MANUAL_CORRECTION"
        )
        with pytest.raises(MetadataConflictError, match="登记废止或登记失效"):
            service.update_draft(document_id, int(correction["id"]), {"status": "expired"})


def test_not_required_chunk_run_cannot_enter_formal_publication() -> None:
    """零问题ChunkRun没有人工批准记录时，active指针也不能绕过发布门禁。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "待审核制度", "not-required-chunk")
    with KnowledgeMetadataService(paths.database_path) as metadata:
        draft = metadata.ensure_draft(
            document_id, "uploader", source_type="PARSE_EXTRACTED",
            initial_document_status="effective",
        )
        revision_id = int(draft["id"])
        metadata.update_draft(document_id, revision_id, {
            "issuing_org": "测试机构", "owner_department": "测试部门",
            "publish_date": "2026-09-05", "status": "effective",
        })
        metadata.submit(document_id, revision_id)
        metadata.review(document_id, revision_id, True, "reviewer", "元数据通过")
    now = "2026-09-05T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        parse_run_id = connection.execute(
            "SELECT active_parse_run_id FROM policy_document WHERE id=?", (document_id,)
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO chunk_run (
                document_id,parse_run_id,chunker_version,strategy,config_json,config_hash,
                status,review_status,source_scope,started_at,created_at
            ) VALUES (?,?,'test','test','{}','not-required','succeeded','not_required','active',?,?)
            """,
            (document_id, parse_run_id, now, now),
        )
        chunk_run_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE policy_document SET active_chunk_run_id=? WHERE id=?",
            (chunk_run_id, document_id),
        )

    management = KnowledgeManagementService(paths)
    with pytest.raises(ValueError, match="active ChunkRun尚未审核通过"):
        management.publication_source(document_id, revision_id)
    with IndexDatabase(paths.database_path) as database:
        with pytest.raises(ValueError, match="尚未通过审核"):
            database.freeze_active_sources([document_id])


def test_inconsistent_repeal_revision_cannot_enter_publication() -> None:
    """历史遗留的REPEAL+effective组合必须在索引构建前被明确拦截。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "错误废止制度", "invalid-repeal")
    revision_id = _publish_initial_metadata(paths, document_id)
    now = "2026-09-14T00:00:00+00:00"
    with sqlite3.connect(paths.database_path) as connection:
        parse_run_id = int(connection.execute(
            "SELECT active_parse_run_id FROM policy_document WHERE id=?", (document_id,)
        ).fetchone()[0])
        cursor = connection.execute(
            """
            INSERT INTO chunk_run (
                document_id,parse_run_id,chunker_version,strategy,config_json,config_hash,
                status,review_status,source_scope,started_at,created_at
            ) VALUES (?,?,'test','test','{}','invalid-repeal','succeeded','approved','active',?,?)
            """,
            (document_id, parse_run_id, now, now),
        )
        connection.execute(
            "UPDATE policy_document SET active_chunk_run_id=? WHERE id=?",
            (int(cursor.lastrowid), document_id),
        )
        connection.execute(
            "UPDATE document_metadata_revision SET source_type='REPEAL',status='effective' WHERE id=?",
            (revision_id,),
        )

    with pytest.raises(ValueError, match="必须为已废止"):
        KnowledgeManagementService(paths).publication_source(document_id, revision_id)


def test_policy_document_is_a_version_under_policy_series() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    first_document_id = _insert_reviewable_document(paths, "测试制度第1版", "series-checksum-1")
    second_document_id = _insert_reviewable_document(paths, "测试制度第2版", "series-checksum-2")

    with KnowledgeMetadataService(paths.database_path) as service:
        first_document = next(
            item for item in service.list_documents() if int(item["id"]) == first_document_id
        )
        first_series = int(first_document["series_id"])
        second = service.assign_series(
            second_document_id, series_id=first_series, canonical_title="测试制度"
        )
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


def test_unpublished_manual_revision_can_be_withdrawn() -> None:
    """撤回只结束候选修订，不改变当前正式生效的元数据。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    document_id = _insert_reviewable_document(paths, "撤回测试制度", "withdraw-metadata")
    active_revision_id = _publish_initial_metadata(paths, document_id)

    with KnowledgeMetadataService(paths.database_path) as service:
        draft = service.ensure_draft(
            document_id, "admin", source_type="REPEAL", change_reason="测试登记废止"
        )
        revision_id = int(draft["id"])
        service.update_draft(document_id, revision_id, {
            "repeal_reason": "测试原因",
            "repeal_evidence": "测试依据",
        })
        service.submit(document_id, revision_id)
        service.review(document_id, revision_id, True, "reviewer", "审核通过")

        withdrawn = service.withdraw(document_id, revision_id)
        detail = service.detail(document_id)

    assert withdrawn["lifecycle_status"] == "WITHDRAWN"
    assert detail["document"]["active_metadata_revision_id"] == active_revision_id
    assert detail["document"]["approved_metadata_revision_id"] == active_revision_id
