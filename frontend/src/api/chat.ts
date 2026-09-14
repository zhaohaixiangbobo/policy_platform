/** 文件说明：封装M3会话、M4反馈及受控诊断Platform API。 */
import { requestJson } from './httpClient';
import type {
  ChatMessage,
  ChatSession,
  ChatTurnResponse,
  DiagnosticDetail,
  DiagnosticListResponse,
  DocumentSelection,
  QueryScopeCapabilities,
  QueryScope,
} from '../types/chat';

export const listSessions = () => requestJson<ChatSession[]>('/api/v1/chat/sessions');

export const createSession = () =>
  requestJson<ChatSession>('/api/v1/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({}),
  });

export const renameSession = (sessionId: string, title: string) =>
  requestJson<ChatSession>(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });

export const deleteSession = (sessionId: string) =>
  requestJson<void>(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });

export const listMessages = async (sessionId: string): Promise<ChatMessage[]> => {
  const result = await requestJson<{ items: ChatMessage[] }>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
  );
  return result.items;
};

export const getQueryScopeCapabilities = () =>
  requestJson<QueryScopeCapabilities>('/api/v1/chat/query-capabilities');

export const sendMessage = (
  sessionId: string,
  content: string,
  queryScope: QueryScope,
  documentSelection: DocumentSelection,
  signal?: AbortSignal,
) =>
  requestJson<ChatTurnResponse>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: 'POST',
      body: JSON.stringify({
        content,
        query_scope: queryScope,
        document_selection: documentSelection,
      }),
      signal,
    },
  );

export const submitFeedback = (
  messageId: string,
  payload: {
    rating: 'up' | 'down';
    reason_codes: string[];
    comment?: string;
    mark_as_eval_case: boolean;
  },
) =>
  requestJson(`/api/v1/chat/messages/${encodeURIComponent(messageId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export interface DiagnosticFilters {
  request_id?: string;
  keyword?: string;
  answer_status?: string;
  quality_gate_status?: string;
  has_down_feedback?: boolean;
  date_from?: string;
  date_to?: string;
}

export const listDiagnostics = (filters: DiagnosticFilters = {}) => {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value));
  });
  const query = params.toString();
  return requestJson<DiagnosticListResponse>(`/api/v1/diagnostics/requests${query ? `?${query}` : ''}`);
};

export const getDiagnostic = (requestId: string) =>
  requestJson<DiagnosticDetail>(
    `/api/v1/diagnostics/requests/${encodeURIComponent(requestId)}`,
  );
