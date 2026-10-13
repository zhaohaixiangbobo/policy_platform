"""文件说明：个人一次性自测API；统一开关、身份/制度权限与CSRF，保护未提交答案。"""

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import require_permission
from app.application.learning_service import LearningService, public_current
from app.application.material_service import MaterialService
from app.config import get_settings
from app.infrastructure.db.session import get_db_session
from knowledge.learning_source import freeze_learning_source


def enabled():
    if not get_settings().learning_assessment_enabled:
        raise HTTPException(404, "学习检测未启用")


router = APIRouter(prefix="/learning-assessments",
                   tags=["learning-assessments"], dependencies=[Depends(enabled)])


class CreateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    document_id: int = Field(gt=0)
    scope: Literal["FULL", "SELECTED"] = "FULL"
    node_ids: list[int] = Field(default_factory=list, max_length=500)
    single: int = Field(default=5, ge=0, le=15)
    multiple: int = Field(default=3, ge=0, le=15)
    true_false: int = Field(default=2, ge=0, le=15)

    @model_validator(mode="after")
    def check_counts(self):
        if not 1 <= self.single + self.multiple + self.true_false <= get_settings().learning_assessment_max_questions:
            raise ValueError("题量总数必须在1至配置上限之间，最高15题")
        if (self.scope == "FULL" and self.node_ids) or (self.scope == "SELECTED" and not self.node_ids):
            raise ValueError("全文范围不传节点；指定范围必须选择章节或条款")
        return self


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, Annotated[list[StrictInt],
                                 Field(max_length=5)]] = Field(max_length=15)


def access(request, principal, document_id):
    if not request.app.state.document_access_resolver.resolve(principal).allows(document_id):
        raise HTTPException(403, "当前用户无权访问该制度")


def checked_slot(request, principal, session):
    service = LearningService(session, principal.user_id, get_settings())
    row = service.slot()
    if row:
        for value in (row.current_json, row.pending_json):
            if value:
                data = json.loads(value)
                access(request, principal, data.get(
                    "source", data)["document_id"])
        session.commit()
    return service, row


def conflict(session, exc):
    session.rollback()
    raise HTTPException(409, "检测已发生变化，请刷新后重试" if isinstance(
        exc, (IntegrityError, StaleDataError)) else str(exc)) from exc


@router.post("", status_code=202)
def create(body: CreateAssessment, request: Request,
           principal=Depends(require_permission("knowledge.document.read", csrf=True)), session: Session = Depends(get_db_session)):
    access(request, principal, body.document_id)
    try:
        source = freeze_learning_source(
            request.app.state.knowledge_catalog, body.document_id, body.scope, body.node_ids)
        counts = {"SINGLE": body.single, "MULTIPLE": body.multiple,
                  "TRUE_FALSE": body.true_false}
        if sum(counts.values()) > len(source["units"]) * 2:
            raise ValueError("所选范围完整条款不足，每条最多两题，请减少题量或扩大范围")
        row = LearningService(session, principal.user_id, get_settings()).start(
            source, counts, str(body.request_id))
        return {"task_id": row.task_id, "status": row.task_state}
    except (ValueError, IntegrityError, StaleDataError) as exc:
        conflict(session, exc)


@router.get("/current")
def current(request: Request, principal=Depends(require_permission("knowledge.document.read")), session: Session = Depends(get_db_session)):
    try:
        _, row = checked_slot(request, principal, session)
        if row is None:
            return {"task": None, "assessment": None}
        data = public_current(json.loads(row.current_json)
                              ) if row.current_json else None
        if data:
            try:
                document = request.app.state.knowledge_catalog.get_document(
                    data["document_id"])
                data["version_changed"] = (
                    document.active_parse_run_id != data["parse_run_id"]
                    or getattr(document, "status", "现行有效") != "现行有效"
                    or getattr(document, "title", data["document_title"]) != data["document_title"]
                )
            except LookupError:
                data["version_changed"] = True
        return {"task": {"task_id": row.task_id, "status": row.task_state,
                         "progress": row.progress, "error": row.error_message} if row.task_id else None,
                "assessment": data}
    except StaleDataError as exc:
        conflict(session, exc)


@router.put("/{assessment_id}/answers")
def save_answers(assessment_id: UUID, body: Answers, request: Request,
                 principal=Depends(require_permission("knowledge.document.read", csrf=True)), session: Session = Depends(get_db_session)):
    try:
        service, _ = checked_slot(request, principal, session)
        service.submit(str(assessment_id), body.answers, draft=True)
        return {"saved": True}
    except (ValueError, StaleDataError) as exc:
        conflict(session, exc)


@router.get("/{assessment_id}/questions/{question_id}/materials")
def question_materials(assessment_id: UUID, question_id: str, request: Request,
                       principal=Depends(require_permission(
                           "knowledge.document.read")),
                       _material=Depends(require_permission("material.read")),
                       session: Session = Depends(get_db_session)):
    # 仅从本人未过期的已提交快照取材，不接受客户端题干、选项或任意检索文本。
    _, row = checked_slot(request, principal, session)
    if not row or row.current_id != str(assessment_id) or not row.current_json:
        raise HTTPException(404, "检测已过期或不可访问")
    data = json.loads(row.current_json)
    if data["status"] != "SUBMITTED":
        raise HTTPException(409, "提交检测后可查看辅助资料")
    question = next(
        (q for q in data["questions"] if q["question_id"] == question_id), None)
    if not question:
        raise HTTPException(404, "题目不存在")
    # 快照中的短句独立匹配；不使用整份制度标题、错误选项和生成解析扩大主题。
    import re
    # 知识点只保留条款标题：“正文条款 769”“第三条”等编号无主题含义，还会挤占前10个匹配词名额。
    point = re.sub(r"正文条款\s*\d+|第[0-9零〇一二三四五六七八九十百千]+[编章节条款项]",
                   " ", question.get("knowledge_point", ""))
    query = " ".join([point] +
                     re.split(r"[，。；：、\n]", question.get("source_text_snapshot", "")))
    result = MaterialService(session, principal).recommend(query)
    by_kind = {}
    for item in result["items"]:
        by_kind.setdefault(item["kind"], item)
    result["items"] = list(by_kind.values())
    return result


@router.post("/{assessment_id}/submit")
def submit(assessment_id: UUID, body: Answers, request: Request,
           principal=Depends(require_permission("knowledge.document.read", csrf=True)), session: Session = Depends(get_db_session)):
    try:
        service, _ = checked_slot(request, principal, session)
        return public_current(service.submit(str(assessment_id), body.answers))
    except (ValueError, StaleDataError) as exc:
        conflict(session, exc)
