"""文件说明：验证第二期认证、入库状态机、关系证据和流程生命周期核心契约。"""

import io
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.auth_service import AuthService, bootstrap_local_user
from app.application.ingestion_service import IngestionService
from app.application.evidence_binding_service import EvidenceBindingService
from app.application.evidence_reference_validator import EvidenceValidationResult
from app.application.process_service import ProcessConflictError, ProcessService
from app.application.relation_service import RelationConflictError, RelationService
from app.domain.ingestion import InvalidStateTransition, assert_transition, retry_target
from app.infrastructure.db.base import Base
from knowledge.config import KnowledgePaths


def make_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def minimal_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document xmlns:w='urn:test'><w:body/></w:document>")
    return output.getvalue()


def test_authentication_and_rbac_session() -> None:
    session = make_session()
    user = bootstrap_local_user(session, "admin", "系统管理员", "phase2-pass-123", ["ADMIN"])
    service = AuthService(session, 8)
    result = service.login("admin", "phase2-pass-123", "127.0.0.1", "pytest")

    assert result.principal.user_id == user.id
    assert "policy_process.publish" in result.principal.permissions
    assert "policy_relation.manage" in result.principal.permissions
    assert service.authenticate(result.session_token).username == "admin"
    service.change_password(result.principal, "phase2-pass-123", "phase2-new-pass-456")
    assert service.authenticate(result.session_token).must_change_password is False
    session.close()


def test_upload_creates_only_uploaded_job() -> None:
    session = make_session()
    user = bootstrap_local_user(session, "manager", "入库管理员", "phase2-pass-123", ["ADMIN"])
    test_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    test_root.mkdir(parents=True)
    service = IngestionService(session, KnowledgePaths(test_root / "knowledge"))

    job = service.create_job("测试制度.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", minimal_docx(), user.id)

    assert job.state == "UPLOADED"
    assert job.state_version == 1
    assert job.initial_document_status == "effective"
    assert (test_root / "knowledge" / job.stored_path).is_file()
    session.close()


def test_upload_persists_explicit_status_as_declaration() -> None:
    """上传状态是声明值，供首次元数据草稿使用，不代表已经审核生效。"""

    session = make_session()
    user = bootstrap_local_user(session, "status-manager", "状态管理员", "phase2-pass-123", ["ADMIN"])
    test_root = Path(os.environ["POLICY_TEST_RUNTIME_ROOT"]).resolve() / uuid4().hex
    test_root.mkdir(parents=True)
    service = IngestionService(session, KnowledgePaths(test_root / "knowledge"))

    job = service.create_job(
        "历史制度.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        minimal_docx(),
        user.id,
        initial_document_status="repealed",
    )

    assert job.initial_document_status == "repealed"
    assert job.state == "UPLOADED"
    session.close()


def test_state_machine_rejects_skip_and_freezes_retry_targets() -> None:
    assert_transition("UPLOADED", "PREFLIGHTING")
    assert retry_target("PARSING", True) == "PARSE_QUEUED"
    with pytest.raises(InvalidStateTransition):
        assert_transition("UPLOADED", "PUBLISHED")


def test_process_requires_review_before_publish() -> None:
    session = make_session()
    user = bootstrap_local_user(session, "flow-admin", "流程管理员", "phase2-pass-123", ["ADMIN"])
    service = ProcessService(session)
    process, _revision = service.create("制度入库流程", None, user.id)
    service.update_graph(process.id, {"nodes": [{"id": "start"}], "edges": []}, "建立起点", user.id)
    with pytest.raises(ProcessConflictError):
        service.publish(process.id, user.id)
    service.submit(process.id)
    service.review(process.id, user.id, user.id, True)
    _process, revision = service.publish(process.id, user.id)
    assert revision.status == "PUBLISHED"
    session.close()


def test_relation_requires_valid_evidence_before_review() -> None:
    """关系必须先绑定经统一校验的证据，人工确认后才成为正式关系。"""

    class ValidEvidenceValidator:
        def validate(self, *_args: object) -> EvidenceValidationResult:
            return EvidenceValidationResult("VALID", "证据引用有效")

        def validate_document_version(self, *_args: object) -> EvidenceValidationResult:
            return EvidenceValidationResult("VALID", "制度版本有效")

    session = make_session()
    user = bootstrap_local_user(session, "relation-admin", "关系管理员", "phase2-pass-123", ["ADMIN"])
    evidence = EvidenceBindingService(session, ValidEvidenceValidator())  # type: ignore[arg-type]
    service = RelationService(session, evidence)
    relation = service.create("CITES", 1, 10, 2, 20, "测试引用关系", None, None, user.id)
    with pytest.raises(RelationConflictError, match="至少需要一条制度证据"):
        service.submit(relation.id)
    evidence.bind(owner_type="POLICY_RELATION", owner_id=relation.id, document_id=1, parse_run_id=10, primary_node_id=100, page_start=1, page_end=1, quote_snapshot="真实制度原文", actor_user_id=user.id)
    assert service.submit(relation.id).status == "PENDING_REVIEW"
    assert service.review(relation.id, True, "审核通过", user.id).status == "CONFIRMED"
    session.close()
