/** 文件说明：展示单次问答的公开响应诊断快照，不呈现受控debug字段。 */
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Tag, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { getDiagnostic } from '../api/chat';
import { EvidencePanel } from '../components/EvidencePanel';
import type { DiagnosticDetail } from '../types/chat';

export function DiagnosticDetailPage() {
  const navigate = useNavigate();
  const { requestId = '' } = useParams();
  const [detail, setDetail] = useState<DiagnosticDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDiagnostic(requestId)
      .then(setDetail)
      .catch((error: unknown) => message.error(error instanceof Error ? error.message : '诊断详情加载失败'))
      .finally(() => setLoading(false));
  }, [requestId]);

  if (loading) return <Spin />;
  if (!detail) return <Empty description="诊断快照不存在或功能未启用" />;

  return (
    <div className="page-stack">
      <Space wrap>
        <Button onClick={() => navigate('/diagnostics/requests')}>返回诊断列表</Button>
        <Tag>{detail.diagnostic_scope}</Tag>
      </Space>
      <Alert type="info" showIcon message="本页仅来自Platform保存的rag_api_v1_1公开响应快照" />
      <Card title="问题"><Typography.Paragraph>{detail.question.content}</Typography.Paragraph></Card>
      <Card title="回答" extra={<Tag>{detail.answer.answer_status}</Tag>}>
        <Typography.Paragraph>{detail.answer.content}</Typography.Paragraph>
        <EvidencePanel citations={detail.answer.citations} />
      </Card>
      <Card title="公开来源与配置摘要">
        <Descriptions column={{ xs: 1, lg: 2 }}>
          <Descriptions.Item label="RAG版本">{detail.rag_version ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="生成模型">{detail.generator_model ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="生成修订">{detail.generator_revision ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="Prompt版本">{detail.prompt_version ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="Prompt Schema">{detail.prompt_schema_version ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="index_run_id">{detail.answer.index_run_id ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="质量门禁版本">{detail.answer.quality_gate?.version ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="总耗时快照">{detail.latency_total_ms == null ? '-' : `${detail.latency_total_ms} ms`}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
