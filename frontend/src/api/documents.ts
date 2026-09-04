/** 文件说明：封装M2制度浏览Platform API。 */
import { requestJson } from './httpClient';
import type {
  DocumentDetail,
  DocumentFacetsResponse,
  DocumentListResponse,
  DocumentNodeListResponse,
} from '../types/documents';

export interface DocumentFilters {
  keyword?: string;
  status?: string;
  issuer?: string;
  department?: string;
  publish_date_from?: string;
  publish_date_to?: string;
  sort_by?:
    | 'updated_at'
    | 'title'
    | 'document_code'
    | 'issuer'
    | 'publish_date'
    | 'effective_date'
    | 'status'
    | 'responsibility_department';
  sort_order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

export function listDocuments(filters: DocumentFilters = {}): Promise<DocumentListResponse> {
  const params = new URLSearchParams({
    page: String(filters.page ?? 1),
    page_size: String(filters.page_size ?? 20),
    sort_by: filters.sort_by ?? 'updated_at',
    sort_order: filters.sort_order ?? 'desc',
  });
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '' && key !== 'page' && key !== 'page_size') {
      params.set(key, String(value));
    }
  });
  return requestJson(`/api/v1/documents?${params.toString()}`);
}

export function getDocumentFacets(): Promise<DocumentFacetsResponse> {
  return requestJson('/api/v1/documents/facets');
}

export function getDocument(documentId: string): Promise<DocumentDetail> {
  return requestJson(`/api/v1/documents/${encodeURIComponent(documentId)}`);
}

export function getDocumentNodes(documentId: string): Promise<DocumentNodeListResponse> {
  return requestJson(`/api/v1/documents/${encodeURIComponent(documentId)}/nodes`);
}
