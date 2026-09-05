"""文件说明：验证发布来源冻结、任务协调、草稿冲突和显式知识数据迁移。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.ingestion_service import IngestionService, JobConflictError
from app.application.publication_service import PublicationService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    IndexPublicationRequest,
    IndexPublicationSource,
    IngestionJob,
    IngestionJobEvent,
    MetadataChangeRequest,
)
from knowledge.config import KnowledgePaths
from knowledge.data_migrations import migrate_historical_published_metadata
from knowledge.management import KnowledgeManagementService
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError
from knowledge.parser.database import ParserDatabase
from worker import run_publication


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _paths() -> KnowledgePaths:
    root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    root.mkdir(parents=True)
    return KnowledgePaths(root / "knowledge")


def _job(session: Session, *, state: str = "READY_FOR_INDEX") -> IngestionJob:
    job = IngestionJob(
        task_name="测试制度",
        original_filename="测试制度.docx",
        stored_path="pending/test.docx",
        file_sha256=uuid4().hex * 2,
        state=state,
        document_id=8,
        parse_run_id=8,
        chunk_run_id=4,
        created_by="user-1",
    )
    session.add(job)
    session.flush()
    return job


class _SourceManagement:
    def __init__(self, baseline: list[dict[str, int]] | None = None) -> None:
        self.build_called = False
        self.baseline = baseline or []
        self.frozen_sources: list[dict[str, int]] = []

    def active_index_snapshot(self) -> dict[str, object]:
        return {"index_run_id": 4 if self.baseline else None, "sources": self.baseline}

    def publication_source(self, document_id: int, metadata_revision_id: int) -> dict[str, int]:
        return {
            "document_id": document_id,
            "parse_run_id": 8,
            "chunk_run_id": 4,
            "metadata_revision_id": metadata_revision_id,
        }

    def build_index_run(self, required_document_ids: list[int] | None = None, frozen_sources: list[dict[str, int]] | None = None) -> dict[str, int]:
        self.build_called = True
        self.frozen_sources = frozen_sources or []
        return {"index_run_id": 5}

    def index_run_sources(self, run_id: int) -> list[dict[str, int]]:
        assert run_id == 5
        return self.frozen_sources


class _UnexpectedSourceManagement(_SourceManagement):
    def index_run_sources(self, run_id: int) -> list[dict[str, int]]:
        return [
            *super().index_run_sources(run_id),
            {"document_id": 9, "parse_run_id": 9, "chunk_run_id": 9, "metadata_revision_id": 9},
        ]


class _StateFirstManagement(_SourceManagement):
    def __init__(self) -> None:
        super().__init__()
        self.source_called = False

    def publication_source(self, document_id: int, metadata_revision_id: int) -> dict[str, int]:
        self.source_called = True
        raise AssertionError("任务状态无效时不应读取Knowledge发布来源")


def test_publication_freezes_exact_source_and_optional_job() -> None:
    """首次入库绑定Job；纯元数据修订也冻结知识版本但不制造Job。"""

    session = _session()
    job = _job(session)
    session.add(MetadataChangeRequest(
        document_id=8,
        metadata_revision_id=10,
        job_id=job.id,
        request_type="INITIAL",
        status="APPROVED",
        created_by="user-1",
    ))
    session.commit()
    service = PublicationService(
        session, IngestionService(session, _paths()), _SourceManagement()  # type: ignore[arg-type]
    )

    request = service.create([8], "user-1")
    binding = service.bindings(request.id)[0]
    assert job.state == "INDEX_QUEUED"
    assert (binding.document_id, binding.parse_run_id, binding.chunk_run_id) == (8, 8, 4)
    assert binding.metadata_revision_id == 10
    assert binding.job_id == job.id
    assert binding.source_role == "CHANGE"
    assert request.snapshot_contract_version == "exact_snapshot_v2"
    session.close()

    metadata_session = _session()
    metadata_session.add(MetadataChangeRequest(
        document_id=8,
        metadata_revision_id=11,
        job_id=None,
        request_type="CORRECTION",
        status="APPROVED",
        created_by="user-1",
    ))
    metadata_session.commit()
    metadata_service = PublicationService(
        metadata_session,
        IngestionService(metadata_session, _paths()),
        _SourceManagement(),  # type: ignore[arg-type]
    )
    metadata_request = metadata_service.create([8], "user-1")
    metadata_binding = metadata_service.bindings(metadata_request.id)[0]
    assert metadata_binding.job_id is None
    assert metadata_binding.metadata_revision_id == 11
    metadata_session.close()


def test_failed_job_cannot_join_a_new_publication() -> None:
    session = _session()
    job = _job(session, state="FAILED")
    job.failed_stage = "INDEXING"
    session.add(MetadataChangeRequest(
        document_id=8,
        metadata_revision_id=10,
        job_id=job.id,
        request_type="INITIAL",
        status="APPROVED",
        created_by="user-1",
    ))
    session.commit()
    service = PublicationService(
        session, IngestionService(session, _paths()), _SourceManagement()  # type: ignore[arg-type]
    )
    with pytest.raises(JobConflictError, match="重试原发布请求"):
        service.create([8], "user-1")
    session.close()


def test_publication_reports_chunk_review_before_reading_active_source() -> None:
    """任务尚未提交分块审核时，应返回直接可操作的流程提示。"""

    session = _session()
    job = _job(session, state="CHUNK_REVIEW")
    session.add(MetadataChangeRequest(
        document_id=8, metadata_revision_id=10, job_id=job.id,
        request_type="INITIAL", status="APPROVED", created_by="user-1",
    ))
    session.commit()
    management = _StateFirstManagement()
    service = PublicationService(
        session, IngestionService(session, _paths()), management  # type: ignore[arg-type]
    )

    with pytest.raises(JobConflictError, match="审核工作台完成分块审核"):
        service.create([8], "user-1")
    assert management.source_called is False
    session.close()


def test_worker_rejects_unexpected_bound_job_before_index_build() -> None:
    """绑定任务不是INDEX_QUEUED时，Worker必须在调用索引构建前失败。"""

    session = _session()
    paths = _paths()
    job = _job(session, state="READY_FOR_INDEX")
    publication = IndexPublicationRequest(
        status="BUILD_QUEUED", source_document_ids_json="[8]", requested_by="user-1"
    )
    session.add(publication)
    session.flush()
    session.add(IndexPublicationSource(
        publication_request_id=publication.id,
        job_id=job.id,
        document_id=8,
        parse_run_id=8,
        chunk_run_id=4,
        metadata_revision_id=10,
    ))
    session.commit()
    management = _SourceManagement()

    assert run_publication(session, publication, management, paths) is True  # type: ignore[arg-type]
    assert publication.status == "FAILED"
    assert job.state == "READY_FOR_INDEX"
    assert management.build_called is False
    session.close()


def test_worker_marks_legacy_request_without_bindings_failed() -> None:
    """历史请求缺少冻结来源时应留痕失败，不能使Worker进程退出。"""

    session = _session()
    paths = _paths()
    publication = IndexPublicationRequest(
        status="BUILD_QUEUED", source_document_ids_json="[8]", requested_by="user-1"
    )
    session.add(publication)
    session.commit()
    management = _SourceManagement()

    assert run_publication(session, publication, management, paths) is True  # type: ignore[arg-type]
    assert publication.status == "FAILED"
    assert "精确全量快照契约" in str(publication.error_summary)
    assert management.build_called is False
    session.close()


def test_worker_accepts_only_the_exact_frozen_index_source() -> None:
    session = _session()
    paths = _paths()
    job = _job(session, state="INDEX_QUEUED")
    publication = IndexPublicationRequest(
        status="BUILD_QUEUED", snapshot_contract_version="exact_snapshot_v2",
        source_document_ids_json="[8]", requested_by="user-1"
    )
    session.add(publication)
    session.flush()
    binding = IndexPublicationSource(
        publication_request_id=publication.id,
        job_id=job.id,
        source_role="CHANGE",
        document_id=8,
        parse_run_id=8,
        chunk_run_id=4,
        metadata_revision_id=10,
    )
    session.add(binding)
    session.commit()
    management = _SourceManagement()

    assert run_publication(session, publication, management, paths) is True  # type: ignore[arg-type]
    assert management.build_called is True
    assert publication.status == "READY_TO_PUBLISH"
    assert publication.index_run_id == 5
    assert binding.index_run_id == 5
    assert job.state == "READY_TO_PUBLISH"
    assert job.index_run_id == 5
    session.close()


def test_publication_merges_active_baseline_and_selected_change_exactly() -> None:
    """未选中的新制度不得搭车，基线制度即使正在起草修订也必须留在快照。"""

    session = _session()
    job = _job(session)
    session.add(MetadataChangeRequest(
        document_id=8, metadata_revision_id=10, job_id=job.id,
        request_type="INITIAL", status="APPROVED", created_by="user-1",
    ))
    session.commit()
    baseline = [{
        "document_id": 2, "parse_run_id": 2, "chunk_run_id": 2,
        "metadata_revision_id": 2,
    }]
    management = _SourceManagement(baseline)
    service = PublicationService(session, IngestionService(session, _paths()), management)  # type: ignore[arg-type]

    request = service.create([8], "user-1")
    bindings = service.bindings(request.id)
    assert request.base_index_run_id == 4
    assert [(item.document_id, item.source_role) for item in bindings] == [
        (2, "BASELINE"), (8, "CHANGE"),
    ]

    assert run_publication(session, request, management, _paths()) is True  # type: ignore[arg-type]
    assert request.status == "READY_TO_PUBLISH"
    assert {item["document_id"] for item in management.frozen_sources} == {2, 8}
    session.close()


def test_worker_rejects_an_unrequested_document_in_built_snapshot() -> None:
    """构建结果多出任何未冻结制度时，Worker必须阻止进入Alias确认阶段。"""

    session = _session()
    paths = _paths()
    job = _job(session, state="INDEX_QUEUED")
    publication = IndexPublicationRequest(
        status="BUILD_QUEUED", snapshot_contract_version="exact_snapshot_v2",
        source_document_ids_json="[8]", requested_by="user-1",
    )
    session.add(publication)
    session.flush()
    session.add(IndexPublicationSource(
        publication_request_id=publication.id, job_id=job.id, source_role="CHANGE",
        document_id=8, parse_run_id=8, chunk_run_id=4, metadata_revision_id=10,
    ))
    session.commit()
    management = _UnexpectedSourceManagement()

    assert run_publication(session, publication, management, paths) is True  # type: ignore[arg-type]
    assert publication.status == "FAILED"
    assert "来源集合" in str(publication.error_summary)
    assert job.state == "FAILED"
    session.close()


def test_reconcile_failed_job_requires_exact_run_versions() -> None:
    session = _session()
    paths = _paths()
    job = _job(session, state="FAILED")
    job.failed_stage = "INDEXING"
    job.retryable = True
    session.commit()
    ingestion = IngestionService(session, paths)

    with pytest.raises(JobConflictError, match="版本"):
        ingestion.reconcile_published_job(
            job, index_run_id=5, parse_run_id=99, chunk_run_id=4, reason="测试"
        )
    ingestion.reconcile_published_job(
        job, index_run_id=5, parse_run_id=8, chunk_run_id=4, reason="精确来源已核验"
    )
    event = session.scalar(select(IngestionJobEvent).where(
        IngestionJobEvent.job_id == job.id,
        IngestionJobEvent.to_state == "PUBLISHED",
    ))
    assert job.state == "PUBLISHED"
    assert job.index_run_id == 5
    assert event is not None and event.run_id == 5
    session.close()


def test_database_open_does_not_create_backfill_and_draft_collision_is_explicit() -> None:
    paths = _paths()
    KnowledgeManagementService(paths).initialize_empty_baseline()
    with ParserDatabase(paths.database_path) as database:
        document_id = database.get_or_create_document({
            "source_file": "pending/test.docx",
            "file_name": "test.docx",
            "file_size": 10,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "checksum": "no-runtime-backfill",
        })
    with ParserDatabase(paths.database_path) as reopened:
        count = reopened.connection.execute(
            "SELECT COUNT(*) FROM document_metadata_revision WHERE document_id=?", (document_id,)
        ).fetchone()[0]
        assert count == 0
        parse_run_id = reopened.create_parse_run(document_id, "test", "hash")
        reopened.update_run(parse_run_id, status="succeeded", review_status="approved")
        reopened.update_document(
            document_id,
            active_parse_run_id=parse_run_id,
            latest_parse_run_id=parse_run_id,
            parser_status="succeeded",
            review_status="passed",
        )

    with KnowledgeMetadataService(paths.database_path) as metadata:
        initial = metadata.ensure_draft(
            document_id,
            "user-1",
            source_type="PARSE_EXTRACTED",
            initial_document_status="effective",
        )
        assert initial["parse_run_id"] == parse_run_id
        with pytest.raises(MetadataConflictError, match="不能创建"):
            metadata.ensure_draft(document_id, "user-1", source_type="REPEAL")


def test_explicit_historical_migration_records_version_and_is_idempotent() -> None:
    paths = _paths()
    KnowledgeManagementService(paths).initialize_empty_baseline()
    now = "2026-09-04T00:00:00+00:00"
    with ParserDatabase(paths.database_path) as database:
        document_id = database.get_or_create_document({
            "source_file": "accepted/historical.docx",
            "file_name": "historical.docx",
            "file_size": 10,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "checksum": "historical-active-document",
        })
        parse_run_id = database.create_parse_run(document_id, "legacy", "parse-hash")
        database.update_run(parse_run_id, status="succeeded", review_status="approved")
        database.update_document(
            document_id,
            title="历史已发布制度",
            status="effective",
            active_parse_run_id=parse_run_id,
            latest_parse_run_id=parse_run_id,
            parser_status="succeeded",
            review_status="passed",
        )
        cursor = database.connection.execute(
            """
            INSERT INTO chunk_run (
                document_id,parse_run_id,chunker_version,strategy,config_json,config_hash,
                status,review_status,source_scope,started_at,created_at
            ) VALUES (?,?,'legacy','legacy','{}','chunk-hash','succeeded','approved','active',?,?)
            """,
            (document_id, parse_run_id, now, now),
        )
        chunk_run_id = int(cursor.lastrowid)
        database.update_document(document_id, active_chunk_run_id=chunk_run_id)

    with sqlite3.connect(paths.database_path) as connection:
        profile_id = connection.execute(
            "SELECT id FROM index_profile WHERE profile_name='policy_platform_dense'"
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO index_run (
                profile_id,source_manifest_hash,embedding_provider,embedding_model,
                embedding_model_revision,embedding_contract_json,embedding_contract_hash,
                dimension,distance_metric,vector_name,collection_name,alias_name,
                point_schema_version,config_json,config_hash,indexer_version,status,
                activation_status,started_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                profile_id, "manifest", "provider", "model", "revision", "{}", "contract",
                8, "Cosine", "dense", "collection-historical",
                "policy_platform_dense_active", "v1", "{}", "config", "legacy",
                "succeeded", "active", now, now,
            ),
        )
        index_run_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO index_run_source (
                index_run_id,document_id,parse_run_id,chunk_run_id,metadata_revision_id,
                retrievable_count,source_digest,created_at
            ) VALUES (?,?,?,?,NULL,1,'digest',?)
            """,
            (index_run_id, document_id, parse_run_id, chunk_run_id, now),
        )
        connection.execute(
            "UPDATE index_profile SET active_index_run_id=?,latest_index_run_id=? WHERE id=?",
            (index_run_id, index_run_id, profile_id),
        )

    first = migrate_historical_published_metadata(paths.database_path)
    second = migrate_historical_published_metadata(paths.database_path)
    assert first["applied"] is True and first["details"]["migrated_document_ids"] == [document_id]
    assert second["applied"] is False and second["details"]["count"] == 1
    with sqlite3.connect(paths.database_path) as connection:
        revision = connection.execute(
            """
            SELECT mr.source_type,mr.lifecycle_status,mr.parse_run_id
            FROM document_metadata_revision mr
            JOIN policy_document d ON d.latest_metadata_revision_id=mr.id
            WHERE d.id=?
            """,
            (document_id,),
        ).fetchone()
        assert revision == ("BACKFILL", "PUBLISHED", parse_run_id)
        assert connection.execute(
            "SELECT metadata_revision_id FROM index_run_source WHERE index_run_id=?",
            (index_run_id,),
        ).fetchone()[0] == 1
    source = KnowledgeManagementService(paths).publication_source(document_id, 1)
    assert source == {
        "document_id": document_id,
        "parse_run_id": parse_run_id,
        "chunk_run_id": chunk_run_id,
        "metadata_revision_id": 1,
    }
