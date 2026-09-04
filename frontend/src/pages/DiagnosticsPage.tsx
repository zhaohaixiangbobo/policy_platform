/** 文件说明：展示默认关闭、本机限定且只使用公开响应快照的诊断筛选列表。 */
import { Alert, Button, Card, Checkbox, Empty, Form, Input, Select, Space, Table, Tag, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { listDiagnostics } from '../api/chat';
import type { DiagnosticSummary } from '../types/chat';

interface DiagnosticFilters {
  request_id?: string;
  keyword?: string;
  answer_status?: string;
  quality_gate_status?: string;
  has_down_feedback?: boolean;
  date_from?: string;
  date_to?: string;
}

export function DiagnosticsPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm<DiagnosticFilters>();
  const [items, setItems] = useState<DiagnosticSummary[]>([]);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = async (filters: DiagnosticFilters = {}) => {
    setLoading(true);
    try {
      const result = await listDiagnostics(filters);
      setItems(result.items);
      setDisabled(false);
    } catch (error) {
      setDisabled(true);
      message.info(error instanceof Error ? error.message : '诊断功能未启用');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  return (
    <div className="page-stack">
      <Typography.Title level={2} className="page-heading">公开响应诊断</Typography.Title>
      <Alert type={disabled ? 'warning' : 'info'} showIcon message={disabled ? '诊断功能默认关闭' : '仅展示Platform保存的rag_api_v1_1公开响应快照'} description="该页面不读取草稿哈希、Claim绑定、Verifier判定或其他受控debug数据。" />
      {!disabled ? (
        <Card bordered={false}>
          <Form<DiagnosticFilters> form={form} layout="inline" onFinish={(values) => void load(values)}>
            <Form.Item name="request_id"><Input allowClear placeholder="request_id" /></Form.Item>
            <Form.Item name="keyword"><Input allowClear placeholder="问题关键词" /></Form.Item>
            <Form.Item name="answer_status"><Select allowClear placeholder="回答状态" style={{ width: 190 }} options={['ANSWER', 'INSUFFICIENT_EVIDENCE', 'CONFLICT'].map((value) => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="quality_gate_status"><Select allowClear placeholder="质量门禁" style={{ width: 160 }} options={['PASS', 'DOWNGRADED', 'NOT_REQUIRED'].map((value) => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="date_from"><Input type="date" aria-label="开始日期" /></Form.Item>
            <Form.Item name="date_to"><Input type="date" aria-label="结束日期" /></Form.Item>
            <Form.Item name="has_down_feedback" valuePropName="checked"><Checkbox>仅点踩</Checkbox></Form.Item>
            <Form.Item><Space><Button type="primary" htmlType="submit">查询</Button><Button onClick={() => { form.resetFields(); void load(); }}>重置</Button></Space></Form.Item>
          </Form>
        </Card>
      ) : null}
      <Table<DiagnosticSummary>
        rowKey="request_id"
        loading={loading}
        dataSource={items}
        locale={{ emptyText: <Empty description="暂无可展示的诊断快照" /> }}
        onRow={(record) => ({ onClick: () => navigate(`/diagnostics/requests/${encodeURIComponent(record.request_id)}`) })}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 180, render: (value: string) => new Date(value).toLocaleString('zh-CN') },
          { title: '问题', dataIndex: 'question_summary' },
          { title: '状态', dataIndex: 'answer_status', width: 200, render: (value) => <Tag>{value}</Tag> },
          { title: '质量门禁', key: 'quality', width: 230, render: (_, row) => `${row.quality_gate_version ?? '-'} / ${row.quality_gate_status ?? '-'}` },
          { title: 'Citation', dataIndex: 'citation_count', width: 100 },
          { title: 'index_run_id', dataIndex: 'index_run_id', width: 130, render: (value) => value ?? '-' },
          { title: '耗时', dataIndex: 'latency_total_ms', width: 100, render: (value) => value == null ? '-' : `${value} ms` },
          { title: '反馈', dataIndex: 'has_down_feedback', width: 90, render: (value) => value ? <Tag color="red">点踩</Tag> : '-' },
        ]}
      />
    </div>
  );
}
