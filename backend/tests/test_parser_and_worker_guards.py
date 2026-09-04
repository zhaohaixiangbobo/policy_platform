"""文件说明：验证解析阈值、Worker与审核服务失败运行守卫的最小契约。"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from knowledge.chunking.review import ChunkReviewService
from knowledge.chunking.chunker import PolicyChunker
from knowledge.parser.analyzer import validate_structure
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
