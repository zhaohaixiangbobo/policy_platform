"""文件说明：学习自测最小回归，使用临时内存库与模型替身，不调用模型或改动正式数据。"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_principal
from app.api.v1.learning import router, CreateAssessment
from app.application.auth_service import Principal, hash_token
from app.application.learning_service import LearningService, encode, public_current, score_questions
from app.application.query_scope_service import OpenDocumentAccessResolver, DocumentAccessDecision
from app.config import Settings
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import UserAccount, LearningAssessmentSlot as Slot, utc_now
from app.infrastructure.db.session import get_db_session
from knowledge.learning_generator import generate_assessment, Candidate, validate_candidate
from knowledge.learning_source import freeze_learning_source
from learning_worker import run_once


@pytest.fixture
def storage():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([UserAccount(id="u1", username="learner1", display_name="学习者"),
                         UserAccount(id="u2", username="learner2", display_name="另一学习者")])
        session.commit()
    yield factory
    engine.dispose()


def source():
    return {"document_id": 1, "document_title": "测试制度", "document_code": "测〔2026〕1号",
            "index_run_id": 9, "parse_run_id": 3, "scope": {"mode": "FULL", "node_ids": []},
            "units": [{"primary_node_id": 10, "knowledge_point": "第一条",
                       "source_text_snapshot": "第一条 工作人员应当在收到通知后三日内提交书面报告。"}]}


def question():
    return {"question_id": "q1", "question_type": "SINGLE", "question": "收到通知后应在几日内提交报告？",
            "options": ["三日", "五日", "十日", "十五日"], "correct_answer": [0],
            "explanation": "第一条规定收到通知后三日内提交书面报告。", **source()["units"][0]}


def ready(factory, *, expired=False):
    task_id = str(uuid4())
    data = {**{k: v for k, v in source().items() if k != "units"}, "assessment_id": task_id,
            "status": "READY", "questions": [question()], "user_answers": {},
            "expires_at": (utc_now() + timedelta(hours=24)).isoformat()}
    with factory() as session:
        session.add(Slot(user_id="u1", current_id=task_id, current_json=encode(data), task_id=task_id, task_state="READY",
                         task_created_at=utc_now(), expires_at=utc_now() + timedelta(hours=-1 if expired else 24)))
        session.commit()
    return task_id, data


@pytest.fixture
def api(storage):
    settings = Settings(learning_assessment_enabled=True)
    principal = Principal(user_id="u1", username="learner1", display_name="学习者", roles=("USER",),
                          permissions=frozenset({"knowledge.document.read"}), must_change_password=False,
                          auth_provider="LOCAL", session_id="test", csrf_token_hash=hash_token("csrf"))
    app = FastAPI()
    app.include_router(router)
    app.state.document_access_resolver = OpenDocumentAccessResolver()
    app.state.knowledge_catalog = SimpleNamespace(
        get_document=lambda _: SimpleNamespace(active_parse_run_id=3))
    app.dependency_overrides[get_current_principal] = lambda: principal

    def session():
        with storage() as value:
            yield value
    app.dependency_overrides[get_db_session] = session
    with patch("app.api.v1.learning.get_settings", return_value=settings), \
            patch("app.api.dependencies.get_settings", return_value=settings):
        with TestClient(app) as client:
            yield client, app, settings, principal


def test_question_limit_and_scope():
    with patch("app.api.v1.learning.get_settings", return_value=Settings()):
        for args in ({"single": 16}, {"single": 15, "multiple": 1, "true_false": 0},
                     {"single": 0, "multiple": 0, "true_false": 0}, {"scope": "SELECTED"}, {"node_ids": [9]}):
            with pytest.raises(ValueError):
                CreateAssessment(request_id=uuid4(), document_id=1, **args)


def test_program_scoring_exact_sets():
    one = question()
    two = {**one, "question_id": "q2",
           "question_type": "MULTIPLE", "correct_answer": [0, 1]}
    three = {**one, "question_id": "q3", "question_type": "TRUE_FALSE",
             "options": ["正确", "错误"], "correct_answer": [1]}
    result = score_questions([one, two, three], {"q1": [0], "q2": [0]})
    assert result["score"] == 33.3 and result["unanswered"] == 1
    assert result["weak_points"][0]["wrong"] == 1
    assert score_questions([two], {"q2": [1, 0]})["score"] == 100
    for answers in ({"q1": [True]}, {"q1": [0, 0]}, {"q1": [9]}, {"fake": [0]}, {"q1": [0, 1]}):
        with pytest.raises(ValueError):
            score_questions([one], answers)


def test_answer_projection_hides_all_evidence():
    data = {"status": "READY", "questions": [question()]}
    exposed = public_current(data)["questions"][0]
    assert set(exposed) == {"question_id",
                            "question_type", "question", "options"}
    assert "correct_answer" in public_current(
        {**data, "status": "SUBMITTED"})["questions"][0]


def test_api_submission_csrf_ownership_expiry_and_idempotency(api, storage):
    client, app, settings, principal = api
    task_id, _ = ready(storage)
    response = client.get("/learning-assessments/current")
    assert response.status_code == 200
    assert "correct_answer" not in response.json()[
        "assessment"]["questions"][0]
    assert client.post(
        f"/learning-assessments/{task_id}/submit", json={"answers": {}}).status_code == 403
    headers = {"X-CSRF-Token": "csrf"}
    assert client.put(f"/learning-assessments/{task_id}/answers", headers=headers, json={
                      "answers": {"q1": [0]}}).status_code == 200
    assert client.get(
        "/learning-assessments/current").json()["assessment"]["user_answers"] == {"q1": [0]}
    response = client.post(
        f"/learning-assessments/{task_id}/submit", headers=headers, json={"answers": {"q1": [0]}})
    assert response.json()["result"]["score"] == 100
    assert client.post(f"/learning-assessments/{task_id}/submit", headers=headers, json={
                       "answers": {"q1": [1]}}).json()["result"]["score"] == 100
    assert client.post(f"/learning-assessments/{uuid4()}/submit",
                       headers=headers, json={"answers": {}}).status_code == 409
    with storage() as session:
        row = session.get(Slot, "u1")
        row.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    assert client.get(
        "/learning-assessments/current").json()["assessment"] is None
    assert client.post(f"/learning-assessments/{task_id}/submit",
                       headers=headers, json={"answers": {}}).status_code == 409


def test_feature_disabled_and_document_access(api, storage):
    client, app, settings, _ = api
    ready(storage)
    settings.learning_assessment_enabled = False
    assert client.get("/learning-assessments/current").status_code == 404
    settings.learning_assessment_enabled = True
    app.state.document_access_resolver = SimpleNamespace(
        resolve=lambda _: DocumentAccessDecision("RESTRICTED", frozenset(), "test"))
    assert client.get("/learning-assessments/current").status_code == 403


def test_other_user_has_no_result(api, storage):
    client, app, _, principal = api
    ready(storage)
    from dataclasses import replace
    app.dependency_overrides[get_current_principal] = lambda: replace(
        principal, user_id="u2")
    assert client.get(
        "/learning-assessments/current").json()["assessment"] is None


def test_creation_deduplicates_and_bounds_pending(api, storage):
    client, app, settings, _ = api
    body = {"request_id": str(uuid4()), "document_id": 1,
            "single": 1, "multiple": 0, "true_false": 0}
    headers = {"X-CSRF-Token": "csrf"}
    with patch("app.api.v1.learning.freeze_learning_source", return_value=source()):
        assert client.post("/learning-assessments",
                           headers=headers, json=body).status_code == 202
        assert client.post("/learning-assessments",
                           headers=headers, json=body).status_code == 202
        assert client.post("/learning-assessments", headers=headers,
                           json={**body, "request_id": str(uuid4())}).status_code == 409
    with storage() as session:
        assert len(session.scalars(select(Slot)).all()) == 1


def test_api_worker_complete_loop(api, storage):
    client, app, settings, _ = api
    task_id = str(uuid4())
    headers = {"X-CSRF-Token": "csrf"}
    with patch("app.api.v1.learning.freeze_learning_source", return_value=source()):
        response = client.post("/learning-assessments", headers=headers, json={
            "request_id": task_id, "document_id": 1, "single": 1, "multiple": 0, "true_false": 0})
    assert response.status_code == 202
    assert run_once(storage, settings, FakeModel)
    data = client.get("/learning-assessments/current").json()["assessment"]
    assert data["assessment_id"] == task_id and data["status"] == "READY"
    q = data["questions"][0]
    answer = q["options"].index("三日")
    result = client.post(f"/learning-assessments/{task_id}/submit", headers=headers,
                         json={"answers": {q["question_id"]: [answer]}}).json()
    assert result["result"]["score"] == 100
    assert result["questions"][0]["source_text_snapshot"] == source()[
        "units"][0]["source_text_snapshot"]


def test_invalid_candidate_types_and_answer_indices():
    base = {"slot": 0, "question_type": "SINGLE", "question": "应当在多久内完成这项工作？", "options": ["一天", "两天", "三天", "四天"],
            "correct_answer": [2], "explanation": "原文规定三天内完成这项工作。"}
    validate_candidate(Candidate(**base), "SINGLE")
    for change in ({"correct_answer": [9]}, {"correct_answer": [2, 2]}, {"explanation": "选项C是正确答案，请根据条款确认。"},
                   {"question_type": "MULTIPLE", "correct_answer": [2]}, {"options": ["一天"] * 4}):
        with pytest.raises(ValueError):
            value = {**base, **change}
            validate_candidate(Candidate(**value), value["question_type"])
    with pytest.raises(ValueError):
        Candidate(**{**base, "correct_answer": [True]})


def test_expired_content_physically_cleared(storage):
    ready(storage, expired=True)
    assert not run_once(storage, Settings(
        learning_assessment_enabled=True), FakeModel)
    with storage() as session:
        row = session.get(Slot, "u1")
        assert row.current_json is None and row.current_id is None and row.task_state == "EXPIRED"


def test_optimistic_write_conflict(storage):
    from sqlalchemy.orm.exc import StaleDataError
    task_id, _ = ready(storage)
    with storage() as first, storage() as second:
        a, b = first.get(Slot, "u1"), second.get(Slot, "u1")
        a.progress = "新状态"
        first.commit()
        b.progress = "旧页面覆盖"
        with pytest.raises(StaleDataError):
            second.commit()


class FakeModel:
    def __init__(self, reject=False): self.reject = reject; self.calls = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass

    def generate(self, messages, **kwargs):
        self.calls += 1
        payload = json.loads(messages[1]["content"])
        if kwargs["response_format"]["json_schema"]["name"] == "CandidateBatch":
            values = [{"slot": item["slot"], "question_type": item["question_type"],
                       "question": f"收到通知后应在几日内提交报告（题目{item['slot']}）？", "options": ["三日", "五日", "十日", "十五日"],
                       "correct_answer": [0, 1] if item["question_type"] == "MULTIPLE" else [0],
                       "explanation": "原文要求收到通知后三日内提交书面报告。"} for item in payload["assignments"]]
            result = {"questions": values}
        else:
            result = {"verdicts": [
                {"slot": item["slot"], "passed": not self.reject} for item in payload["questions"]]}
        return SimpleNamespace(content=encode(result), finish_reason="stop")


def test_generation_review_frozen_evidence_and_finite_retry():
    client = FakeModel()
    questions = generate_assessment(
        source(), {"SINGLE": 1, "MULTIPLE": 0, "TRUE_FALSE": 0}, client, lambda _: None)
    assert client.calls == 2
    assert questions[0]["options"][questions[0]["correct_answer"][0]] == "三日"
    assert questions[0]["source_text_snapshot"] == source()[
        "units"][0]["source_text_snapshot"]
    rejected = FakeModel(reject=True)
    with pytest.raises(ValueError, match="未形成"):
        generate_assessment(
            source(), {"SINGLE": 1, "MULTIPLE": 0, "TRUE_FALSE": 0}, rejected, lambda _: None)
    # 只有一条条款可用：首轮 + 3 轮补题各 1 次生成 + 1 次审校，之后停止，不会无限重试。
    assert rejected.calls == 8


def test_sampling_skips_short_units_and_retry_switches_unit():
    """过短条款不参与多选题；补题轮换用别的条款而不是原地重试。"""
    units = [{"primary_node_id": i, "knowledge_point": f"第{i}条",
              "source_text_snapshot": text} for i, text in enumerate([
                  "本办法自发布之日起施行。",  # 12字：任何题型都排在最后
                  "工作人员应当在收到通知后三日内提交书面报告，特殊情形经批准可以延期，延期不得超过五日。",  # 43字：够单选、不够多选
                  "第三条 " + "供应商应当具备独立法人资格、无重大违法记录、近三年无失信行为，并按要求提交资质材料。" * 2])]  # >60字：够多选
    src = {**source(), "units": units}
    seen: list[tuple[str, int]] = []

    class Recorder(FakeModel):
        def generate(self, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if kwargs["response_format"]["json_schema"]["name"] == "CandidateBatch":
                seen.extend((a["question_type"], a["evidence"]["primary_node_id"])
                            for a in payload["assignments"])
            return super().generate(messages, **kwargs)

    generate_assessment(
        src, {"SINGLE": 1, "MULTIPLE": 1, "TRUE_FALSE": 0}, Recorder(), lambda _: None)
    picked = dict(seen)  # 并发生成，记录顺序不定，按题型取
    assert picked["SINGLE"] != 0                                  # 单选不用12字条款
    assert picked["MULTIPLE"] == 2                                # 多选只能用最长条款
    seen.clear()
    with pytest.raises(ValueError, match="未形成"):
        generate_assessment(src, {"SINGLE": 1, "MULTIPLE": 0, "TRUE_FALSE": 0}, Recorder(
            reject=True), lambda _: None)
    assert seen[0][1] == 1                                        # 首轮用最近的合格条款
    assert {unit for _, unit in seen[1:3]} == {
        0, 2}              # 补题轮并行两个候选，且都换了条款
    # 条款试完后重置再轮一遍，四轮即停
    assert len(seen) == 6


def test_worker_success_failure_and_old_result(storage):
    settings = Settings(learning_assessment_enabled=True)
    old_id, old = ready(storage)
    failed_id = str(uuid4())
    with storage() as session:
        LearningService(session, "u1", settings).start(
            source(), {"SINGLE": 1, "MULTIPLE": 0, "TRUE_FALSE": 0}, failed_id)
    assert run_once(storage, settings, lambda: FakeModel(reject=True))
    with storage() as session:
        row = session.get(Slot, "u1")
        assert row.task_state == "FAILED" and row.current_id == old_id and row.pending_json is None
        # 内容类失败把具体通过数带给用户，且不含模型输出。
        assert "0/1" in row.error_message and "原检测保留" in row.error_message
        new_id = str(uuid4())
        LearningService(session, "u1", settings).start(
            source(), {"SINGLE": 1, "MULTIPLE": 0, "TRUE_FALSE": 0}, new_id)
    assert run_once(storage, settings, FakeModel)
    with storage() as session:
        row = session.get(Slot, "u1")
        assert row.current_id == new_id and row.task_state == "READY" and row.pending_json is None
        assert len(json.loads(row.current_json)["questions"]) == 1
        assert len(session.scalars(select(Slot)).all()) == 1


def test_worker_disabled_never_calls_model(storage):
    assert not run_once(storage, Settings(learning_assessment_enabled=False), lambda: (
        _ for _ in ()).throw(AssertionError()))


def test_timed_out_job_becomes_failed(storage):
    settings = Settings(learning_assessment_enabled=True)
    with storage() as session:
        row = LearningService(session, "u1", settings).start(
            source(), {"SINGLE": 1}, str(uuid4()))
        row.task_created_at = utc_now() - timedelta(hours=1)
        session.commit()
    assert not run_once(storage, settings, FakeModel)
    with storage() as session:
        row = session.get(Slot, "u1")
        assert row.task_state == "FAILED" and row.pending_json is None


def test_source_uses_published_parse_and_preserves_children():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE index_profile(profile_name TEXT,active_index_run_id INTEGER);
        CREATE TABLE index_run(id INTEGER,status TEXT,activation_status TEXT);
        CREATE TABLE index_run_source(index_run_id INTEGER,document_id INTEGER,parse_run_id INTEGER,metadata_revision_id INTEGER);
        CREATE TABLE document_metadata_revision(id INTEGER,title TEXT,document_code TEXT,status TEXT);
        CREATE TABLE policy_node(id INTEGER,document_id INTEGER,parse_run_id INTEGER,parent_id INTEGER,node_type TEXT,node_number TEXT,title TEXT,raw_text TEXT,content TEXT,order_no INTEGER);
        INSERT INTO index_profile VALUES('test',9);
        INSERT INTO index_run VALUES(9,'succeeded','active');
        INSERT INTO index_run_source VALUES(9,1,3,5);
        INSERT INTO document_metadata_revision VALUES(5,'测试制度','编号','effective');
        INSERT INTO policy_node VALUES(1,1,3,NULL,'chapter','第一章','总则','总则',NULL,1);
        INSERT INTO policy_node VALUES(2,1,3,1,'article','第一条',NULL,'工作人员应当在收到通知后三日内提交报告。',NULL,2);
        INSERT INTO policy_node VALUES(3,1,3,2,'item',NULL,NULL,'特殊情形可以延期。',NULL,3);
        INSERT INTO policy_node VALUES(4,1,4,NULL,'article','第二条',NULL,'未发布的草稿绝不可读取。',NULL,4);
    """)
    @contextmanager
    def read(): yield connection
    catalog = SimpleNamespace(_connection=read, profile_name="test")
    value = freeze_learning_source(catalog, 1, "SELECTED", [1])
    assert value["parse_run_id"] == 3 and len(value["units"]) == 1
    assert "特殊情形" in value["units"][0]["source_text_snapshot"]
    connection.rollback()
    with pytest.raises(ValueError, match="不属于"):
        freeze_learning_source(catalog, 1, "SELECTED", [4])
    connection.rollback()
    connection.execute(
        "UPDATE document_metadata_revision SET status='repealed'")
    connection.commit()
    with pytest.raises(ValueError, match="现行"):
        freeze_learning_source(catalog, 1, "FULL", [])
    connection.close()
