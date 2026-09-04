/** 文件说明：集中维护制度业务状态对应的轻量视觉样式。 */
export function documentStatusClass(status: string): string {
  if (status === '现行有效') return 'document-status-current';
  if (status.includes('试行')) return 'document-status-trial';
  if (status.includes('废止') || status.includes('失效')) return 'document-status-retired';
  return 'document-status-default';
}
