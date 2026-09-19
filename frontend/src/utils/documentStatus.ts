/** 文件说明：集中维护制度业务状态的中文文案与对应的轻量视觉样式。 */

/**
 * 制度状态英文存储码到中文业务名称的映射。
 * 取值与后端 backend/knowledge/catalog.py 的 STATUS_DISPLAY_NAMES 保持一致，
 * 确保制度库、首页与制度治理页显示同一套文案。
 */
export const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  effective: '现行有效',
  repealed: '已废止',
  expired: '已失效',
  draft: '草案',
  unknown: '状态待确认',
};

/** 把制度状态转换为中文；后端已返回中文时原样透传。 */
export function documentStatusLabel(status: string | null | undefined): string {
  if (!status) return '-';
  return DOCUMENT_STATUS_LABELS[status] ?? status;
}

export function documentStatusClass(status: string): string {
  if (status === '现行有效') return 'document-status-current';
  if (status.includes('试行')) return 'document-status-trial';
  if (status.includes('废止') || status.includes('失效')) return 'document-status-retired';
  return 'document-status-default';
}
