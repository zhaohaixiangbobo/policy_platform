/**
 * 文件说明：封装第二期任务中心、审核队列和流程修订管理接口。
 */
import { requestJson } from './httpClient';

export interface IngestionJob {
  id: string;
  task_name: string;
  original_filename: string;
  initial_document_status: 'effective' | 'repealed' | 'expired';
  state: string;
  state_version: number;
  stage_progress: number;
  attempt_no: number;
  retryable: boolean;
  failed_stage: string | null;
  error_code: string | null;
  document_id: number | null;
  parse_run_id: number | null;
  chunk_run_id: number | null;
  index_run_id: number | null;
  batch_id: string | null;
  rework_of_job_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface JobListResponse {
  items: IngestionJob[];
  total: number;
  page: number;
  page_size: 10;
  counts: Record<string, number>;
}

export interface ReviewQueueItem {
  target_type: 'PARSE_RUN' | 'CHUNK_RUN';
  target_id: string;
  job_id: string;
  document_id: number | null;
  title: string;
  document_code: string | null;
  state: string;
  issue_count: number;
  review_status: string;
  processing_status: 'PENDING' | 'PROCESSED';
  review_outcome: 'PASS' | 'PASS_WITH_WARNING' | 'REJECT' | null;
  display_state: 'ACTION_REQUIRED' | 'READY_TO_SUBMIT' | 'PASS' | 'PASS_WITH_WARNING' | 'REJECT' | 'FAILED';
  created_at: string;
  updated_at: string;
}

export interface ReviewQueuePage {
  items: ReviewQueueItem[];
  total: number;
  page: number;
  page_size: 10;
  counts: Record<string, number>;
}

export interface ReviewDetail {
  target_type: 'PARSE_RUN' | 'CHUNK_RUN';
  run: Record<string, unknown> & { document_title?: string; document_code?: string; page_count?: number; render_engine?: string; review_status?: string };
  metrics: Record<string, unknown>;
  nodes: Array<Record<string, unknown> & { id: number; parent_id: number | null; title: string | null; text: string | null; path_text: string | null; page_start: number | null; page_end: number | null; node_type: string; rule_id?: string | null; review_status?: string; review_reason?: string | null }>;
  fields: Array<Record<string, unknown> & { id: number; field_name: string; raw_value: string; normalized_value: string | null; confidence: number }>;
  chunks: Array<Record<string, unknown> & { id: number; chunk_key: string; chunk_type: string; is_retrievable: boolean; path_text: string | null; retrieval_text: string; char_count: number; token_count: number | null; page_start: number | null; page_end: number | null; sources: Array<Record<string, unknown>> }>;
  issues: Array<Record<string, unknown> & { id: number; issue_code: string; issue_type: string; severity: string; message: string; resolved: boolean }>;
  pdf_available: boolean;
}

export interface EvidenceCatalogNode {
  id: number; parent_id: number | null; node_type: string; node_number: string | null;
  title: string | null; text: string; path_text: string | null; page_start: number | null; page_end: number | null; order_no: number;
}

export interface EvidenceCatalogDocument {
  id: number; title: string; document_code: string | null; status: string; active_parse_run_id: number; nodes: EvidenceCatalogNode[];
}

export interface EvidenceReference {
  id: string; owner_type: string; owner_id: string; document_id: number; parse_run_id: number;
  primary_node_id: number; page_start: number | null; page_end: number | null; quote_snapshot: string;
  snapshot_hash: string; validation_status: string; validated_at: string | null; created_by: string; created_at: string;
}

export interface RelationSummary {
  id: string; relation_type: 'CITES' | 'SUPERSEDES' | 'REPEALS' | 'RELATED_TOPIC' | 'CONFLICTS_WITH';
  source_document_id: number; source_parse_run_id: number; target_document_id: number; target_parse_run_id: number;
  status: string; rationale: string | null; valid_from: string | null; valid_to: string | null;
  created_by: string; reviewed_by: string | null; reviewed_at: string | null; created_at: string; updated_at: string;
}

export interface ProcessSummary {
  id: string;
  name: string;
  description: string | null;
  revision_id: string;
  revision_no: number;
  status: 'DRAFT' | 'PENDING_REVIEW' | 'APPROVED' | 'PUBLISHED';
  graph: { nodes?: unknown[]; edges?: unknown[] };
  updated_at: string;
}

export function listJobs(state?: string, page = 1) {
  const query = new URLSearchParams({ page: String(page), page_size: '10' });
  if (state) query.set('state', state);
  return requestJson<JobListResponse>(`/api/v1/admin/jobs?${query.toString()}`);
}

export interface JobDetail {
  job: IngestionJob;
  events: Array<{ id: number; from_state: string | null; to_state: string; reason: string | null; run_type: string | null; run_id: number | null; actor_user_id: string | null; created_at: string }>;
  artifacts: Array<{ id: string; artifact_type: string; relative_path: string; sha256: string | null; created_at: string }>;
  reviews: Array<{ id: string; target_type: string; target_id: string; outcome: string; comment: string | null; reviewer_user_id: string; created_at: string }>;
}

export function getJobDetail(jobId: string) { return requestJson<JobDetail>(`/api/v1/admin/jobs/${jobId}`); }

export async function uploadJob(file: File, taskName?: string, initialDocumentStatus = 'effective') {
  const form = new FormData();
  form.append('file', file);
  if (taskName) form.append('task_name', taskName);
  form.append('initial_document_status', initialDocumentStatus);
  const csrf = document.cookie.split('; ').find((item) => item.startsWith('policy_platform_csrf='))?.split('=')[1];
  const response = await fetch('/api/v1/admin/jobs', {
    method: 'POST', body: form, credentials: 'same-origin',
    headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {},
  });
  if (!response.ok) {
    const payload = (await response.json()) as { detail?: string };
    throw new Error(payload.detail ?? '上传失败');
  }
  return response.json() as Promise<{ id: string; state: string }>;
}

export function listReviews(params?: {
  include_history?: boolean;
  processing_status?: 'PENDING' | 'PROCESSED';
  target_type?: 'PARSE_RUN' | 'CHUNK_RUN';
  keyword?: string;
  review_state?: string;
  sort_by?: 'UPDATED_DESC' | 'OLDEST_PENDING' | 'TITLE_ASC';
  page?: number;
}) {
  const query = new URLSearchParams();
  query.set('include_history', String(params?.include_history ?? true));
  if (params?.processing_status) query.set('processing_status', params.processing_status);
  if (params?.target_type) query.set('target_type', params.target_type);
  if (params?.keyword) query.set('keyword', params.keyword);
  if (params?.review_state) query.set('review_state', params.review_state);
  query.set('sort_by', params?.sort_by ?? 'UPDATED_DESC');
  query.set('page', String(params?.page ?? 1));
  query.set('page_size', '10');
  return requestJson<ReviewQueuePage>(`/api/v1/admin/reviews?${query.toString()}`);
}

export function decideReview(jobId: string, outcome: 'PASS' | 'PASS_WITH_WARNING' | 'REJECT', comment?: string) {
  return requestJson<IngestionJob>(`/api/v1/admin/reviews/${jobId}/decision`, {
    method: 'POST', body: JSON.stringify({ outcome, comment, warning_acceptance: outcome === 'PASS_WITH_WARNING' ? comment : null }),
  });
}

export function getReviewDetail(jobId: string, targetType?: 'PARSE_RUN' | 'CHUNK_RUN') {
  return requestJson<ReviewDetail>(`/api/v1/admin/reviews/${jobId}${targetType ? `?target_type=${targetType}` : ''}`);
}

export function decideReviewItem(jobId: string, payload: { target_type: 'issue' | 'field' | 'node' | 'chunk_issue' | 'chunk'; target_id: number; action: 'confirm' | 'ignore' | 'reject' | 'correct'; comment?: string; corrected_value?: string }) {
  return requestJson<Record<string, unknown>>(`/api/v1/admin/reviews/${jobId}/items/decision`, { method: 'POST', body: JSON.stringify(payload) });
}

export function batchReviewItems(jobId: string, payload: { target_type: 'node' | 'issue' | 'chunk_issue'; target_ids: number[]; action: 'confirm' | 'ignore'; comment?: string }) {
  return requestJson<Record<string, unknown>>(`/api/v1/admin/reviews/${jobId}/items/batch-decision`, { method: 'POST', body: JSON.stringify(payload) });
}

export function decideArticleTitle(jobId: string, payload: { node_id: number; mode: 'TITLE' | 'CONTENT'; title?: string; comment?: string }) {
  return requestJson<Record<string, unknown>>(`/api/v1/admin/reviews/${jobId}/article-title-decision`, { method: 'POST', body: JSON.stringify(payload) });
}

export function reviewPdfUrl(jobId: string) {
  return `/api/v1/admin/reviews/${encodeURIComponent(jobId)}/pdf`;
}

export function publishJob(jobId: string, expectedStateVersion: number) {
  return requestJson<IngestionJob>(`/api/v1/admin/jobs/${jobId}/publish`, {
    method: 'POST', body: JSON.stringify({ expected_state_version: expectedStateVersion }),
  });
}

export interface ManagedDocument {
  id: number; file_name: string; series_id: number; series_key: string; canonical_title: string;
  document_version_no: number; latest_metadata_revision_id: number | null; approved_metadata_revision_id: number | null;
  active_metadata_revision_id: number | null; title: string | null; document_code: string | null;
  issuing_org: string | null; owner_department: string | null; publish_date: string | null;
  status: string; metadata_status: string; request_id: string | null; request_type: string | null;
  request_status: string; job_id: string | null; active_parse_run_id: number | null; active_chunk_run_id: number | null;
}

export interface MetadataRevision {
  id: number; document_id: number; revision_no: number; lifecycle_status: string;
  title: string | null; document_code: string | null; document_type: string | null;
  issuing_org: string | null; owner_department: string | null; publish_date: string | null;
  effective_date: string | null; expiry_date: string | null; status: string;
  version: string | null; authority_level: string | null; confidentiality_level: string | null;
  change_reason: string | null; repeal_date: string | null; repeal_reason: string | null;
  repeal_evidence: string | null; status_confirmation_note: string | null;
  source_type: string;
}

export interface ManagedDocumentDetail {
  document: Record<string, unknown> & { id: number; series_id: number; document_version_no: number };
  revisions: MetadataRevision[];
  candidates: Array<Record<string, unknown> & { id: number; field_name: string; raw_value: string; normalized_value: string | null; confidence: number; page_start: number | null; page_end: number | null }>;
  requests: Array<Record<string, unknown>>;
}

export interface PolicySeries { id: number; series_key: string; canonical_title: string; status: string; document_count: number }
export interface ManagedDocumentPage { items: ManagedDocument[]; total: number; page: number; page_size: number }
export interface IndexPublication { id: string; status: string; document_ids: number[]; index_run_id: number | null; base_index_run_id: number | null; snapshot_contract_version: string; alias_name: string; error_summary: string | null; can_retry: boolean; created_at: string; published_at: string | null }
export interface IngestionBatch { id: string; name: string; status: string; file_count: number; created_at: string; completed_at: string | null }

export const listManagedDocuments = (params?: { keyword?: string; metadata_status?: string; sort_by?: string; page?: number }) => {
  const query = new URLSearchParams();
  if (params?.keyword) query.set('keyword', params.keyword);
  if (params?.metadata_status) query.set('metadata_status', params.metadata_status);
  if (params?.sort_by) query.set('sort_by', params.sort_by);
  query.set('page', String(params?.page ?? 1));
  query.set('page_size', '10');
  return requestJson<ManagedDocumentPage>(`/api/v1/admin/knowledge/documents?${query.toString()}`);
};
export const getManagedDocument = (documentId: number) => requestJson<ManagedDocumentDetail>(`/api/v1/admin/knowledge/documents/${documentId}/metadata`);
export const listPolicySeries = () => requestJson<PolicySeries[]>('/api/v1/admin/knowledge/series');
export const assignPolicySeries = (documentId: number, payload: { series_id: number | null; canonical_title?: string }) => requestJson<Record<string, unknown>>(`/api/v1/admin/knowledge/documents/${documentId}/series`, { method: 'PUT', body: JSON.stringify(payload) });
export const createMetadataDraft = (documentId: number, requestType: 'CORRECTION' | 'REPEAL' | 'EXPIRY', changeReason?: string) => requestJson<{ revision: MetadataRevision }>(`/api/v1/admin/knowledge/documents/${documentId}/metadata/drafts`, { method: 'POST', body: JSON.stringify({ request_type: requestType, change_reason: changeReason }) });
export const updateMetadataRevision = (documentId: number, revisionId: number, payload: Partial<MetadataRevision>) => requestJson<MetadataRevision>(`/api/v1/admin/knowledge/documents/${documentId}/metadata/${revisionId}`, { method: 'PUT', body: JSON.stringify(payload) });
export const submitMetadataRevision = (documentId: number, revisionId: number) => requestJson<Record<string, unknown>>(`/api/v1/admin/knowledge/documents/${documentId}/metadata/${revisionId}/submit`, { method: 'POST' });
export const reviewMetadataRevision = (documentId: number, revisionId: number, approved: boolean, comment?: string) => requestJson<Record<string, unknown>>(`/api/v1/admin/knowledge/documents/${documentId}/metadata/${revisionId}/review`, { method: 'POST', body: JSON.stringify({ approved, comment }) });
export const listIndexPublications = () => requestJson<IndexPublication[]>('/api/v1/admin/index-publications');
export const createIndexPublication = (documentIds: number[]) => requestJson<IndexPublication>('/api/v1/admin/index-publications', { method: 'POST', body: JSON.stringify({ document_ids: documentIds }) });
export const confirmIndexPublication = (requestId: string) => requestJson<IndexPublication>(`/api/v1/admin/index-publications/${requestId}/publish`, { method: 'POST' });
export const retryIndexPublication = (requestId: string) => requestJson<IndexPublication>(`/api/v1/admin/index-publications/${requestId}/retry`, { method: 'POST' });
export const createParseCorrection = (documentId: number, payload: { source_parse_run_id: number; source_node_id: number; title?: string | null; node_number?: string | null; node_type?: string | null; parent_id?: number | null; order_no?: number | null }) => requestJson<Record<string, unknown>>(`/api/v1/admin/knowledge/documents/${documentId}/parse-corrections`, { method: 'POST', body: JSON.stringify(payload) });

export const createBatch = (name: string) => requestJson<IngestionBatch>('/api/v1/admin/batches', { method: 'POST', body: JSON.stringify({ name }) });
export const listBatches = () => requestJson<IngestionBatch[]>('/api/v1/admin/batches');
export const completeBatch = (batchId: string) => requestJson<IngestionBatch>(`/api/v1/admin/batches/${batchId}/complete`, { method: 'POST' });

export async function uploadBatchJob(batchId: string, file: File, initialDocumentStatus = 'effective') {
  const form = new FormData(); form.append('file', file); form.append('initial_document_status', initialDocumentStatus);
  const csrf = document.cookie.split('; ').find((item) => item.startsWith('policy_platform_csrf='))?.split('=')[1];
  const response = await fetch(`/api/v1/admin/batches/${encodeURIComponent(batchId)}/jobs`, { method: 'POST', body: form, credentials: 'same-origin', headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {} });
  if (!response.ok) { const payload = (await response.json()) as { detail?: string }; throw new Error(payload.detail ?? '批次文件上传失败'); }
  return response.json() as Promise<{ id: string; state: string }>;
}

export function getIndexStatus() {
  return requestJson<{ profile: Record<string, unknown> | null; runs: Array<Record<string, unknown>> }>('/api/v1/admin/indexes');
}

export function getEvidenceCatalog(keyword?: string) {
  return requestJson<EvidenceCatalogDocument[]>(`/api/v1/admin/knowledge/evidence-catalog${keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''}`);
}

export interface EvidenceBindingInput {
  owner_kind: 'NODE' | 'EDGE' | 'RELATION'; cell_id: string; document_id: number; parse_run_id: number;
  primary_node_id: number; page_start: number | null; page_end: number | null; quote_snapshot: string;
}

export function listProcessEvidence(processId: string) {
  return requestJson<EvidenceReference[]>(`/api/v1/admin/processes/${processId}/evidence`);
}

export function bindProcessEvidence(processId: string, payload: EvidenceBindingInput) {
  return requestJson<EvidenceReference>(`/api/v1/admin/processes/${processId}/evidence`, { method: 'POST', body: JSON.stringify(payload) });
}

export function deleteProcessEvidence(processId: string, referenceId: string) {
  return requestJson<void>(`/api/v1/admin/processes/${processId}/evidence/${referenceId}`, { method: 'DELETE' });
}

export function listRelations() { return requestJson<RelationSummary[]>('/api/v1/admin/relations'); }

export function createRelation(payload: Omit<RelationSummary, 'id' | 'status' | 'created_by' | 'reviewed_by' | 'reviewed_at' | 'created_at' | 'updated_at'>) {
  return requestJson<RelationSummary>('/api/v1/admin/relations', { method: 'POST', body: JSON.stringify(payload) });
}

export function listRelationEvidence(relationId: string) { return requestJson<EvidenceReference[]>(`/api/v1/admin/relations/${relationId}/evidence`); }
export function bindRelationEvidence(relationId: string, payload: EvidenceBindingInput) { return requestJson<EvidenceReference>(`/api/v1/admin/relations/${relationId}/evidence`, { method: 'POST', body: JSON.stringify(payload) }); }
export function submitRelation(relationId: string) { return requestJson<RelationSummary>(`/api/v1/admin/relations/${relationId}/submit`, { method: 'POST' }); }
export function reviewRelation(relationId: string, approved: boolean, comment?: string) { return requestJson<RelationSummary>(`/api/v1/admin/relations/${relationId}/review`, { method: 'POST', body: JSON.stringify({ approved, comment }) }); }

export function listProcesses() {
  return requestJson<ProcessSummary[]>('/api/v1/admin/processes');
}

export function createProcess(name: string, description?: string) {
  return requestJson<ProcessSummary>('/api/v1/admin/processes', {
    method: 'POST', body: JSON.stringify({ name, description }),
  });
}

export function saveProcessGraph(processId: string, graph: object, changeSummary?: string) {
  return requestJson<ProcessSummary>(`/api/v1/admin/processes/${processId}/graph`, {
    method: 'PUT', body: JSON.stringify({ graph, change_summary: changeSummary }),
  });
}

export function submitProcess(processId: string) {
  return requestJson<ProcessSummary>(`/api/v1/admin/processes/${processId}/submit`, { method: 'POST' });
}

export function publishProcess(processId: string) {
  return requestJson<ProcessSummary>(`/api/v1/admin/processes/${processId}/publish`, { method: 'POST' });
}

export function reviewProcess(processId: string, approved: boolean) {
  return requestJson<ProcessSummary>(`/api/v1/admin/processes/${processId}/review?approved=${approved}`, { method: 'POST' });
}
