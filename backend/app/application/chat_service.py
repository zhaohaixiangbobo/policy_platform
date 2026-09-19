"""文件说明：实现平台会话、公开RAG回答快照、反馈和候选评测案例业务。"""

import json
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.db.models import (
    ChatMessage,
    ChatSession,
    ConflictPosition,
    EvalCandidate,
    MessageCitation,
    MessageConflict,
    MessageFeedback,
    PlatformAuditLog,
    utc_now,
)
from knowledge.contracts import QueryResponse as RagQueryResponse
from knowledge.service import KnowledgeService, KnowledgeServiceError
from app.application.auth_service import Principal
from app.application.conversation_context import STRATEGY_VERSION, resolve_context
from app.application.query_scope_service import QueryScopeResolver, ResolvedQueryScope
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionSummary,
    ChatTurnResponse,
    CitationSnapshot,
    ConflictPositionSnapshot,
    ConflictSnapshot,
    MessageFeedbackCreate,
    MessageFeedbackResponse,
    QueryScopeCapabilitiesResponse,
    QualityGateSummary,
)


class ChatResourceNotFoundError(LookupError):
    """会话或消息不存在。"""


class FeedbackConflictError(RuntimeError):
    """同一回答已经提交反馈。"""


def message_response(message: ChatMessage) -> ChatMessageResponse:
    quality_gate = None
    if message.quality_gate_version:
        quality_gate = QualityGateSummary(
            version=message.quality_gate_version,
            status=message.quality_gate_status or "",
            semantic_verification=message.quality_gate_semantic_verification or "",
            reason_codes=json.loads(message.quality_gate_reason_codes or "[]"),
        )
    conflicts = [
        ConflictSnapshot(
            topic=conflict.topic,
            positions=[
                ConflictPositionSnapshot(
                    statement=position.statement,
                    citations=json.loads(position.citation_labels),
                )
                for position in conflict.positions
            ],
        )
        for conflict in message.conflicts
    ]
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        query_scope=message.query_scope,
        document_selection_mode=message.document_selection_mode,
        selected_document_ids=[
            int(value) for value in json.loads(message.selected_document_ids_json or "[]")
        ],
        resolved_document_scope_mode=message.resolved_document_scope_mode,
        query_index_run_id=message.query_index_run_id,
        access_scope_version=message.access_scope_version,
        access_scope_hash=message.access_scope_hash,
        access_scope_count=message.access_scope_count,
        content=message.content,
        answer_status=message.answer_status,
        answerability=message.answerability,
        reason_code=message.reason_code,
        missing_fields=json.loads(message.missing_fields_json) if message.missing_fields_json is not None else None,
        clarification_question=message.clarification_question,
        rewrite_used=message.rewrite_used,
        retrieval_query=message.retrieval_query,
        rewrite_strategy_version=message.rewrite_strategy_version,
        conversation_context=json.loads(message.conversation_context_json) if message.conversation_context_json else None,
        request_id=message.request_id,
        engine_request_id=message.engine_request_id,
        contract_version=message.contract_version,
        index_run_id=message.index_run_id,
        quality_gate=quality_gate,
        citations=[CitationSnapshot.model_validate(item) for item in message.citations],
        conflicts=conflicts,
        created_at=message.created_at,
    )


class ChatService:
    """编排Platform持久化和唯一进程内RAG查询调用。"""

    def __init__(
        self,
        session: Session,
        client: KnowledgeService,
        principal: Principal,
        query_scope_resolver: QueryScopeResolver,
    ) -> None:
        self._session = session
        self._client = client
        self._principal = principal
        self._actor_user_id = principal.user_id
        self._query_scope_resolver = query_scope_resolver

    def query_scope_capabilities(self) -> QueryScopeCapabilitiesResponse:
        capabilities = self._query_scope_resolver.capabilities(self._principal)
        return QueryScopeCapabilitiesResponse(
            active_index_run_id=capabilities.index_run_id,
            current_document_count=capabilities.current_document_count,
            historical_document_count=capabilities.historical_document_count,
        )

    def list_sessions(self) -> list[ChatSessionSummary]:
        sessions = self._session.scalars(
            select(ChatSession)
            .where(ChatSession.status == "ACTIVE", ChatSession.created_by == self._actor_user_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
        return [ChatSessionSummary.model_validate(item) for item in sessions]

    def create_session(self, title: str | None) -> ChatSessionSummary:
        session = ChatSession(title=(title or "新会话").strip() or "新会话", created_by=self._actor_user_id)
        self._session.add(session)
        self._session.commit()
        return ChatSessionSummary.model_validate(session)

    def rename_session(self, session_id: str, title: str) -> ChatSessionSummary:
        chat_session = self._active_session(session_id)
        chat_session.title = title.strip()
        chat_session.updated_at = utc_now()
        self._session.commit()
        return ChatSessionSummary.model_validate(chat_session)

    def delete_session(self, session_id: str) -> None:
        chat_session = self._active_session(session_id)
        chat_session.status = "DELETED"
        chat_session.updated_at = utc_now()
        self._session.commit()

    def list_messages(self, session_id: str) -> list[ChatMessageResponse]:
        self._active_session(session_id)
        messages = self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .options(
                selectinload(ChatMessage.citations),
                selectinload(ChatMessage.conflicts).selectinload(MessageConflict.positions),
            )
            .order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
        return [message_response(item) for item in messages]

    async def send_message(
        self,
        session_id: str,
        content: str,
        request_id: str,
        query_scope: str = "CURRENT",
        document_selection_mode: str = "ALL",
        selected_document_ids: tuple[int, ...] = (),
    ) -> ChatTurnResponse:
        chat_session = self._active_session(session_id)
        resolved_scope = self._query_scope_resolver.resolve(
            self._principal,
            selection_mode=document_selection_mode,  # type: ignore[arg-type]
            selected_document_ids=selected_document_ids,
            query_scope=query_scope,  # type: ignore[arg-type]
        )
        # 只考虑最近的完整一轮；会话所有权已由_active_session验证。
        recent = self._session.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(2)).all()
        previous = recent[0] if len(recent) == 2 and recent[0].role == "assistant" and recent[1].role == "user" else None
        question = recent[1] if previous else None
        message_id = str(uuid.uuid4())
        retrieval_query, context = resolve_context(content.strip(), message_id, previous, question, resolved_scope, selected_document_ids)
        rewritten = retrieval_query != content.strip()
        user_message = ChatMessage(
            id=message_id,
            session_id=session_id,
            role="user",
            query_scope=query_scope,
            **self._scope_fields(resolved_scope, selected_document_ids),
            content=content.strip(),
            retrieval_query=retrieval_query,
            rewrite_used=rewritten,
            rewrite_strategy_version=STRATEGY_VERSION,
            conversation_context_json=json.dumps(context, ensure_ascii=False),
            request_id=request_id,
        )
        if chat_session.title == "新会话":
            chat_session.title = content.strip()[:30]
        chat_session.updated_at = utc_now()
        self._session.add(user_message)
        self._session.commit()

        try:
            response = await self._client.query(
                retrieval_query,
                request_id,
                query_scope,
                resolved_scope.rag_document_scope_mode,
                resolved_scope.document_ids
                if resolved_scope.rag_document_scope_mode == "SELECTED"
                else (),
            )
            self._validate_citation_scope(response, resolved_scope, request_id)
            # 补全发生在Platform，公开provenance记录实际执行事实。
            response = response.model_copy(update={"provenance": response.provenance.model_copy(update={"rewrite_used": rewritten})})
        except KnowledgeServiceError as exc:
            # 失败问题由前端保留为可重试草稿，平台库不留下无法判断状态的孤立用户消息。
            self._session.execute(delete(ChatMessage).where(ChatMessage.id == user_message.id))
            self._session.add(
                PlatformAuditLog(
                    request_id=request_id,
                    actor_user_id=self._actor_user_id,
                    auth_provider="SESSION",
                    action="rag_query",
                    object_type="chat_session",
                    object_id=session_id,
                    status="failed",
                    error_code=exc.code,
                )
            )
            self._session.commit()
            raise

        assistant = self._build_assistant_message(
            session_id,
            request_id,
            query_scope,
            response,
            resolved_scope,
            selected_document_ids,
        )
        assistant.retrieval_query = retrieval_query
        assistant.rewrite_strategy_version = STRATEGY_VERSION
        assistant.conversation_context_json = json.dumps(context, ensure_ascii=False)
        self._session.add(assistant)
        self._session.flush()
        self._session.add(
            PlatformAuditLog(
                request_id=request_id,
                actor_user_id=self._actor_user_id,
                auth_provider="SESSION",
                action="rag_query",
                object_type="chat_message",
                object_id=assistant.id,
                status="succeeded",
                latency_ms=response.latency_ms.total,
            )
        )
        self._session.commit()
        return ChatTurnResponse(
            user_message=message_response(user_message),
            assistant_message=message_response(assistant),
        )

    def submit_feedback(
        self, message_id: str, payload: MessageFeedbackCreate, request_id: str
    ) -> MessageFeedbackResponse:
        message = self._session.scalar(
            select(ChatMessage)
            .where(ChatMessage.id == message_id, ChatMessage.role == "assistant")
            .options(selectinload(ChatMessage.feedback))
        )
        if message is None:
            raise ChatResourceNotFoundError
        if message.feedback is not None:
            raise FeedbackConflictError
        feedback = MessageFeedback(
            message_id=message_id,
            rating=payload.rating,
            primary_reason_code=payload.reason_codes[0] if payload.reason_codes else None,
            reason_codes=json.dumps(payload.reason_codes, ensure_ascii=False),
            comment=payload.comment,
            mark_as_eval_case=payload.mark_as_eval_case,
        )
        self._session.add(feedback)
        eval_candidate = None
        if payload.mark_as_eval_case:
            question = self._previous_question(message)
            eval_candidate = EvalCandidate(
                feedback=feedback,
                request_id=request_id,
                question_snapshot=question.content,
                answer_snapshot=message.content,
                citation_snapshot=json.dumps(
                    [citation.model_dump(mode="json") for citation in message_response(message).citations],
                    ensure_ascii=False,
                ),
            )
            self._session.add(eval_candidate)
        self._session.add(
            PlatformAuditLog(
                request_id=request_id,
                actor_user_id=self._actor_user_id,
                auth_provider="SESSION",
                action="submit_feedback",
                object_type="chat_message",
                object_id=message_id,
                status="succeeded",
            )
        )
        self._session.commit()
        return MessageFeedbackResponse(
            id=feedback.id,
            message_id=message_id,
            rating=payload.rating,
            reason_codes=payload.reason_codes,
            comment=payload.comment,
            mark_as_eval_case=payload.mark_as_eval_case,
            eval_candidate_id=eval_candidate.id if eval_candidate else None,
            created_at=feedback.created_at,
        )

    def _active_session(self, session_id: str) -> ChatSession:
        chat_session = self._session.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.status == "ACTIVE",
                ChatSession.created_by == self._actor_user_id,
            )
        )
        if chat_session is None:
            raise ChatResourceNotFoundError
        return chat_session

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

    @staticmethod
    def _build_assistant_message(
        session_id: str,
        request_id: str,
        query_scope: str,
        response: RagQueryResponse,
        resolved_scope: ResolvedQueryScope,
        selected_document_ids: tuple[int, ...],
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role="assistant",
            query_scope=query_scope,
            **ChatService._scope_fields(resolved_scope, selected_document_ids),
            content=response.answer,
            answer_status=response.status,
            answerability=response.answerability,
            reason_code=response.reason_code,
            missing_fields_json=json.dumps(response.missing_fields, ensure_ascii=False) if response.missing_fields is not None else None,
            clarification_question=response.clarification_question,
            request_id=request_id,
            engine_request_id=response.request_id,
            contract_version=response.contract_version,
            rag_version=response.provenance.rag_version,
            generator_model=response.provenance.generator_model,
            generator_revision=response.provenance.generator_revision,
            prompt_version=response.provenance.prompt_version,
            prompt_schema_version=response.provenance.prompt_schema_version,
            retrieval_config_hash=response.provenance.retrieval_config_hash,
            context_config_hash=response.provenance.context_config_hash,
            index_run_id=response.retrieval.index_run_id,
            rewrite_used=response.provenance.rewrite_used,
            quality_gate_version=response.quality_gate.version,
            quality_gate_status=response.quality_gate.status,
            quality_gate_semantic_verification=response.quality_gate.semantic_verification,
            quality_gate_reason_codes=json.dumps(
                response.quality_gate.reason_codes, ensure_ascii=False
            ),
            latency_total_ms=response.latency_ms.total,
            warnings_snapshot=json.dumps(response.warnings, ensure_ascii=False),
        )
        message.citations = [MessageCitation(**citation.model_dump()) for citation in response.citations]
        message.conflicts = [
            MessageConflict(
                topic=conflict.topic,
                order_no=conflict_index,
                positions=[
                    ConflictPosition(
                        statement=position.statement,
                        citation_labels=json.dumps(position.citations, ensure_ascii=False),
                        order_no=position_index,
                    )
                    for position_index, position in enumerate(conflict.positions)
                ],
            )
            for conflict_index, conflict in enumerate(response.conflicts)
        ]
        return message

    @staticmethod
    def _validate_citation_scope(
        response: RagQueryResponse,
        resolved_scope: ResolvedQueryScope,
        request_id: str,
    ) -> None:
        """对公开 Citation 再做边界校验，避免上游错误状态进入 Platform 历史。"""

        response_index_run_ids = {
            response.retrieval.index_run_id,
            *(item.index_run_id for item in response.citations),
        }
        if response_index_run_ids != {resolved_scope.index_run_id}:
            raise KnowledgeServiceError(
                code="RAG_INDEX_SCOPE_MISMATCH",
                message="查询期间正式索引已切换，请按原问题重试",
                request_id=request_id,
                retryable=True,
                http_status=503,
            )
        normalized = {
            "effective": "effective", "现行有效": "effective",
            "repealed": "repealed", "已废止": "repealed",
            "expired": "expired", "已失效": "expired",
        }
        allowed_statuses = (
            {"effective"}
            if resolved_scope.query_scope == "CURRENT"
            else {"repealed", "expired"}
        )
        invalid_status = [
            item.label for item in response.citations
            if normalized.get(
                item.document_status.strip().lower(),
                item.document_status.strip().lower(),
            ) not in allowed_statuses
        ]
        if invalid_status:
            raise KnowledgeServiceError(
                code="RAG_SCOPE_MISMATCH",
                message="制度知识服务返回了不符合查询范围的引用",
                request_id=request_id,
                retryable=False,
                http_status=502,
            )
        allowed_document_ids = set(resolved_scope.document_ids)
        invalid_documents = [
            item.label
            for item in response.citations
            if item.document_id not in allowed_document_ids
        ]
        if invalid_documents:
            raise KnowledgeServiceError(
                code="RAG_DOCUMENT_SCOPE_MISMATCH",
                message="制度知识服务返回了超出授权范围的引用",
                request_id=request_id,
                retryable=False,
                http_status=502,
            )

    @staticmethod
    def _scope_fields(
        resolved_scope: ResolvedQueryScope,
        selected_document_ids: tuple[int, ...],
    ) -> dict[str, object]:
        """用户选择和Platform最终范围分别持久化，避免把ALL误写成空集合。"""

        selected = (
            sorted(set(int(value) for value in selected_document_ids))
            if resolved_scope.user_selection_mode == "SELECTED"
            else []
        )
        return {
            "document_selection_mode": resolved_scope.user_selection_mode,
            "selected_document_ids_json": json.dumps(selected),
            "resolved_document_scope_mode": resolved_scope.rag_document_scope_mode,
            "query_index_run_id": resolved_scope.index_run_id,
            "access_scope_version": resolved_scope.access_policy_version,
            "access_scope_hash": resolved_scope.scope_hash,
            "access_scope_count": len(resolved_scope.document_ids),
        }
