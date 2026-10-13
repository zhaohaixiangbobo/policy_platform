"""文件说明：P3最小PG故障测试；业务数据仅写隔离schema，不调用真实外部服务。"""

from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.infrastructure.db.worker_mutex import worker_mutex
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from sqlalchemy import create_engine, text, select, update, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import UserAccount, IngestionJob, IndexPublicationRequest, LearningAssessmentSlot
from app.application.task_lease import claim, LeaseExecution, LeaseLostError
from tests.test_pg_p2 import isolated_pg
from knowledge.storage.execution import knowledge_execution
from knowledge.storage.repository import CoreRepository
from unittest.mock import Mock
from app.infrastructure.db.models import IndexPublicationSource, IngestionJobEvent
from app.application.publication_recovery import recover_publication, requeue_interrupted_build
from knowledge.config import KnowledgePaths
from knowledge.parser.database import ParserDatabase
from app.application.ingestion_recovery import recover_completed_ingestion, mark_interrupted_ingestion
from types import SimpleNamespace
from contextlib import contextmanager


@pytest.fixture
def platform_factory():
    values = dotenv_values(Path(__file__).resolve().parents[2] / "var/postgres-dev/platform.env")
    owner = create_engine(values["PLATFORM_MIGRATION_URL"], hide_parameters=True)
    schema = "p3_test_" + uuid4().hex
    with owner.begin() as connection:
        assert connection.execute(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()" )).scalar() == "policy-platform-pg17-dev:platform"
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        Base.metadata.create_all(connection)
        connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO platform_app'))
        connection.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA "{schema}" TO platform_app'))
        connection.execute(text(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO platform_app'))
    engine = create_engine(values["PLATFORM_DATABASE_URL"], hide_parameters=True, connect_args={"options": f"-c search_path={schema}"})
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        with factory() as session:
            session.add(UserAccount(id="tester", username="p3-test", display_name="测试"))
            session.commit()
        yield factory
    finally:
        engine.dispose()
        with owner.begin() as connection:
            assert schema.startswith("p3_test_") and len(schema) == 40
            connection.execute(DropSchema(schema, cascade=True))
        owner.dispose()


@pytest.mark.parametrize("kind", ["ingestion", "publication", "learning"])
def test_atomic_claim_and_expired_generation(platform_factory, kind):
    factory = platform_factory
    if kind == "ingestion":
        model, key_name, order, eligible = IngestionJob, "id", IngestionJob.created_at, [IngestionJob.state == "UPLOADED"]
        row = model(id="job", task_name="test", original_filename="test.docx", stored_path="pending/test.docx", file_sha256="a"*64, created_by="tester")
    elif kind == "publication":
        model, key_name, order, eligible = IndexPublicationRequest, "id", IndexPublicationRequest.created_at, [IndexPublicationRequest.status == "BUILD_QUEUED"]
        row = model(id="request", status="BUILD_QUEUED", requested_by="tester")
    else:
        model, key_name, order, eligible = LearningAssessmentSlot, "user_id", LearningAssessmentSlot.task_created_at, [LearningAssessmentSlot.task_state == "GENERATING"]
        row = model(user_id="tester", task_id="task", task_state="GENERATING", pending_json="{}", task_created_at=func.clock_timestamp())
    with factory() as session:
        session.add(row)
        session.commit()
    barrier = Barrier(2)
    def contender(owner):
        with factory() as session:
            barrier.wait(timeout=5)
            return claim(session, model, key_name=key_name, owner=owner, eligible=eligible, order_by=order)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(contender, ["worker-a", "worker-b"]))
    winners = [token for token in tokens if token]
    assert len(winners) == 1
    old = winners[0]
    with factory() as session:
        session.execute(update(model).values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1)))
        session.commit()
        new = claim(session, model, key_name=key_name, owner="worker-new", eligible=eligible, order_by=order)
    assert new.generation == old.generation + 1
    with pytest.raises(LeaseLostError):
        LeaseExecution(factory, old).check()
    LeaseExecution(factory, new).check()
    # 即使旧执行者已加载ORM对象，提交保护也应回滚其写入。
    with factory() as session:
        execution = LeaseExecution(factory, old)
        with pytest.raises(LeaseLostError), execution.guard_session(session):
            stale = session.get(model, old.key)
            stale.lease_owner = "stale-overwrite"
            session.commit()
        session.rollback()
    LeaseExecution(factory, new).check()
    renewal = LeaseExecution(factory, new)
    renewal.stopped = Mock()
    renewal.stopped.wait.side_effect = [False, True]
    renewal._heartbeat()
    with factory() as session:
        assert session.scalar(select(model.lease_expires_at > func.clock_timestamp() + timedelta(seconds=90)))
        session.execute(update(model).values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1)))
        session.commit()
    renewal.stopped.wait.side_effect = [False]
    renewal._heartbeat()
    assert renewal.lost.is_set()


def test_worker_role_mutex_release_and_independent_roles(monkeypatch):
    from app.infrastructure.db.worker_mutex import WORKER_LOCKS
    # 测试使用独立锁键，不抢占用户正在运行的真实Worker角色锁。
    key = int(uuid4().hex[:7], 16) + 2000000000
    monkeypatch.setitem(WORKER_LOCKS, "ingestion", key)
    monkeypatch.setitem(WORKER_LOCKS, "learning", key + 1)
    values = dotenv_values(Path(__file__).resolve().parents[2] / "var/postgres-dev/platform.env")
    url = values["PLATFORM_DATABASE_URL"]
    with worker_mutex("ingestion", database_url=url):
        with pytest.raises(RuntimeError, match="已在此数据库运行"):
            with worker_mutex("ingestion", database_url=url):
                pytest.fail("同角色的第二个连接不应取得锁")
        with worker_mutex("learning", database_url=url):
            pass
    # 物理会话关闭后可重新取得锁，异常路径亦须释放。
    with pytest.raises(ValueError, match="模拟退出"):
        with worker_mutex("ingestion", database_url=url):
            raise ValueError("模拟退出")
    with worker_mutex("ingestion", database_url=url):
        pass


def test_knowledge_generation_rejects_stale_write(isolated_pg):
    url, engine, _paths = isolated_pg
    with knowledge_execution(engine, "test:operation", 1, lambda: None) as old:
        old.complete({"id": 10})
        with knowledge_execution(engine, "test:operation", 2, lambda: None) as current:
            current.complete({"id": 20})
        with CoreRepository(url) as repo:
            with pytest.raises(RuntimeError, match="操作代次已变化"):
                repo.run(text("INSERT INTO policy_series(series_key,canonical_title,status,created_at,updated_at) VALUES ('stale','旧结果','ACTIVE','now','now')"))
        with pytest.raises(RuntimeError, match="操作代次已变化"):
            old.complete({"id": 30})
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM policy_series")).scalar() == 0
        assert '20' in connection.execute(text("SELECT result_json FROM worker_operation")).scalar()


def test_publication_partial_success_preserved_and_recovered(platform_factory):
    from worker import run_publication
    factory = platform_factory
    paths = KnowledgePaths(Path(__file__).resolve().parents[2] / "var/tests/pg-p3")
    with factory() as session:
        session.add(IngestionJob(id="publish-job", task_name="test", original_filename="test.docx",
                                 stored_path="pending/test.docx", file_sha256="b"*64, created_by="tester",
                                 state="READY_TO_PUBLISH", document_id=1, parse_run_id=2, chunk_run_id=3, index_run_id=4))
        session.add(IndexPublicationRequest(id="publish-request", status="PUBLISH_QUEUED",
                    requested_by="tester", published_by="tester", snapshot_contract_version="exact_snapshot_v2",
                    source_document_ids_json="[1]", index_run_id=4))
        session.commit()
        session.add(IndexPublicationSource(publication_request_id="publish-request", job_id="publish-job",
                    source_role="CHANGE", document_id=1, parse_run_id=2, chunk_run_id=3, metadata_revision_id=5))
        session.commit()
    management = Mock()
    management.active_index_snapshot.return_value = {"index_run_id": None}
    management.publish_index_run.side_effect = RuntimeError("Alias已切换，数据库提交失败")
    with factory() as session:
        request = session.get(IndexPublicationRequest, "publish-request")
        assert run_publication(session, request, management, paths)
        assert request.status == "PUBLISHING"
        assert session.get(IngestionJob, "publish-job").state == "PUBLISHING"
    management.publish_index_run.side_effect = None
    management.index_run_sources.return_value = [dict(document_id=1, parse_run_id=2, chunk_run_id=3, metadata_revision_id=5)]
    with pytest.raises(ValueError, match="确认旧执行者"):
        recover_publication(factory, management, paths, "publish-request")
    recover_publication(factory, management, paths, "publish-request", executor_stopped=True)
    recover_publication(factory, management, paths, "publish-request", executor_stopped=True)
    management.publish_index_run.assert_called_with(4, recover=True, recover_base=None)
    with factory() as session:
        assert session.get(IndexPublicationRequest, "publish-request").status == "PUBLISHED"
        assert session.get(IngestionJob, "publish-job").state == "PUBLISHED"
        assert len(list(session.scalars(select(IngestionJobEvent).where(IngestionJobEvent.to_state == "PUBLISHED")))) == 1


def test_ingestion_receipt_recovery_is_idempotent(platform_factory, isolated_pg):
    url, engine, paths = isolated_pg
    with ParserDatabase(url) as db:
        document_id = db.get_or_create_document(dict(source_file="pending/test.docx", file_name="test.docx",
                   file_size=100, mime_type="application/octet-stream", checksum="p3-recovery"))
        run_id = db.create_parse_run(document_id, "test", "test")
        db.update_run(run_id, status="succeeded")
    with knowledge_execution(engine, "ingestion:recover-job:PARSE_QUEUED", 1, lambda: None) as operation:
        operation.complete(dict(id=run_id, document_id=document_id, status="succeeded"))
    with platform_factory() as session:
        session.add(IngestionJob(id="recover-job", task_name="test", original_filename="test.docx",
                    stored_path="pending/test.docx", file_sha256="c"*64, created_by="tester",
                    state="PARSING", lease_generation=2))
        session.commit()
    assert recover_completed_ingestion(platform_factory, paths) == 1
    assert recover_completed_ingestion(platform_factory, paths) == 0
    with platform_factory() as session:
        job = session.get(IngestionJob, "recover-job")
        assert job.state == "PARSE_REVIEW" and job.parse_run_id == run_id


def test_ingestion_worker_preflight_with_lease(platform_factory, isolated_pg, monkeypatch):
    import worker
    url, engine, paths = isolated_pg
    paths.pending_documents.mkdir(parents=True)
    (paths.pending_documents / "test.docx").touch()
    monkeypatch.setattr(worker, "get_session_factory", lambda: platform_factory)
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(knowledge_data_root=paths.data_root))
    monkeypatch.setattr(worker, "engine_for", lambda _: engine)
    with platform_factory() as session:
        session.add(IngestionJob(id="preflight", task_name="test", original_filename="test.docx",
                    stored_path="pending/test.docx", file_sha256="d"*64, created_by="tester"))
        session.commit()
    assert worker.run_once("test-worker")
    with platform_factory() as session:
        job = session.get(IngestionJob, "preflight")
        assert job.state == "PARSE_QUEUED" and job.lease_generation == 1 and job.lease_owner is None


def test_learning_worker_has_no_transaction_during_model(platform_factory, monkeypatch):
    import learning_worker
    settings = SimpleNamespace(learning_assessment_enabled=True, learning_assessment_task_timeout_seconds=600,
                               learning_assessment_ttl_hours=24)
    with platform_factory() as session:
        session.add(LearningAssessmentSlot(user_id="tester", task_id="learn", task_state="GENERATING",
                    task_created_at=func.clock_timestamp(), pending_json='{"source":{"units":[]},"counts":{}}'))
        session.commit()
    @contextmanager
    def client_factory():
        assert platform_factory.kw["bind"].pool.checkedout() == 0
        yield SimpleNamespace()
    monkeypatch.setattr(learning_worker, "generate_assessment", lambda *args: [])
    assert learning_worker.run_once(platform_factory, settings, client_factory)
    with platform_factory() as session:
        row = session.get(LearningAssessmentSlot, "tester")
        assert row.task_state == "READY" and row.lease_owner is None


@pytest.mark.parametrize("state,retryable", [("PARSING", True), ("CHUNKING", False)])
def test_interrupted_ingestion_requires_confirmation(platform_factory, isolated_pg, state, retryable):
    _url, _engine, paths = isolated_pg
    with platform_factory() as session:
        session.add(IngestionJob(id="interrupted", task_name="test", original_filename="test.docx",
                    stored_path="pending/test.docx", file_sha256="e"*64, created_by="tester", state=state))
        session.commit()
    with pytest.raises(ValueError, match="确认"):
        mark_interrupted_ingestion(platform_factory, paths, "interrupted")
    mark_interrupted_ingestion(platform_factory, paths, "interrupted", executor_stopped=True)
    with platform_factory() as session:
        job = session.get(IngestionJob, "interrupted")
        assert job.state == "FAILED" and job.failed_stage == state and job.retryable == retryable


def test_interrupted_build_requeues_original_request(platform_factory):
    paths = KnowledgePaths(Path(__file__).resolve().parents[2] / "var/tests/pg-p3")
    with platform_factory() as session:
        session.add(IndexPublicationRequest(id="build-recovery", status="BUILDING", requested_by="tester",
                    snapshot_contract_version="exact_snapshot_v2", source_document_ids_json="[1]"))
        session.commit()
        session.add(IndexPublicationSource(publication_request_id="build-recovery", source_role="CHANGE",
                    document_id=1, parse_run_id=2, chunk_run_id=3, metadata_revision_id=4))
        session.commit()
    with pytest.raises(ValueError, match="确认"):
        requeue_interrupted_build(platform_factory, paths, "build-recovery")
    requeue_interrupted_build(platform_factory, paths, "build-recovery", executor_stopped=True)
    with platform_factory() as session:
        request = session.get(IndexPublicationRequest, "build-recovery")
        assert request.status == "BUILD_QUEUED" and request.published_by is None
        assert len(list(session.scalars(select(IndexPublicationSource)))) == 1
