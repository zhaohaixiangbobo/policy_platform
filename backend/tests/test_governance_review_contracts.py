"""文件说明：验证治理列表筛选分页与审核批量操作的最小业务契约。"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.metadata_service import MetadataApplicationService
from app.application.review_service import ReviewService
from app.application.ingestion_service import IngestionService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import IngestionJob
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.parser.database import ParserDatabase, utc_now
from knowledge.parser.review import ReviewService as ParseReviewService


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


class _DocumentCatalog:
    def list_documents(self) -> list[dict[str, object]]:
        return [
            {
                "id": index,
                "title": f"制度{index:02d}",
                "file_name": f"policy-{index}.docx",
                "document_code": f"文号-{index}",
                "issuing_org": "测试机构",
                "owner_department": "信息部门" if index == 12 else "其他部门",
                "canonical_title": f"制度系列{index}",
                "latest_metadata_revision_id": None,
                "metadata_status": "DRAFT" if index == 12 else "PUBLISHED",
                "updated_at": f"2026-09-{index:02d}T00:00:00+00:00",
            }
            for index in range(1, 13)
        ]


class _ReviewReader:
    """提供审核运行摘要，验证Platform分页契约而不读取真实Knowledge库。"""

    def review_detail(self, target_type: str, run_id: int) -> dict[str, object]:
        return {
            "run": {
                "status": "succeeded",
                "review_status": "not_required",
                "document_title": f"制度{run_id:02d}",
                "document_code": f"文号-{run_id}",
            },
            "issues": [], "nodes": [], "chunks": [],
        }


def test_governance_search_status_sort_and_fixed_page_size() -> None:
    session = _session()
    service = MetadataApplicationService(session, _DocumentCatalog(), None)  # type: ignore[arg-type]

    first_page = service.search(
        keyword=None, metadata_status=None, sort_by="ACTION_REQUIRED", page=1, page_size=10
    )
    matched = service.search(
        keyword="信息部门", metadata_status="ACTION_REQUIRED",
        sort_by="UPDATED_DESC", page=1, page_size=10,
    )

    assert first_page["total"] == 12 and len(first_page["items"]) == 10
    assert first_page["items"][0]["id"] == 12
    assert [item["id"] for item in matched["items"]] == [12]
    session.close()


def test_task_center_uses_server_pagination_and_filtered_total() -> None:
    """任务中心每页十条，状态筛选后的总数与当前结果保持一致。"""

    session = _session()
    root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    paths = KnowledgePaths(root / "knowledge")
    for index in range(12):
        session.add(IngestionJob(
            task_name=f"任务{index:02d}",
            original_filename=f"{index}.docx",
            stored_path=f"pending/{index}.docx",
            file_sha256=f"{index:064d}",
            state="UPLOADED" if index < 7 else "FAILED",
            created_by="reviewer",
        ))
    session.commit()
    service = IngestionService(session, paths)

    first_items, first_total, counts = service.list_jobs(page=1, page_size=10)
    second_items, second_total, _ = service.list_jobs(page=2, page_size=10)
    filtered_items, filtered_total, _ = service.list_jobs("FAILED", page=1, page_size=10)

    assert first_total == second_total == 12
    assert len(first_items) == 10 and len(second_items) == 2
    assert filtered_total == 5 and len(filtered_items) == 5
    assert counts == {"FAILED": 5, "UPLOADED": 7}
    session.close()


def test_parse_batch_confirmation_is_atomic_and_excludes_blocking_errors() -> None:
    root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    database_path = root / "knowledge" / "policy_parser.db"
    database_path.parent.mkdir(parents=True)
    now = utc_now()
    with ParserDatabase(database_path) as database:
        document_id = database.get_or_create_document({
            "source_file": "pending/batch.docx", "file_name": "batch.docx",
            "file_size": 10, "mime_type": "application/docx", "checksum": uuid4().hex,
        })
        run_id = database.create_parse_run(document_id, "test", "batch-config")
        node_ids: list[int] = []
        for index in range(2):
            cursor = database.connection.execute(
                """
                INSERT INTO policy_node (
                    document_id,parse_run_id,temp_key,node_type,raw_text,level,order_no,
                    parser_confidence,decision_method,review_status,created_at,updated_at
                ) VALUES (?,?,?,'article','正文',1,?,1.0,'rule','pending',?,?)
                """,
                (document_id, run_id, f"node-{index}", index, now, now),
            )
            node_ids.append(int(cursor.lastrowid))
        issue_ids: list[int] = []
        for severity in ("review", "error"):
            cursor = database.connection.execute(
                """
                INSERT INTO validation_issue (
                    parse_run_id,stage,issue_code,severity,message,details_json,resolved
                ) VALUES (?,'validate',?,?,?,'{}',0)
                """,
                (run_id, f"ISSUE_{severity.upper()}", severity, severity),
            )
            issue_ids.append(int(cursor.lastrowid))
        database.connection.commit()

    with ParseReviewService(database_path) as review:
        result = review.decide_many(
            run_id=run_id, target_type="node", target_ids=node_ids,
            action="confirm", reviewed_by="reviewer",
        )
        assert result["processed_count"] == 2
        with pytest.raises(ValueError, match="普通待处理问题"):
            review.decide_many(
                run_id=run_id, target_type="issue", target_ids=issue_ids,
                action="ignore", reviewed_by="reviewer", comment="统一接受理由",
            )
        unresolved = review.db.connection.execute(
            "SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=? AND resolved=0",
            (run_id,),
        ).fetchone()[0]
        assert unresolved == 2


def test_review_queue_keeps_zero_issue_runs_pending_and_pages_by_ten() -> None:
    """not_required只表示零问题，不能代替最终人工批准。"""

    session = _session()
    root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    paths = KnowledgePaths(root / "knowledge")
    KnowledgeManagementService(paths).initialize_empty_baseline()
    for run_id in range(1, 13):
        session.add(IngestionJob(
            task_name=f"制度{run_id:02d}", original_filename=f"{run_id}.docx",
            stored_path=f"pending/{run_id}.docx", file_sha256=f"{run_id:064d}",
            state="CHUNK_REVIEW", document_id=run_id, parse_run_id=run_id,
            chunk_run_id=run_id, created_by="reviewer",
        ))
    session.commit()
    service = ReviewService(
        session, IngestionService(session, paths), KnowledgeManagementService(paths),
        _ReviewReader(),  # type: ignore[arg-type]
    )

    first = service.search_queue(
        include_history=True, processing_status="PENDING", target_type="CHUNK_RUN",
        keyword=None, review_state=None, sort_by="UPDATED_DESC", page=1, page_size=10,
    )
    matched = service.search_queue(
        include_history=True, processing_status="PENDING", target_type="CHUNK_RUN",
        keyword="文号-12", review_state="READY_TO_SUBMIT", sort_by="TITLE_ASC",
        page=1, page_size=10,
    )

    assert first["total"] == 12 and len(first["items"]) == 10
    assert first["counts"]["pending_chunk"] == 12
    assert all(item["processing_status"] == "PENDING" for item in first["items"])
    assert [item["target_id"] for item in matched["items"]] == ["12"]
    session.close()
