/** 文件说明：兼容历史PDF入口，并将受控PDF交由浏览器原生查看器在新窗口打开。 */
import { Button, Empty, Space, Spin, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { getDocument } from '../api/documents';
import type { DocumentDetail } from '../types/documents';
import { documentPdfUrl } from '../utils/pdf';

export function PdfEntryPage() {
  const navigate = useNavigate();
  const { documentId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const requestedPage = Number(searchParams.get('page') ?? '1');
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const pdfUrl = documentPdfUrl(documentId, page);

  useEffect(() => {
    getDocument(documentId)
      .then(setDocument)
      .catch((error: unknown) => message.error(error instanceof Error ? error.message : '制度信息加载失败'))
      .finally(() => setLoading(false));
  }, [documentId]);

  if (loading) return <Spin />;
  return (
    <div className="page-stack">
      <Space wrap>
        <Button onClick={() => navigate(`/documents/${documentId}`)}>返回制度详情</Button>
        <Typography.Title level={3} className="page-heading">{document?.title ?? '制度PDF'}</Typography.Title>
      </Space>
      <Typography.Text type="secondary">{document?.document_code ?? '无文号'} · 目标第 {page} 页</Typography.Text>
      {document?.has_pdf ? (
        <div className="pdf-launcher">
          <Typography.Title level={4}>使用浏览器查看PDF</Typography.Title>
          <Typography.Paragraph type="secondary">
            PDF不会嵌入平台页面。点击下方按钮后，将由浏览器原生PDF查看器打开并定位到第 {page} 页。
          </Typography.Paragraph>
          <Button type="primary" size="large" href={pdfUrl} target="_blank" rel="noreferrer">
            在新窗口打开PDF
          </Button>
        </div>
      ) : <Empty description="当前制度尚未配置可访问PDF" />}
    </div>
  );
}
