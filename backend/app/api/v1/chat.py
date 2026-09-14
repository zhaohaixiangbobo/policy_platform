"""文件说明：暴露M3平台会话问答及M4结构化反馈接口。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import get_chat_service, require_permission
from app.application.auth_service import Principal
from app.application.chat_service import ChatResourceNotFoundError, ChatService, FeedbackConflictError
from app.application.query_scope_service import QueryScopeResolutionError
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageListResponse,
    ChatSessionCreate,
    ChatSessionSummary,
    ChatSessionUpdate,
    ChatTurnResponse,
    MessageFeedbackCreate,
    MessageFeedbackResponse,
    QueryScopeCapabilitiesResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions(service: ChatService = Depends(get_chat_service)) -> list[ChatSessionSummary]:
    return service.list_sessions()


@router.get("/query-capabilities", response_model=QueryScopeCapabilitiesResponse)
def query_capabilities(
    service: ChatService = Depends(get_chat_service),
) -> QueryScopeCapabilitiesResponse:
    """返回当前用户在active IndexRun中可使用的状态范围。"""

    try:
        return service.query_scope_capabilities()
    except QueryScopeResolutionError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=exc.message,
            headers={"X-Error-Code": exc.code},
        ) from exc


@router.post("/sessions", response_model=ChatSessionSummary, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ChatSessionCreate,
    service: ChatService = Depends(get_chat_service),
    _principal: Principal = Depends(require_permission("chat.write", csrf=True)),
) -> ChatSessionSummary:
    return service.create_session(payload.title)


@router.patch("/sessions/{session_id}", response_model=ChatSessionSummary)
def rename_session(
    session_id: str,
    payload: ChatSessionUpdate,
    service: ChatService = Depends(get_chat_service),
    _principal: Principal = Depends(require_permission("chat.write", csrf=True)),
) -> ChatSessionSummary:
    try:
        return service.rename_session(session_id, payload.title)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
    _principal: Principal = Depends(require_permission("chat.write", csrf=True)),
) -> Response:
    try:
        service.delete_session(session_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
def list_messages(
    session_id: str, service: ChatService = Depends(get_chat_service)
) -> ChatMessageListResponse:
    try:
        return ChatMessageListResponse(items=service.list_messages(session_id))
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc


@router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
async def send_message(
    session_id: str,
    payload: ChatMessageCreate,
    request: Request,
    service: ChatService = Depends(get_chat_service),
    _principal: Principal = Depends(require_permission("chat.write", csrf=True)),
) -> ChatTurnResponse:
    try:
        return await service.send_message(
            session_id,
            payload.content,
            request.state.request_id,
            payload.query_scope,
            payload.document_selection.mode,
            tuple(getattr(payload.document_selection, "document_ids", [])),
        )
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except QueryScopeResolutionError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=exc.message,
            headers={"X-Error-Code": exc.code},
        ) from exc


@router.post("/messages/{message_id}/feedback", response_model=MessageFeedbackResponse)
def submit_feedback(
    message_id: str,
    payload: MessageFeedbackCreate,
    request: Request,
    service: ChatService = Depends(get_chat_service),
    _principal: Principal = Depends(require_permission("chat.write", csrf=True)),
) -> MessageFeedbackResponse:
    try:
        return service.submit_feedback(message_id, payload, request.state.request_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="助手回答不存在") from exc
    except FeedbackConflictError as exc:
        raise HTTPException(status_code=409, detail="该回答已经提交反馈") from exc
