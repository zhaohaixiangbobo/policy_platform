/**
 * 文件说明：集中生成受控PDF公开地址，统一使用浏览器原生查看器的页码片段。
 */
export function documentPdfUrl(documentId: string | number, requestedPage?: number | null): string {
  const page = Number.isInteger(requestedPage) && Number(requestedPage) > 0
    ? Number(requestedPage)
    : 1;
  return `/api/v1/documents/${encodeURIComponent(String(documentId))}/pdf#page=${page}`;
}
