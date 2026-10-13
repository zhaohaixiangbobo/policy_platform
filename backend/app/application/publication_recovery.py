"""文件说明：发布部分成功的受控对账；以冻结来源、管理员确认和实际Alias为依据。"""

from sqlalchemy import select, func, or_

from app.application.ingestion_service import IngestionService, JobConflictError
from app.application.publication_service import PublicationService
from app.application.task_lease import claim, LeaseExecution
from app.infrastructure.db.models import IndexPublicationRequest, IngestionJobEvent, MetadataChangeRequest, utc_now


def finish_publication(session, publication, bindings):
    """同一Platform事务收尾任务、元数据和请求；重复执行不重复追加任务事件。"""
    for binding, job in bindings:
        if binding.source_role != "CHANGE" or job is None:
            continue
        if (job.parse_run_id, job.chunk_run_id) != (binding.parse_run_id, binding.chunk_run_id):
            raise JobConflictError("任务版本与已发布来源不一致，停止自动收尾")
        if job.state == "PUBLISHED":
            if job.index_run_id != publication.index_run_id:
                raise JobConflictError("任务已发布到其他IndexRun")
            continue
        if job.state not in {"PUBLISHING", "PUBLISH_QUEUED", "READY_TO_PUBLISH"}:
            raise JobConflictError(f"任务状态{job.state}需要人工核查")
        session.add(IngestionJobEvent(job_id=job.id, from_state=job.state, to_state="PUBLISHED",
                                     reason="已核验Alias目标及冻结来源，完成发布收尾",
                                     run_type="INDEX_RUN", run_id=publication.index_run_id))
        job.state, job.stage_progress = "PUBLISHED", 100
        job.state_version += 1
        job.index_run_id = publication.index_run_id
        job.error_code = job.error_summary = job.failed_stage = None
        job.retryable = False
    ids = [binding.metadata_revision_id for binding, _job in bindings if binding.source_role == "CHANGE"]
    for change in session.scalars(select(MetadataChangeRequest).where(
            MetadataChangeRequest.metadata_revision_id.in_(ids), MetadataChangeRequest.status == "APPROVED")):
        change.status, change.open_slot = "PUBLISHED", None
    publication.status = "PUBLISHED"
    publication.published_at = publication.published_at or utc_now()
    publication.error_summary = None
    session.commit()


def pending_recovery(session):
    """有界只读扫描；网络调用结果不明时不因租约过期推断操作失败。"""
    rows = session.scalars(select(IndexPublicationRequest).where(
        IndexPublicationRequest.status.in_(["BUILDING", "PUBLISHING", "READY_TO_PUBLISH"]),
        or_(IndexPublicationRequest.lease_expires_at.is_(None),
            IndexPublicationRequest.lease_expires_at <= func.clock_timestamp()),
    ).order_by(IndexPublicationRequest.created_at).limit(50)).all()
    return [{"id": row.id, "status": row.status, "index_run_id": row.index_run_id,
             "base_index_run_id": row.base_index_run_id, "confirmed": bool(row.published_by)} for row in rows]


def recover_publication(factory, management, paths, request_id, *, executor_stopped=False):
    if not executor_stopped:
        raise ValueError("必须先确认旧执行者和外部调用均已结束")
    with factory() as session:
        current = session.get(IndexPublicationRequest, request_id)
        if current is not None and current.status == "PUBLISHED":
            return
        token = claim(session, IndexPublicationRequest, key_name="id", owner="admin-recovery",
                      eligible=[IndexPublicationRequest.id == request_id,
                                IndexPublicationRequest.status == "PUBLISHING"],
                      order_by=IndexPublicationRequest.created_at)
    if token is None:
        raise JobConflictError("请求不在待恢复发布状态或仍有有效租约")
    with LeaseExecution(factory, token) as execution, factory() as session, execution.guard_session(session):
        request = session.get(IndexPublicationRequest, request_id)
        if not request.published_by or request.index_run_id is None:
            raise JobConflictError("缺少管理员确认或目标IndexRun，禁止恢复发布")
        service = PublicationService(session, IngestionService(session, paths), management)
        bindings = service.bound_sources(request_id)
        expected = {(b.document_id, b.parse_run_id, b.chunk_run_id, b.metadata_revision_id) for b, _ in bindings}
        actual = {(int(s['document_id']), int(s['parse_run_id']), int(s['chunk_run_id']), int(s['metadata_revision_id']))
                  for s in management.index_run_sources(request.index_run_id)}
        if actual != expected:
            raise JobConflictError("IndexRun与冻结来源不完全一致")
        session.commit()
        management.publish_index_run(request.index_run_id, recover=True, recover_base=request.base_index_run_id)
        execution.check()
        finish_publication(session, request, bindings)


def requeue_interrupted_build(factory, paths, request_id, *, executor_stopped=False):
    """管理员确认旧构建结束后重排同一冻结请求；Indexer按来源和配置幂等复用。"""
    if not executor_stopped:
        raise ValueError("必须先确认旧构建执行者及外部调用已经结束")
    with factory() as session:
        token = claim(session, IndexPublicationRequest, key_name="id", owner="admin-build-recovery",
                      eligible=[IndexPublicationRequest.id == request_id, IndexPublicationRequest.status == "BUILDING"],
                      order_by=IndexPublicationRequest.created_at)
    if token is None:
        raise JobConflictError("构建任务仍有有效租约或不在BUILDING状态")
    with LeaseExecution(factory, token) as execution, factory() as session, execution.guard_session(session):
        request = session.get(IndexPublicationRequest, request_id)
        bindings = PublicationService(session, IngestionService(session, paths)).bound_sources(request_id)
        for binding, job in bindings:
            if binding.source_role != "CHANGE" or job is None:
                continue
            if job.state not in {"INDEX_QUEUED", "INDEXING"}:
                raise JobConflictError("绑定任务状态变化，不能重排构建")
            if job.state == "INDEXING":
                session.add(IngestionJobEvent(job_id=job.id, from_state="INDEXING", to_state="INDEX_QUEUED",
                                             reason="管理员确认旧执行者停止，恢复同一冻结构建请求"))
                job.state = "INDEX_QUEUED"
                job.state_version += 1
                job.attempt_no += 1
        request.status, request.error_summary = "BUILD_QUEUED", None
        session.commit()
