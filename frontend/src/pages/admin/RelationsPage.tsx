/**
 * 文件说明：实现制度关系草稿、证据绑定、人工送审和ECharts只读关系图。
 */
import { LinkOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons';
import * as echarts from 'echarts/core';
import { GraphChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { Button, Card, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import { bindRelationEvidence, createRelation, getEvidenceCatalog, listRelationEvidence, listRelations, reviewRelation, submitRelation } from '../../api/admin';
import type { EvidenceCatalogDocument, RelationSummary } from '../../api/admin';
import { EvidenceBindingModal } from '../../components/EvidenceBindingModal';
import { UiIcon } from '../../components/UiIcon';

const labels: Record<string, string> = { CITES: '引用', SUPERSEDES: '替代', REPEALS: '废止', RELATED_TOPIC: '同主题', CONFLICTS_WITH: '冲突' };

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

export function RelationsPage() {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const [items, setItems] = useState<RelationSummary[]>([]);
  const [documents, setDocuments] = useState<EvidenceCatalogDocument[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [evidenceTarget, setEvidenceTarget] = useState<string | null>(null);
  const [evidenceCounts, setEvidenceCounts] = useState<Record<string, number>>({});
  const [form] = Form.useForm();
  const documentMap = useMemo(() => new Map(documents.map((item) => [item.id, item])), [documents]);

  const refresh = async () => {
    try {
      const [relations, catalog] = await Promise.all([listRelations(), getEvidenceCatalog()]);
      setItems(relations); setDocuments(catalog);
      const counts = await Promise.all(relations.map(async (item) => [item.id, (await listRelationEvidence(item.id)).length] as const));
      setEvidenceCounts(Object.fromEntries(counts));
    } catch (error) { message.error(error instanceof Error ? error.message : '制度关系加载失败'); }
  };
  useEffect(() => { void refresh(); }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const confirmed = items.filter((item) => item.status === 'CONFIRMED');
    const ids = Array.from(new Set(confirmed.flatMap((item) => [item.source_document_id, item.target_document_id])));
    chart.setOption({
      tooltip: {},
      series: [{ type: 'graph', layout: 'force', roam: true, label: { show: true }, force: { repulsion: 180 },
        data: ids.map((id) => ({ id: String(id), name: documentMap.get(id)?.title ?? `制度 ${id}`, symbolSize: 56 })),
        links: confirmed.map((item) => ({ source: String(item.source_document_id), target: String(item.target_document_id), value: labels[item.relation_type], label: { show: true, formatter: labels[item.relation_type] } })),
      }],
    });
    const resize = () => chart.resize(); window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.dispose(); };
  }, [items, documentMap]);

  const create = async () => {
    try {
      const values = await form.validateFields();
      const source = documentMap.get(values.source_document_id); const target = documentMap.get(values.target_document_id);
      if (!source || !target) return;
      await createRelation({ ...values, source_parse_run_id: source.active_parse_run_id, target_parse_run_id: target.active_parse_run_id, valid_from: null, valid_to: null });
      setCreateOpen(false); form.resetFields(); await refresh();
    } catch (error) { if (error instanceof Error) message.error(error.message); }
  };

  const columns = [
    { title: '关系', dataIndex: 'relation_type', render: (value: string) => <Tag color="blue">{labels[value] ?? value}</Tag> },
    { title: '源制度', dataIndex: 'source_document_id', render: (id: number) => documentMap.get(id)?.title ?? `制度 ${id}` },
    { title: '目标制度', dataIndex: 'target_document_id', render: (id: number) => documentMap.get(id)?.title ?? `制度 ${id}` },
    { title: '证据', key: 'evidence', render: (_: unknown, item: RelationSummary) => `${evidenceCounts[item.id] ?? 0} 条` },
    { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'CONFIRMED' ? 'green' : value === 'REJECTED' ? 'red' : 'orange'}>{value}</Tag> },
    { title: '操作', key: 'actions', render: (_: unknown, item: RelationSummary) => <Space><Button type="link" onClick={() => setEvidenceTarget(item.id)} disabled={!['DRAFT', 'NEEDS_REVIEW'].includes(item.status)}>绑定证据</Button><Button type="link" icon={<UiIcon icon={SendOutlined} />} disabled={!['DRAFT', 'NEEDS_REVIEW'].includes(item.status) || !evidenceCounts[item.id]} onClick={() => void submitRelation(item.id).then(refresh).catch((error) => message.error(error.message))}>送审</Button>{item.status === 'PENDING_REVIEW' && <><Button type="link" onClick={() => void reviewRelation(item.id, true).then(refresh)}>确认</Button><Button danger type="link" onClick={() => void reviewRelation(item.id, false, '审核驳回').then(refresh)}>驳回</Button></>}</Space> },
  ];

  return <div className="admin-page relation-page">
    <div className="admin-page-title"><div><Typography.Title level={2}>制度关系</Typography.Title><Typography.Text type="secondary">引用、替代、废止、同主题和冲突关系均由人工创建并绑定证据</Typography.Text></div><Button type="primary" icon={<UiIcon icon={PlusOutlined} />} disabled={documents.length < 2} onClick={() => setCreateOpen(true)}>新建关系</Button></div>
    <Card bordered={false} title="已确认关系图"><div ref={chartRef} className="relation-chart">{items.some((item) => item.status === 'CONFIRMED') ? null : <Empty description="暂无已确认制度关系" />}</div></Card>
    <Card bordered={false}><Table rowKey="id" columns={columns} dataSource={items} locale={{ emptyText: <Empty image={<UiIcon icon={LinkOutlined} />} description={documents.length < 2 ? '至少发布两份制度后可创建关系' : '尚无制度关系'} /> }} /></Card>
    <Modal title="新建制度关系" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => void create()} okText="创建草稿"><Form form={form} layout="vertical"><Form.Item label="关系类型" name="relation_type" rules={[{ required: true }]}><Select options={Object.entries(labels).map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item label="源制度" name="source_document_id" rules={[{ required: true }]}><Select options={documents.map((item) => ({ value: item.id, label: item.title }))} /></Form.Item><Form.Item label="目标制度" name="target_document_id" rules={[{ required: true }]}><Select options={documents.map((item) => ({ value: item.id, label: item.title }))} /></Form.Item><Form.Item label="关系说明" name="rationale"><Input.TextArea rows={3} /></Form.Item></Form></Modal>
    <EvidenceBindingModal open={Boolean(evidenceTarget)} ownerKind="RELATION" cellId={evidenceTarget ?? ''} onCancel={() => setEvidenceTarget(null)} onSubmit={async (payload) => { if (!evidenceTarget) return; await bindRelationEvidence(evidenceTarget, payload); message.success('制度关系证据已绑定'); setEvidenceTarget(null); await refresh(); }} />
  </div>;
}
