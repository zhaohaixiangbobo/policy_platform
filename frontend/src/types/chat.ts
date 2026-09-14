/** 文件说明：定义M3/M4平台会话、公开回答快照与反馈类型。 */
export type AnswerStatus = 'ANSWER' | 'INSUFFICIENT_EVIDENCE' | 'CONFLICT';
export type QueryScope = 'CURRENT' | 'HISTORICAL';
export type DocumentSelection =
  | { mode: 'ALL' }
  | { mode: 'SELECTED'; document_ids: number[] };

export interface QueryScopeCapabilities {
  active_index_run_id: number;
  current_document_count: number;
  historical_document_count: number;
}

export interface ChatSession {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CitationSnapshot {
  citation_version: string;
  evidence_uid_version: string;
  label: string;
  evidence_uid: string;
  document_id: number;
  primary_node_id: number | null;
  parse_run_id: number;
  chunk_run_id: number;
  index_run_id: number;
  chunk_id: number;
  document_title: string;
  document_code: string | null;
  document_status: string;
  source_reference: string;
  path_text: string | null;
  page_start: number | null;
  page_end: number | null;
  quote: string;
  truncated: boolean;
  snapshot_hash: string;
}

export interface ConflictSnapshot {
  topic: string;
  positions: Array<{ statement: string; citations: string[] }>;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  query_scope: QueryScope;
  document_selection_mode: 'ALL' | 'SELECTED';
  selected_document_ids: number[];
  resolved_document_scope_mode: 'ALL' | 'SELECTED';
  query_index_run_id: number | null;
  access_scope_version: string;
  access_scope_hash: string;
  access_scope_count: number;
  content: string;
  answer_status: AnswerStatus | null;
  request_id: string;
  engine_request_id: string | null;
  contract_version: string | null;
  index_run_id: number | null;
  quality_gate: {
    version: string;
    status: string;
    semantic_verification: string;
    reason_codes: string[];
  } | null;
  citations: CitationSnapshot[];
  conflicts: ConflictSnapshot[];
  created_at: string;
}

export interface ChatTurnResponse {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface DiagnosticSummary {
  request_id: string;
  question_summary: string;
  answer_status: string;
  quality_gate_version: string | null;
  quality_gate_status: string | null;
  citation_count: number;
  index_run_id: number | null;
  latency_total_ms: number | null;
  has_down_feedback: boolean;
  created_at: string;
}

export interface DiagnosticListResponse {
  items: DiagnosticSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface DiagnosticDetail {
  question: ChatMessage;
  answer: ChatMessage;
  rag_version: string | null;
  generator_model: string | null;
  generator_revision: string | null;
  prompt_version: string | null;
  prompt_schema_version: string | null;
  retrieval_config_hash: string | null;
  context_config_hash: string | null;
  latency_total_ms: number | null;
  diagnostic_scope: 'public_response_snapshot_only';
}
