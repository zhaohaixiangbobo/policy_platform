"""文件说明：暴露任务、运行审核、索引发布、关系、流程和证据绑定管理接口。"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.application.auth_service import Principal
from app.application.ingestion_service import IngestionService, InvalidDocumentError, JobConflictError
from app.application.metadata_service import MetadataApplicationService
from app.application.evidence_binding_service import EvidenceBindingService
from app.application.process_service import ProcessConflictError, ProcessService
from app.application.publication_service import PublicationService, publication_dict
from app.application.relation_service import RelationConflictError, RelationService
from app.application.review_service import ReviewConflictError, ReviewService
from app.application.evidence_reference_validator import EvidenceReferenceValidator
from app.config import get_settings
from app.infrastructure.db.models import IngestionArtifact, IngestionJob, IngestionJobEvent, PolicyRelation, ReviewRecord, SystemConfig, UserAccount
from app.infrastructure.db.session import get_db_session
from app.schemas.admin import BatchCreateRequest, EvidenceBindRequest, EvidenceReferenceResponse, IndexPublicationCreateRequest, IndexStatusResponse, IngestionJobResponse, JobListResponse, JobPublishRequest, JobRetryRequest, MetadataDraftCreateRequest, MetadataRevisionUpdateRequest, MetadataReviewRequest, ParseNodeCorrectionRequest, PolicySeriesAssignRequest, ProcessCreateRequest, ProcessGraphUpdateRequest, ProcessReviewerRequest, ProcessSummary, RelationCreateRequest, RelationReviewRequest, RelationSummary, ReviewArticleTitleDecisionRequest, ReviewBatchDecisionRequest, ReviewDecisionRequest, ReviewDetail, ReviewItemDecisionRequest, ReviewQueuePage
from knowledge.config import KnowledgePaths
from knowledge.management import KnowledgeManagementService
from knowledge.metadata_service import KnowledgeMetadataService, MetadataConflictError
from knowledge.read_service import KnowledgeReadService

router = APIRouter(prefix="/admin", tags=["admin"])


def ingestion(session: Session) -> IngestionService:
    return IngestionService(session, KnowledgePaths(get_settings().knowledge_data_root))


def management() -> KnowledgeManagementService:
    return KnowledgeManagementService(KnowledgePaths(get_settings().knowledge_data_root))


def knowledge_reader() -> KnowledgeReadService:
    return KnowledgeReadService(KnowledgePaths(get_settings().knowledge_data_root))


def processes(session: Session) -> ProcessService:
    settings = get_settings()
    return ProcessService(session, EvidenceReferenceValidator(settings.knowledge_database_path))


def evidence_bindings(session: Session) -> EvidenceBindingService:
    return EvidenceBindingService(session, EvidenceReferenceValidator(get_settings().knowledge_database_path))


def relations(session: Session) -> RelationService:
    return RelationService(session, evidence_bindings(session))


def process_reviewer_user_id(session: Session) -> str | None:
    """环境变量优先，未设置时读取受审计Platform业务配置。"""

    configured = get_settings().process_reviewer_user_id
    if configured:
        return configured
    item = session.get(SystemConfig, "process_reviewer_user_id")
    if item is None:
        return None
    value = json.loads(item.value_json)
    return str(value) if value else None


def process_summary(process, revision) -> ProcessSummary:
    return ProcessSummary(id=process.id, name=process.name, description=process.description, revision_id=revision.id, revision_no=revision.revision_no, status=revision.status, graph=json.loads(revision.graph_json), updated_at=process.updated_at)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    state: str | None = None,
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_db_session),
    _principal: Principal = Depends(require_permission("admin.access")),
) -> JobListResponse:
    """返回服务端分页的入库任务，任务中心固定每页十条。"""

    if page < 1 or page_size != 10:
        raise HTTPException(status_code=422, detail="任务列表固定每页10条")
    items, total, counts = ingestion(session).list_jobs(
        state,
        page=page,
        page_size=page_size,
    )
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=10,
        counts=counts,
    )


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))):
    """返回任务、状态事件、产物和各运行审核记录的完整闭环。"""

    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    target_ids = {str(value) for value in (job.parse_run_id, job.chunk_run_id, job.index_run_id) if value is not None}
    reviews = list(session.scalars(select(ReviewRecord).where(ReviewRecord.target_id.in_(target_ids)).order_by(ReviewRecord.created_at)).all()) if target_ids else []
    events = list(session.scalars(select(IngestionJobEvent).where(IngestionJobEvent.job_id == job.id).order_by(IngestionJobEvent.id)).all())
    artifacts = list(session.scalars(select(IngestionArtifact).where(IngestionArtifact.job_id == job.id).order_by(IngestionArtifact.created_at)).all())
    return {
        "job": IngestionJobResponse.model_validate(job),
        "events": [{"id": item.id, "from_state": item.from_state, "to_state": item.to_state, "reason": item.reason, "run_type": item.run_type, "run_id": item.run_id, "actor_user_id": item.actor_user_id, "created_at": item.created_at} for item in events],
        "artifacts": [{"id": item.id, "artifact_type": item.artifact_type, "relative_path": item.relative_path, "sha256": item.sha256, "created_at": item.created_at} for item in artifacts],
        "reviews": [{"id": item.id, "target_type": item.target_type, "target_id": item.target_id, "outcome": item.outcome, "comment": item.comment, "warning_acceptance": item.warning_acceptance, "reviewer_user_id": item.reviewer_user_id, "created_at": item.created_at} for item in reviews],
    }


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(request: Request, file: UploadFile = File(...), task_name: str | None = Form(default=None), initial_document_status: Literal["effective", "repealed", "expired"] = Form(default="effective"), session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.ingestion.manage", csrf=True))):
    try:
        job = ingestion(session).create_job(file.filename or "", file.content_type, await file.read(), principal.user_id, initial_document_status=initial_document_status)
        if task_name and task_name.strip():
            job.task_name = task_name.strip()
            session.commit()
        return {"id": job.id, "state": job.state, "state_version": job.state_version}
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/batches", status_code=201)
def create_batch(payload: BatchCreateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.batch.manage", csrf=True))):
    item = ingestion(session).create_batch(payload.name, principal.user_id)
    return {"id": item.id, "name": item.name, "status": item.status, "file_count": item.file_count, "created_at": item.created_at}


@router.get("/batches")
def list_batches(session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))):
    return [
        {"id": item.id, "name": item.name, "status": item.status, "file_count": item.file_count, "created_by": item.created_by, "created_at": item.created_at, "completed_at": item.completed_at}
        for item in ingestion(session).list_batches()
    ]


@router.post("/batches/{batch_id}/jobs", status_code=status.HTTP_202_ACCEPTED)
async def upload_batch_job(batch_id: str, file: UploadFile = File(...), initial_document_status: Literal["effective", "repealed", "expired"] = Form(default="effective"), session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.batch.manage", csrf=True))):
    try:
        job = ingestion(session).create_job(
            file.filename or "", file.content_type, await file.read(), principal.user_id,
            initial_document_status=initial_document_status,
            batch_id=batch_id,
        )
        return {"id": job.id, "state": job.state, "state_version": job.state_version}
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/complete")
def complete_batch(batch_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("knowledge.batch.manage", csrf=True))):
    try:
        item = ingestion(session).complete_batch(batch_id)
        return {"id": item.id, "status": item.status, "file_count": item.file_count, "completed_at": item.completed_at}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/rework", status_code=status.HTTP_202_ACCEPTED)
async def create_rework_job(job_id: str, file: UploadFile = File(...), initial_document_status: Literal["effective", "repealed", "expired"] = Form(default="effective"), session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.parse.correct", csrf=True))):
    try:
        job = ingestion(session).create_job(
            file.filename or "", file.content_type, await file.read(), principal.user_id,
            initial_document_status=initial_document_status,
            rework_of_job_id=job_id,
        )
        return {"id": job.id, "state": job.state, "state_version": job.state_version, "rework_of_job_id": job_id}
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, payload: JobRetryRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.ingestion.manage", csrf=True))):
    try:
        return ingestion(session).retry(job_id, payload.expected_state_version, principal.user_id, payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (JobConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/publish")
def publish_job(job_id: str, payload: JobPublishRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.ingestion.manage", csrf=True))):
    """保留旧接口用于明确提示，V2发布必须通过全局索引发布请求。"""

    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.state_version != payload.expected_state_version:
        raise HTTPException(status_code=409, detail="任务状态已经变化，请刷新")
    raise HTTPException(status_code=409, detail="V2请在制度治理页创建全局索引快照并确认Alias发布")


@router.get("/reviews", response_model=ReviewQueuePage)
def review_queue(
    include_history: bool = True,
    processing_status: Literal["PENDING", "PROCESSED"] | None = None,
    target_type: Literal["PARSE_RUN", "CHUNK_RUN"] | None = None,
    keyword: str | None = None,
    review_state: Literal["ACTION_REQUIRED", "READY_TO_SUBMIT", "PASS", "PASS_WITH_WARNING", "REJECT", "FAILED"] | None = None,
    sort_by: Literal["UPDATED_DESC", "OLDEST_PENDING", "TITLE_ASC"] = "UPDATED_DESC",
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_db_session),
    _principal: Principal = Depends(require_permission("admin.access")),
) -> ReviewQueuePage:
    """返回服务端筛选分页的审核运行，正式页面固定每页十条。"""

    if page < 1 or page_size != 10:
        raise HTTPException(status_code=422, detail="审核运行列表固定每页10条")
    result = ReviewService(
        session, ingestion(session), management(), knowledge_reader()
    ).search_queue(
        include_history=include_history,
        processing_status=processing_status,
        target_type=target_type,
        keyword=keyword,
        review_state=review_state,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    return ReviewQueuePage.model_validate(result)


@router.get("/reviews/{job_id}", response_model=ReviewDetail)
def review_detail(job_id: str, target_type: str | None = None, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> ReviewDetail:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="审核任务不存在")
    selected_type = target_type or ("PARSE_RUN" if job.state == "PARSE_REVIEW" else "CHUNK_RUN")
    if selected_type not in {"PARSE_RUN", "CHUNK_RUN"}:
        raise HTTPException(status_code=422, detail="审核对象类型非法")
    target_id = job.parse_run_id if selected_type == "PARSE_RUN" else job.chunk_run_id
    try:
        return ReviewDetail.model_validate(knowledge_reader().review_detail(selected_type, int(target_id or 0)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reviews/{job_id}/pdf", response_class=FileResponse)
def review_pdf(job_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> FileResponse:
    job = session.get(IngestionJob, job_id)
    if job is None or job.parse_run_id is None:
        raise HTTPException(status_code=404, detail="审核PDF不可用")
    try:
        path = knowledge_reader().resolve_parse_pdf(job.parse_run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=f"parse-run-{job.parse_run_id}.pdf", content_disposition_type="inline")


@router.post("/reviews/{job_id}/decision")
def review_decision(job_id: str, payload: ReviewDecisionRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("admin.access", csrf=True))):
    try:
        job = session.get(IngestionJob, job_id)
        permission = "knowledge.chunk.review" if job and job.state == "CHUNK_REVIEW" else "knowledge.parse.review"
        if permission not in principal.permissions:
            raise HTTPException(status_code=403, detail="当前用户无权审核该运行")
        return ReviewService(session, ingestion(session), management(), knowledge_reader()).decide(job_id, payload.outcome, payload.comment, payload.warning_acceptance, principal.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reviews/{job_id}/items/decision")
def review_item_decision(job_id: str, payload: ReviewItemDecisionRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("admin.access", csrf=True))):
    job = session.get(IngestionJob, job_id)
    permission = "knowledge.chunk.review" if job and job.state == "CHUNK_REVIEW" else "knowledge.parse.review"
    if permission not in principal.permissions:
        raise HTTPException(status_code=403, detail="当前用户无权审核该运行")
    try:
        return ReviewService(session, ingestion(session), management(), knowledge_reader()).decide_item(job_id, payload.target_type, payload.target_id, payload.action, payload.comment, payload.corrected_value, principal.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reviews/{job_id}/items/batch-decision")
def review_batch_decision(job_id: str, payload: ReviewBatchDecisionRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("admin.access", csrf=True))):
    """批量操作限定在一个当前运行内，并在知识库中原子提交。"""

    job = session.get(IngestionJob, job_id)
    permission = "knowledge.chunk.review" if payload.target_type == "chunk_issue" else "knowledge.parse.review"
    if permission not in principal.permissions:
        raise HTTPException(status_code=403, detail="当前用户无权批量审核该运行")
    try:
        return ReviewService(session, ingestion(session), management(), knowledge_reader()).decide_items(
            job_id, payload.target_type, payload.target_ids, payload.action,
            payload.comment, principal.user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reviews/{job_id}/article-title-decision")
def review_article_title_decision(job_id: str, payload: ReviewArticleTitleDecisionRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.parse.review", csrf=True))):
    """人工确认启发式条标题，不对已批准历史运行做原位修改。"""

    try:
        return ReviewService(session, ingestion(session), management(), knowledge_reader()).decide_article_title(
            job_id, payload.node_id, payload.mode, payload.title, payload.comment, principal.user_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/indexes", response_model=IndexStatusResponse)
def index_status(_principal: Principal = Depends(require_permission("admin.access"))) -> IndexStatusResponse:
    return IndexStatusResponse.model_validate(knowledge_reader().index_status())


@router.get("/index-publications")
def list_index_publications(session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))):
    service = PublicationService(session, ingestion(session))
    return [
        publication_dict(
            item,
            can_retry=item.status == "FAILED" and service.has_complete_bindings(item.id),
        )
        for item in service.list()
    ]


@router.post("/index-publications", status_code=202)
def create_index_publication(payload: IndexPublicationCreateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.index.publish", csrf=True))):
    try:
        return publication_dict(PublicationService(session, ingestion(session), management()).create(
            payload.document_ids, principal.user_id
        ))
    except (JobConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/index-publications/{request_id}/publish")
def publish_index_publication(request_id: str, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.index.publish", csrf=True))):
    try:
        return publication_dict(PublicationService(session, ingestion(session)).queue_publish(
            request_id, principal.user_id
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/index-publications/{request_id}/retry")
def retry_index_publication(request_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("knowledge.index.publish", csrf=True))):
    try:
        return publication_dict(PublicationService(session, ingestion(session)).retry(request_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/knowledge/evidence-catalog")
def evidence_catalog(keyword: str | None = None, _principal: Principal = Depends(require_permission("admin.access"))):
    return knowledge_reader().evidence_catalog(keyword)


@router.get("/knowledge/documents")
def managed_documents(
    keyword: str | None = None,
    metadata_status: Literal["ACTION_REQUIRED", "DRAFT", "PENDING_REVIEW", "APPROVED", "PUBLISHED", "REJECTED"] | None = None,
    sort_by: Literal["ACTION_REQUIRED", "UPDATED_DESC", "PUBLISH_DATE_DESC", "TITLE_ASC"] = "ACTION_REQUIRED",
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_db_session),
    _principal: Principal = Depends(require_permission("admin.access")),
):
    """按治理优先级列出正式文件版本，正式页面固定每页十条。"""

    if page < 1 or page_size != 10:
        raise HTTPException(status_code=422, detail="制度治理列表固定每页10条")

    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        return MetadataApplicationService(session, knowledge, ingestion(session)).search(
            keyword=keyword,
            metadata_status=metadata_status,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )


@router.get("/knowledge/series")
def policy_series(_principal: Principal = Depends(require_permission("admin.access"))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        return knowledge.list_series()


@router.put("/knowledge/documents/{document_id}/series")
def assign_policy_series(document_id: int, payload: PolicySeriesAssignRequest, _principal: Principal = Depends(require_permission("knowledge.metadata.manage", csrf=True))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return knowledge.assign_series(
                document_id, series_id=payload.series_id, canonical_title=payload.canonical_title
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (MetadataConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/knowledge/documents/{document_id}/parse-corrections", status_code=201)
def create_parse_correction(document_id: int, payload: ParseNodeCorrectionRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.parse.correct", csrf=True))):
    changes = payload.model_dump(
        include={"title", "node_number", "node_type", "parent_id", "order_no"},
        exclude_unset=True,
    )
    try:
        source_job = session.scalar(select(IngestionJob).where(
            IngestionJob.document_id == document_id,
            IngestionJob.parse_run_id == payload.source_parse_run_id,
        ).order_by(IngestionJob.created_at.desc()))
        if source_job is None:
            raise LookupError("原入库任务不存在")
        if source_job.document_id != document_id or source_job.parse_run_id != payload.source_parse_run_id:
            raise ValueError("原任务、制度文件和ParseRun不匹配")
        result = management().create_parse_correction(
            payload.source_parse_run_id,
            payload.source_node_id,
            changes,
            principal.user_id,
        )
        job = ingestion(session).create_structure_rework(
            source_job.id, int(result["id"]), principal.user_id
        )
        return {"parse_run": result, "job": IngestionJobResponse.model_validate(job)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (JobConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/knowledge/documents/{document_id}/metadata")
def metadata_detail(document_id: int, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return MetadataApplicationService(session, knowledge, ingestion(session)).detail(document_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/documents/{document_id}/metadata/drafts", status_code=201)
def create_metadata_draft(document_id: int, payload: MetadataDraftCreateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.metadata.manage", csrf=True))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return MetadataApplicationService(session, knowledge, ingestion(session)).create_draft(
                document_id, principal.user_id, payload.request_type, payload.change_reason
            )
        except (LookupError, MetadataConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/knowledge/documents/{document_id}/metadata/{revision_id}")
def update_metadata_revision(document_id: int, revision_id: int, payload: MetadataRevisionUpdateRequest, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("knowledge.metadata.manage", csrf=True))):
    values = payload.model_dump(exclude_unset=True)
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return MetadataApplicationService(session, knowledge, ingestion(session)).update(
                document_id, revision_id, values
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (MetadataConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/knowledge/documents/{document_id}/metadata/{revision_id}/submit")
def submit_metadata_revision(document_id: int, revision_id: int, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.metadata.manage", csrf=True))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return MetadataApplicationService(session, knowledge, ingestion(session)).submit(
                document_id, revision_id, principal.user_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (MetadataConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/knowledge/documents/{document_id}/metadata/{revision_id}/review")
def review_metadata_revision(document_id: int, revision_id: int, payload: MetadataReviewRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("knowledge.metadata.review", csrf=True))):
    with KnowledgeMetadataService(get_settings().knowledge_database_path) as knowledge:
        try:
            return MetadataApplicationService(session, knowledge, ingestion(session)).review(
                document_id, revision_id, payload.approved, principal.user_id, payload.comment
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (MetadataConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/relations", response_model=list[RelationSummary])
def list_relations(session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> list[RelationSummary]:
    return [RelationSummary.model_validate(item) for item in relations(session).list()]


@router.post("/relations", response_model=RelationSummary, status_code=201)
def create_relation(payload: RelationCreateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_relation.manage", csrf=True))) -> RelationSummary:
    try:
        item = relations(session).create(**payload.model_dump(), actor_user_id=principal.user_id)
        return RelationSummary.model_validate(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/relations/{relation_id}/evidence", response_model=list[EvidenceReferenceResponse])
def relation_evidence(relation_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> list[EvidenceReferenceResponse]:
    if session.get(PolicyRelation, relation_id) is None:
        raise HTTPException(status_code=404, detail="制度关系不存在")
    return [EvidenceReferenceResponse.model_validate(item) for item in evidence_bindings(session).list(["POLICY_RELATION"], relation_id)]


@router.post("/relations/{relation_id}/evidence", response_model=EvidenceReferenceResponse, status_code=201)
def bind_relation_evidence(relation_id: str, payload: EvidenceBindRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_relation.manage", csrf=True))) -> EvidenceReferenceResponse:
    relation = session.get(PolicyRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="制度关系不存在")
    if relation.status not in {"DRAFT", "NEEDS_REVIEW"}:
        raise HTTPException(status_code=409, detail="仅草稿或待复核关系可绑定证据")
    try:
        item = evidence_bindings(session).bind(
            owner_type="POLICY_RELATION",
            owner_id=relation.id,
            actor_user_id=principal.user_id,
            **payload.model_dump(exclude={"owner_kind", "cell_id"}),
        )
        return EvidenceReferenceResponse.model_validate(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/relations/{relation_id}/evidence/{reference_id}", status_code=204)
def delete_relation_evidence(relation_id: str, reference_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("policy_relation.manage", csrf=True))) -> None:
    relation = session.get(PolicyRelation, relation_id)
    if relation is None or relation.status not in {"DRAFT", "NEEDS_REVIEW"}:
        raise HTTPException(status_code=409, detail="当前关系不可编辑")
    try:
        evidence_bindings(session).delete(reference_id, relation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/relations/{relation_id}/submit", response_model=RelationSummary)
def submit_relation(relation_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("policy_relation.manage", csrf=True))) -> RelationSummary:
    try:
        return RelationSummary.model_validate(relations(session).submit(relation_id))
    except (LookupError, RelationConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/relations/{relation_id}/review", response_model=RelationSummary)
def review_relation(relation_id: str, payload: RelationReviewRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_relation.review", csrf=True))) -> RelationSummary:
    try:
        return RelationSummary.model_validate(relations(session).review(relation_id, payload.approved, payload.comment, principal.user_id))
    except (LookupError, RelationConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/processes", response_model=list[ProcessSummary])
def list_processes(session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> list[ProcessSummary]:
    return [process_summary(*row) for row in processes(session).list()]


@router.get("/processes/{process_id}/evidence", response_model=list[EvidenceReferenceResponse])
def process_evidence(process_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("admin.access"))) -> list[EvidenceReferenceResponse]:
    try:
        return [EvidenceReferenceResponse.model_validate(item) for item in processes(session).list_evidence(process_id)]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/processes/{process_id}/evidence", response_model=EvidenceReferenceResponse, status_code=201)
def bind_process_evidence(process_id: str, payload: EvidenceBindRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_process.manage", csrf=True))) -> EvidenceReferenceResponse:
    if payload.owner_kind not in {"NODE", "EDGE"}:
        raise HTTPException(status_code=422, detail="流程证据只能绑定节点或连线")
    try:
        item = processes(session).bind_evidence(
            process_id,
            payload.owner_kind,
            payload.cell_id,
            payload.model_dump(exclude={"owner_kind", "cell_id"}),
            principal.user_id,
        )
        return EvidenceReferenceResponse.model_validate(item)
    except (LookupError, ProcessConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/processes/{process_id}/evidence/{reference_id}", status_code=204)
def delete_process_evidence(process_id: str, reference_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("policy_process.manage", csrf=True))) -> None:
    try:
        processes(session).delete_evidence(process_id, reference_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProcessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/processes", response_model=ProcessSummary, status_code=201)
def create_process(payload: ProcessCreateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_process.manage", csrf=True))) -> ProcessSummary:
    return process_summary(*processes(session).create(payload.name, payload.description, principal.user_id))


@router.put("/processes/{process_id}/graph", response_model=ProcessSummary)
def update_process(process_id: str, payload: ProcessGraphUpdateRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_process.manage", csrf=True))) -> ProcessSummary:
    try:
        return process_summary(*processes(session).update_graph(process_id, payload.graph, payload.change_summary, principal.user_id))
    except (LookupError, ProcessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/processes/{process_id}/submit", response_model=ProcessSummary)
def submit_process(process_id: str, session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("policy_process.manage", csrf=True))) -> ProcessSummary:
    try:
        return process_summary(*processes(session).submit(process_id))
    except (LookupError, ProcessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/processes/{process_id}/review", response_model=ProcessSummary)
def review_process(process_id: str, approved: bool, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_process.review", csrf=True))) -> ProcessSummary:
    try:
        return process_summary(*processes(session).review(process_id, principal.user_id, process_reviewer_user_id(session), approved))
    except (LookupError, ProcessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/processes/{process_id}/publish", response_model=ProcessSummary)
def publish_process(process_id: str, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("policy_process.publish", csrf=True))) -> ProcessSummary:
    try:
        return process_summary(*processes(session).publish(process_id, principal.user_id))
    except (LookupError, ProcessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/settings/process-reviewer")
def get_process_reviewer(session: Session = Depends(get_db_session), _principal: Principal = Depends(require_permission("system.user.manage"))):
    return {"user_id": process_reviewer_user_id(session)}


@router.put("/settings/process-reviewer")
def set_process_reviewer(payload: ProcessReviewerRequest, session: Session = Depends(get_db_session), principal: Principal = Depends(require_permission("system.user.manage", csrf=True))):
    user = session.get(UserAccount, payload.user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(status_code=422, detail="固定流程审核管理员必须是有效平台用户")
    item = session.get(SystemConfig, "process_reviewer_user_id")
    if item is None:
        item = SystemConfig(key="process_reviewer_user_id", value_json=json.dumps(user.id), updated_by=principal.user_id)
        session.add(item)
    else:
        item.value_json = json.dumps(user.id)
        item.updated_by = principal.user_id
    session.commit()
    return {"user_id": user.id}
