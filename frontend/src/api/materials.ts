/** 文件说明：配套资料v2契约（图片三字段、案例十列）；与制度检索、学习和模型生成接口隔离。 */
import { requestJson } from './httpClient';

export interface CaseFields {
  title: string; person_category: string; position: string; rank: string; political_status: string; age: string;
  domains: string[]; problem_types: string[]; outcome: string; original: string;
  tags?: never; summary?: never;
}
export interface ImageFields {
  title: string; tags: string[]; summary: string;
  domains?: never; problem_types?: never; outcome?: never; original?: never;
  person_category?: never; position?: never; rank?: never; political_status?: never; age?: never;
}
export type MaterialFields = CaseFields | ImageFields;
export const emptyImageFields: ImageFields = { title: '', tags: [], summary: '' };
export const emptyCaseFields: CaseFields = { title: '', person_category: '', position: '', rank: '', political_status: '', age: '', domains: [], problem_types: [], outcome: '', original: '' };
export const materialTags = (item: MaterialItem) => item.kind === 'IMAGE' ? item.fields.tags ?? [] : [...(item.fields.domains ?? []), ...(item.fields.problem_types ?? [])];
export interface MaterialItem {
  id: string; kind: 'CASE' | 'IMAGE'; state: 'DRAFT' | 'PUBLISHED' | 'OFFLINE'; version: number;
  revision_id: string; revision_no: number; revision_state: string; published_revision_id: string | null;
  has_draft: boolean; updated_at: string; published_at: string | null;
  preview_text: string; fields: MaterialFields; file_url: string | null; match_excerpt?: string; match_reason?: string;
  history?: { id: string; revision_no: number; state: string; created_at: string }[];
  provenance?: { filename?: string; sheet?: string; row?: number };
  file?: { filename?: string; width?: number; height?: number; sha256?: string };
}
export interface MaterialsResult {
  items: MaterialItem[]; total: number; page: number; page_size: number;
  counts: Record<string, number>; domains: string[];
}
export interface ImportPreview {
  batch_id: string; total: number; new: number; errors: number; duplicates: number;
  rows: { row: number; fields: MaterialFields | null; error: string | null; duplicate: boolean }[];
}
const root = '/api/v1/materials';
export const listMaterials = (params: Record<string, string>) => {
  const query = new URLSearchParams(params);
  return requestJson<MaterialsResult>(`${root}?${query}`);
};
export const getMaterial = (id: string, revision?: string) => requestJson<MaterialItem>(`${root}/${id}${revision ? `?revision_id=${revision}` : ''}`);
export const saveMaterial = (item: MaterialItem, fields: MaterialFields) => requestJson<MaterialItem>(`${root}/${item.id}`, {
  method: 'PUT', body: JSON.stringify({ expected_version: item.version, fields }),
});
export const materialAction = (action: 'PUBLISH' | 'OFFLINE', items: MaterialItem[]) => requestJson<{ count: number }>(`${root}/actions`, {
  method: 'POST', body: JSON.stringify({ action, items: items.map((i) => ({ id: i.id, expected_version: i.version })) }),
});
export const uploadMaterialImage = (file: File, fields: MaterialFields) => {
  const body = new FormData(); body.append('file', file); body.append('metadata', JSON.stringify(fields));
  return requestJson<MaterialItem>(`${root}/images`, { method: 'POST', body });
};
export const previewCases = (file: File) => {
  const body = new FormData(); body.append('file', file);
  return requestJson<ImportPreview>(`${root}/imports/preview`, { method: 'POST', body });
};
export const confirmCases = (batch: string) => requestJson<{ created: number; skipped: number; ids: string[] }>(`${root}/imports/${batch}/confirm`, { method: 'POST' });
