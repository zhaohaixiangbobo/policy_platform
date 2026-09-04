/** 文件说明：定义active制度目录的前端公开类型。 */
export interface DocumentSummary {
  id: number;
  title: string;
  document_code: string | null;
  issuer: string | null;
  responsibility_department: string | null;
  status: string;
  publish_date: string | null;
  effective_date: string | null;
  active_parse_run_id: number;
  has_pdf: boolean;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface DocumentFacetsResponse {
  statuses: string[];
  issuers: string[];
  departments: string[];
}

export type DocumentDetail = DocumentSummary;

export interface DocumentTableCell {
  row: number;
  column: number;
  text: string;
  grid_span: number;
  vertical_merge: 'restart' | 'continue' | null;
}

export interface DocumentTableStructure {
  rows: DocumentTableCell[][];
  row_count: number;
  cell_count: number;
}

export interface DocumentNode {
  id: number;
  document_id: number;
  parse_run_id: number;
  parent_id: number | null;
  node_type: string;
  node_number: string | null;
  title: string | null;
  text: string;
  path_text: string | null;
  order_no: number;
  page_start: number | null;
  page_end: number | null;
  table_structure: DocumentTableStructure | null;
}

export interface DocumentNodeListResponse {
  document_id: number;
  active_parse_run_id: number;
  items: DocumentNode[];
}
