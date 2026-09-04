"""文件说明：从平台保存的公开回答快照生成可筛选的本机受控诊断视图。"""

from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.application.chat_service import ChatResourceNotFoundError, message_response
from app.infrastructure.db.models import ChatMessage, MessageConflict, MessageFeedback
from app.schemas.diagnostics import (
    DiagnosticListResponse,
    DiagnosticRequestDetail,
    DiagnosticRequestSummary,
)


class DiagnosticService:
    """不读取debug数据，仅展示rag_api_v1_1公开字段的已保存子集。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_requests(
        self,
        *,
        request_id: str | None,
        keyword: str | None,
        answer_status: str | None,
        quality_gate_status: str | None,
        has_down_feedback: bool | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> DiagnosticListResponse:
        conditions = [ChatMessage.role == "assistant"]
        if request_id:
            conditions.append(ChatMessage.request_id.ilike(f"%{request_id.strip()}%"))
        if answer_status:
            conditions.append(ChatMessage.answer_status == answer_status)
        if quality_gate_status:
            conditions.append(ChatMessage.quality_gate_status == quality_gate_status)
        if has_down_feedback is True:
            conditions.append(ChatMessage.feedback.has(MessageFeedback.rating == "down"))
        if has_down_feedback is False:
            conditions.append(~ChatMessage.feedback.has(MessageFeedback.rating == "down"))
        if date_from:
            conditions.append(
                ChatMessage.created_at >= datetime.combine(date_from, time.min, timezone.utc)
            )
        if date_to:
            conditions.append(
                ChatMessage.created_at <= datetime.combine(date_to, time.max, timezone.utc)
            )
        if keyword:
            question_message = aliased(ChatMessage)
            question_match = (
                select(question_message.id)
                .where(
                    question_message.session_id == ChatMessage.session_id,
                    question_message.role == "user",
                    question_message.content.ilike(f"%{keyword.strip()}%"),
                )
                .exists()
            )
            conditions.append(question_match)
        base = select(ChatMessage).where(*conditions)
        total = self._session.scalar(
            select(func.count()).select_from(ChatMessage).where(*conditions)
        ) or 0
        answers = self._session.scalars(
            base.options(
                selectinload(ChatMessage.citations),
                selectinload(ChatMessage.feedback),
            )
            .order_by(ChatMessage.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = []
        for answer in answers:
            question = self._previous_question(answer)
            items.append(
                DiagnosticRequestSummary(
                    request_id=answer.request_id,
                    question_summary=question.content[:120],
                    answer_status=answer.answer_status or "",
                    quality_gate_version=answer.quality_gate_version,
                    quality_gate_status=answer.quality_gate_status,
                    citation_count=len(answer.citations),
                    index_run_id=answer.index_run_id,
                    latency_total_ms=answer.latency_total_ms,
                    has_down_feedback=bool(
                        answer.feedback and answer.feedback.rating == "down"
                    ),
                    created_at=answer.created_at,
                )
            )
        return DiagnosticListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    def get_request(self, request_id: str) -> DiagnosticRequestDetail:
        answer = self._session.scalar(
            select(ChatMessage)
            .where(ChatMessage.role == "assistant", ChatMessage.request_id == request_id)
            .options(
                selectinload(ChatMessage.citations),
                selectinload(ChatMessage.conflicts).selectinload(MessageConflict.positions),
            )
            .order_by(ChatMessage.created_at.desc())
        )
        if answer is None:
            raise ChatResourceNotFoundError
        question = self._previous_question(answer)
        return DiagnosticRequestDetail(
            question=message_response(question),
            answer=message_response(answer),
            rag_version=answer.rag_version,
            generator_model=answer.generator_model,
            generator_revision=answer.generator_revision,
            prompt_version=answer.prompt_version,
            prompt_schema_version=answer.prompt_schema_version,
            retrieval_config_hash=answer.retrieval_config_hash,
            context_config_hash=answer.context_config_hash,
            latency_total_ms=answer.latency_total_ms,
        )

    def _previous_question(self, answer: ChatMessage) -> ChatMessage:
        question = self._session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == answer.session_id,
                ChatMessage.role == "user",
                ChatMessage.created_at <= answer.created_at,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        )
        if question is None:
            raise ChatResourceNotFoundError
        return question
