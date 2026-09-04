"""文件说明：验证全新空知识基线不依赖迁移制度且目录接口稳定返回空结果。"""

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from knowledge.catalog import CatalogDocumentNotFoundError, KnowledgeCatalogService
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService


def test_empty_catalog_is_available() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    test_root = runtime_root / uuid4().hex
    test_root.mkdir(parents=True)
    paths = KnowledgePaths(test_root / "knowledge")
    baseline = KnowledgeManagementService(paths).initialize_empty_baseline()
    catalog = KnowledgeCatalogService(paths)
    documents, total = catalog.list_documents(keyword=None, status=None, issuer=None, department=None, publish_date_from=None, publish_date_to=None, sort_by="updated_at", sort_order="desc", page=1, page_size=20)

    assert documents == []
    assert total == 0
    assert catalog.list_facets() == {"statuses": [], "issuers": [], "departments": []}
    assert baseline["profile_name"] == "policy_platform_dense"
    assert baseline["alias_name"] == "policy_platform_dense_active"
    assert baseline["active_index_run_id"] is None


def test_catalog_only_exposes_documents_in_active_index_run() -> None:
    """Parse/Chunk已激活仍不等于发布，制度库只读取当前active IndexRun清单。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    paths = KnowledgePaths(runtime_root / uuid4().hex / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    connection = sqlite3.connect(paths.database_path)
    now = "2026-08-30T00:00:00+00:00"
    for document_id in (1, 2):
        connection.execute(
            """
            INSERT INTO policy_document (
                id,title,source_file,file_name,mime_type,file_size,parser_status,
                review_status,checksum,active_parse_run_id,active_chunk_run_id,
                created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id, f"测试制度{document_id}", f"source/{document_id}.docx",
                f"{document_id}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                100, "succeeded", "passed", f"checksum-{document_id}", document_id,
                document_id, now, now,
            ),
        )
        connection.execute(
            """
            INSERT INTO parse_run (
                id,document_id,parser_version,config_hash,status,current_stage,
                started_at,review_status
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (document_id, document_id, "test", f"parse-{document_id}", "succeeded", "completed", now, "approved"),
        )
        connection.execute(
            """
            INSERT INTO chunk_run (
                id,document_id,parse_run_id,chunker_version,strategy,config_json,
                config_hash,status,review_status,source_scope,started_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (document_id, document_id, document_id, "test", "test", "{}", f"chunk-{document_id}", "succeeded", "approved", "active", now, now),
        )
        connection.execute(
            """
            INSERT INTO document_metadata_revision (
                id,document_id,revision_no,source_type,title,status,lifecycle_status,
                content_hash,created_at,updated_at
            ) VALUES (?,?,1,'BACKFILL',?,'effective','PUBLISHED',?,?,?)
            """,
            (document_id, document_id, f"测试制度{document_id}", f"metadata-{document_id}", now, now),
        )
        connection.execute(
            """
            UPDATE policy_document SET active_metadata_revision_id=?,approved_metadata_revision_id=?,
                latest_metadata_revision_id=? WHERE id=?
            """,
            (document_id, document_id, document_id, document_id),
        )

    profile_id = int(connection.execute("SELECT id FROM index_profile WHERE profile_name='policy_platform_dense'").fetchone()[0])
    connection.execute(
        """
        INSERT INTO index_run (
            id,profile_id,source_manifest_hash,embedding_provider,embedding_model,
            embedding_model_revision,embedding_contract_json,embedding_contract_hash,
            dimension,distance_metric,vector_name,collection_name,alias_name,
            point_schema_version,config_json,config_hash,indexer_version,status,
            activation_status,started_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (1, profile_id, "manifest", "test", "test", "test", "{}", "embedding", 8, "Cosine", "dense", "collection-test", "policy_platform_dense_active", "v1", "{}", "config", "test", "succeeded", "active", now, now),
    )
    connection.execute(
        """
        INSERT INTO index_run_source (
            index_run_id,document_id,parse_run_id,chunk_run_id,metadata_revision_id,retrievable_count,
            source_digest,created_at
        ) VALUES (1,1,1,1,1,1,'digest-1',?)
        """,
        (now,),
    )
    connection.execute("UPDATE index_profile SET active_index_run_id=1 WHERE id=?", (profile_id,))
    # 候选Parse/Chunk和缓存元数据变化时，公开目录仍读取active IndexRun冻结快照。
    connection.execute(
        "UPDATE policy_document SET title='未发布候选标题',active_parse_run_id=2,active_chunk_run_id=2 WHERE id=1"
    )
    connection.execute(
        """
        INSERT INTO policy_node (
            id,document_id,parse_run_id,temp_key,node_type,node_number,title,raw_text,
            level,order_no,parser_confidence,decision_method,review_status,created_at,updated_at
        ) VALUES (1,1,1,'node-1','article','第四条','行业省级一类竞赛获奖奖励标准：',
                  '第四条 行业省级一类竞赛获奖奖励标准：',1,1,1.0,'test','confirmed',?,?)
        """,
        (now, now),
    )
    connection.commit()
    connection.close()

    catalog = KnowledgeCatalogService(paths)
    documents, total = catalog.list_documents(keyword=None, status=None, issuer=None, department=None, publish_date_from=None, publish_date_to=None, sort_by="updated_at", sort_order="desc", page=1, page_size=20)

    assert total == 1
    assert [item.id for item in documents] == [1]
    assert documents[0].title == "测试制度1"
    _parse_run_id, nodes = catalog.list_nodes(1)
    assert nodes[0].node_number == "第四条"
    assert nodes[0].title == "第四条 行业省级一类竞赛获奖奖励标准："
    with pytest.raises(CatalogDocumentNotFoundError):
        catalog.get_document(2)
