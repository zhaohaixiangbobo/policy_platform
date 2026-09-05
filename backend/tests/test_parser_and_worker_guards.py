"""文件说明：验证解析阈值、Worker与审核服务失败运行守卫的最小契约。"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from knowledge.chunking.review import ChunkReviewService
from knowledge.chunking.chunker import PolicyChunker
from knowledge.parser.analyzer import build_nodes, classify_article_remainder, validate_structure
from knowledge.parser.database import ParserDatabase, utc_now
from knowledge.parser.pipeline import ParserConfig
from knowledge.parser.review import ReviewService as ParseReviewService
from worker import KnowledgeRunFailedError, ensure_knowledge_run_succeeded


def _coverage_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    blocks = [
        {"temp_key": "mapped", "raw_text": "甲" * 96, "clean_text": "甲" * 96, "part_type": "document", "block_type": "paragraph", "excluded_role": "none"},
        {"temp_key": "unmapped", "raw_text": "乙" * 4, "clean_text": "乙" * 4, "part_type": "document", "block_type": "paragraph", "excluded_role": "none"},
    ]
    nodes = [
        {"source_block_key": "mapped", "raw_text": "甲" * 96, "node_type": "paragraph", "node_number": None, "parser_confidence": 1.0},
    ]
    return blocks, nodes


def test_character_coverage_uses_parser_configuration() -> None:
    blocks, nodes = _coverage_fixture()
    issues, _metrics = validate_structure(
        blocks,
        nodes,
        {},
        character_error_threshold=0.90,
        character_review_threshold=0.97,
    )

    coverage_issue = next(issue for issue in issues if issue["issue_code"] == "REVIEW_CHARACTER_COVERAGE")
    assert coverage_issue["details"]["threshold"] == 0.97
    assert "97.0%" in coverage_issue["message"]


def test_parser_configuration_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="error <= review"):
        ParserConfig(character_error_threshold=0.99, character_review_threshold=0.98)


def test_parser_configuration_rejects_automatic_activation() -> None:
    with pytest.raises(ValueError, match="自动激活已禁用"):
        ParserConfig(auto_activate=True)


def test_article_title_rules_prioritize_structure_and_expose_heuristic_review() -> None:
    """长条标题可由冒号强证据识别，模糊短标题必须进入人工复核。"""

    strong = classify_article_remainder(
        "关于专业技能竞赛表彰奖励范围和标准的具体规定：", "（一）国家级竞赛"
    )
    normative = classify_article_remainder(
        "有下列情形之一的，应当予以奖励：", "（一）获得一等奖"
    )
    assert strong == {
        "kind": "strong", "title": "关于专业技能竞赛表彰奖励范围和标准的具体规定", "needs_review": False,
    }
    assert normative["kind"] == "content"

    def block(key: str, text: str) -> dict[str, object]:
        return {
            "temp_key": key, "raw_text": text, "clean_text": text,
            "part_type": "document", "block_type": "paragraph",
            "excluded_role": "none", "properties": {},
        }

    blocks = [block("b1", "第四条 奖励发放"), block("b2", "（一）按月发放")]
    nodes = build_nodes(blocks)
    issues, _metrics = validate_structure(blocks, nodes, {})
    assert nodes[0]["title"] == "奖励发放"
    assert nodes[0]["review_status"] == "pending"
    assert nodes[0]["rule_id"] == "NODE_ARTICLE_TITLE_HEURISTIC_V2"
    assert any(item["issue_code"] == "NODE_ARTICLE_TITLE_HEURISTIC" for item in issues)


def test_human_can_restore_heuristic_article_title_to_content() -> None:
    """人工调整必须关闭关联问题、恢复正文并同步重算后代路径。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    database_path = runtime_root / uuid4().hex / "knowledge" / "policy_parser.db"
    database_path.parent.mkdir(parents=True)
    now = utc_now()
    with ParserDatabase(database_path) as database:
        document_id = database.get_or_create_document({
            "source_file": "pending/article.docx", "file_name": "article.docx",
            "file_size": 10, "mime_type": "application/docx", "checksum": uuid4().hex,
        })
        run_id = database.create_parse_run(document_id, "0.1.4", "article-title-v2")
        parent = database.connection.execute(
            """
            INSERT INTO policy_node (
                document_id,parse_run_id,temp_key,node_type,node_number,title,raw_text,
                content,normalized_content,level,path_text,order_no,parser_confidence,
                decision_method,rule_id,review_status,review_reason,created_at,updated_at
            ) VALUES (?,?,?,'article','第四条','奖励发放',?,NULL,?,1,'奖励发放',1,
                      0.99,'rule','NODE_ARTICLE_TITLE_HEURISTIC_V2','pending','待确认',?,?)
            """,
            (document_id, run_id, "node-1", "第四条 奖励发放", "第四条 奖励发放", now, now),
        )
        node_id = int(parent.lastrowid)
        database.connection.execute(
            """
            INSERT INTO policy_node (
                document_id,parse_run_id,parent_id,temp_key,node_type,node_number,raw_text,
                content,normalized_content,level,path_text,order_no,parser_confidence,
                decision_method,review_status,created_at,updated_at
            ) VALUES (?,?,?,?,'item','（一）','（一）按月发放','按月发放','（一）按月发放',
                      2,'奖励发放 > （一）',2,0.99,'rule','confirmed',?,?)
            """,
            (document_id, run_id, node_id, "node-2", now, now),
        )
        database.connection.execute(
            """
            INSERT INTO validation_issue (
                parse_run_id,node_id,stage,issue_code,severity,message,details_json,resolved
            ) VALUES (?,?,'structure_validation','NODE_ARTICLE_TITLE_HEURISTIC','review','待确认','{}',0)
            """,
            (run_id, node_id),
        )
        database.connection.commit()

    with ParseReviewService(database_path) as review:
        review.decide_article_title(
            run_id=run_id, node_id=node_id, mode="CONTENT", reviewed_by="reviewer"
        )
        node = review.db.connection.execute(
            "SELECT title,content,review_status,rule_id FROM policy_node WHERE id=?", (node_id,)
        ).fetchone()
        child_path = review.db.connection.execute(
            "SELECT path_text FROM policy_node WHERE parent_id=?", (node_id,)
        ).fetchone()[0]
        unresolved = review.db.connection.execute(
            "SELECT COUNT(*) FROM validation_issue WHERE node_id=? AND resolved=0", (node_id,)
        ).fetchone()[0]
    assert dict(node) == {
        "title": None, "content": "奖励发放", "review_status": "confirmed",
        "rule_id": "NODE_ARTICLE_CONTENT_HUMAN_V1",
    }
    assert child_path.startswith("第四条 >")
    assert unresolved == 0


def test_worker_rejects_failed_run_result() -> None:
    with pytest.raises(KnowledgeRunFailedError) as captured:
        ensure_knowledge_run_succeeded(
            "PARSE_RUN",
            {"id": 12, "status": "failed", "error_code": "PIPELINE_EXCEPTION", "error_message": "解析异常"},
        )

    assert captured.value.run_id == 12
    assert captured.value.retryable is True


def test_worker_accepts_reviewable_run_result() -> None:
    ensure_knowledge_run_succeeded("CHUNK_RUN", {"id": 13, "status": "review_required"})


def test_failed_runs_cannot_be_approved() -> None:
    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    database_path = runtime_root / uuid4().hex / "knowledge" / "policy_parser.db"
    database_path.parent.mkdir(parents=True)
    database = ParserDatabase(database_path)
    document_id = database.get_or_create_document(
        {
            "source_file": "pending/failed.docx",
            "file_name": "failed.docx",
            "file_size": 10,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "checksum": "failed-run-guard",
        }
    )
    parse_run_id = database.create_parse_run(document_id, "test", "parse-config")
    database.update_run(parse_run_id, status="failed", review_status="pending")
    cursor = database.connection.execute(
        """
        INSERT INTO chunk_run (
            document_id,parse_run_id,chunker_version,strategy,config_json,config_hash,
            status,review_status,source_scope,started_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            document_id,
            parse_run_id,
            "test",
            "test",
            "{}",
            "chunk-config",
            "failed",
            "pending",
            "active",
            utc_now(),
            utc_now(),
        ),
    )
    chunk_run_id = int(cursor.lastrowid)
    database.connection.commit()
    database.close()

    with ParseReviewService(database_path) as review:
        with pytest.raises(ValueError, match="失败的 ParseRun 不能批准"):
            review.approve_run(parse_run_id, "reviewer")
    with ChunkReviewService(database_path) as review:
        with pytest.raises(ValueError, match="失败的 ChunkRun 不能批准"):
            review.approve_run(chunk_run_id, "reviewer")


def test_chunker_returns_persisted_failed_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chunk异常统一返回已落库摘要，使Worker能够保存Run ID并识别failed。"""

    runtime_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve()
    database_path = runtime_root / uuid4().hex / "knowledge" / "policy_parser.db"
    database_path.parent.mkdir(parents=True)
    database = ParserDatabase(database_path)
    document_id = database.get_or_create_document(
        {
            "source_file": "pending/chunk-failed.docx",
            "file_name": "chunk-failed.docx",
            "file_size": 10,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "checksum": "chunk-failed-summary",
        }
    )
    parse_run_id = database.create_parse_run(document_id, "test", "parse-config")
    database.update_run(parse_run_id, status="succeeded", review_status="approved")
    database.update_document(document_id, active_parse_run_id=parse_run_id)
    database.close()

    with PolicyChunker(database_path) as chunker:
        monkeypatch.setattr(chunker, "_load_nodes", lambda _run_id: (_ for _ in ()).throw(RuntimeError("分块异常")))
        result = chunker.run_parse_run(parse_run_id, activate=False)

    assert result["status"] == "failed"
    assert result["error_code"] == "RuntimeError"
    assert result["id"] is not None
