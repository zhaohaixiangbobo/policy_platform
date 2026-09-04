/**
 * 文件说明：使用AntV X6实现真实流程草稿编辑、修订保存、送审和管理员发布入口。
 */
import { ApartmentOutlined, CheckCircleOutlined, PlusOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons';
import { Graph } from '@antv/x6';
import { Button, Card, Empty, Form, Input, List, Modal, Select, Space, Tag, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { bindProcessEvidence, createProcess, deleteProcessEvidence, listProcessEvidence, listProcesses, publishProcess, reviewProcess, saveProcessGraph, submitProcess } from '../../api/admin';
import type { EvidenceReference, ProcessSummary } from '../../api/admin';
import { EvidenceBindingModal } from '../../components/EvidenceBindingModal';
import { UiIcon } from '../../components/UiIcon';

const statusLabels = { DRAFT: '草稿', PENDING_REVIEW: '待审核', APPROVED: '已审核', PUBLISHED: '已发布' };

export function ProcessDesignerPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [current, setCurrent] = useState<ProcessSummary | null>(null);
  const [selectedCell, setSelectedCell] = useState<{ id: string; label: string; kind: 'NODE' | 'EDGE' } | null>(null);
  const [evidence, setEvidence] = useState<EvidenceReference[]>([]);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ name: string; description?: string }>();

  const refresh = async (preferredId?: string) => {
    try {
      const result = await listProcesses();
      setProcesses(result);
      setCurrent(result.find((item) => item.id === (preferredId ?? current?.id)) ?? result[0] ?? null);
    } catch (error) { message.error(error instanceof Error ? error.message : '流程加载失败'); }
  };
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!current) { setEvidence([]); return; }
    void listProcessEvidence(current.id).then(setEvidence).catch((error) => message.error(error.message));
  }, [current?.id, current?.revision_id]);

  useEffect(() => {
    if (!containerRef.current) return;
    graphRef.current?.dispose();
    const graph = new Graph({
      container: containerRef.current,
      background: { color: '#fbfcfe' },
      grid: { visible: true, type: 'dot', args: { color: '#dfe6f2', thickness: 1 } },
      panning: true,
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'], minScale: 0.5, maxScale: 1.8 },
      connecting: { router: 'orth', connector: 'rounded', allowBlank: false, snap: true },
      interacting: current?.status === 'DRAFT',
    });
    const graphData = current?.graph;
    if (graphData && Array.isArray(graphData.nodes) && graphData.nodes.length) {
      graph.fromJSON(graphData as Parameters<Graph['fromJSON']>[0]);
    }
    graph.on('node:click', ({ node }) => setSelectedCell({ id: node.id, label: String(node.attr('label/text') ?? ''), kind: 'NODE' }));
    graph.on('edge:click', ({ edge }) => setSelectedCell({ id: edge.id, label: String(edge.attr('label/text') ?? '流程连线'), kind: 'EDGE' }));
    graphRef.current = graph;
    return () => graph.dispose();
  }, [current?.revision_id]);

  const addNode = (kind: 'start' | 'task' | 'decision' | 'end') => {
    const graph = graphRef.current;
    if (!graph || current?.status !== 'DRAFT') return;
    const labels = { start: '开始', task: '处理节点', decision: '审核判断', end: '结束' };
    const isDecision = kind === 'decision';
    graph.addNode({
      x: 100 + graph.getNodes().length * 24, y: 70 + graph.getNodes().length * 76,
      width: isDecision ? 110 : 150, height: isDecision ? 70 : 44,
      shape: isDecision ? 'polygon' : 'rect',
      attrs: {
        body: { fill: kind === 'start' || kind === 'end' ? '#edf9f1' : isDecision ? '#fff4e8' : '#edf3ff', stroke: kind === 'start' || kind === 'end' ? '#59b77a' : isDecision ? '#e6a64b' : '#6d9ef8', rx: 6, ry: 6, refPoints: isDecision ? '0,10 10,0 20,10 10,20' : undefined },
        label: { text: labels[kind], fill: '#24324a', fontSize: 13 },
      },
      ports: { groups: { top: { position: 'top', attrs: { circle: { r: 4, magnet: true, stroke: '#5f7da8', fill: '#fff' } } }, bottom: { position: 'bottom', attrs: { circle: { r: 4, magnet: true, stroke: '#5f7da8', fill: '#fff' } } } }, items: [{ id: 'in', group: 'top' }, { id: 'out', group: 'bottom' }] },
    });
  };

  const save = async () => {
    if (!current || !graphRef.current) return;
    try { const updated = await saveProcessGraph(current.id, graphRef.current.toJSON(), '流程图编辑'); message.success('草稿修订已保存'); await refresh(updated.id); }
    catch (error) { message.error(error instanceof Error ? error.message : '保存失败'); }
  };

  const selectedEvidence = evidence.filter((item) => item.owner_id.endsWith(`:${selectedCell?.id ?? ''}`));

  const create = async () => {
    try { const values = await form.validateFields(); const result = await createProcess(values.name, values.description); setCreateOpen(false); form.resetFields(); await refresh(result.id); }
    catch (error) { if (error instanceof Error) message.error(error.message); }
  };

  return (
    <div className="admin-page process-page">
      <div className="admin-page-title"><div><Typography.Title level={2}>流程管理</Typography.Title><Typography.Text type="secondary">人工维护节点、连线、条件和制度证据；发布历史修订保持只读</Typography.Text></div><Space><Button icon={<UiIcon icon={PlusOutlined} />} onClick={() => setCreateOpen(true)}>新建流程</Button>{current && <Select value={current.id} onChange={(id) => setCurrent(processes.find((item) => item.id === id) ?? null)} options={processes.map((item) => ({ value: item.id, label: item.name }))} style={{ width: 220 }} />}</Space></div>
      {!current ? <Card bordered={false}><Empty image={<UiIcon icon={ApartmentOutlined} />} description="尚无流程，创建后开始绘制第一份流程草稿"><Button type="primary" onClick={() => setCreateOpen(true)}>创建流程</Button></Empty></Card> : (
        <Card className="process-designer-card" bordered={false} title={<Space><strong>{current.name}</strong><Tag color={current.status === 'PUBLISHED' ? 'green' : current.status === 'APPROVED' ? 'blue' : 'orange'}>{statusLabels[current.status]}</Tag><Typography.Text type="secondary">修订 v{current.revision_no}</Typography.Text></Space>} extra={<Space><Button icon={<UiIcon icon={SaveOutlined} />} disabled={current.status !== 'DRAFT'} onClick={() => void save()}>保存草稿</Button><Button icon={<UiIcon icon={SendOutlined} />} disabled={current.status !== 'DRAFT'} onClick={() => void submitProcess(current.id).then((item) => refresh(item.id)).catch((error) => message.error(error.message))}>提交审核</Button>{current.status === 'PENDING_REVIEW' && <><Button onClick={() => void reviewProcess(current.id, true).then((item) => refresh(item.id)).catch((error) => message.error(error.message))}>审核通过</Button><Button danger onClick={() => void reviewProcess(current.id, false).then((item) => refresh(item.id)).catch((error) => message.error(error.message))}>退回草稿</Button></>}<Button type="primary" icon={<UiIcon icon={CheckCircleOutlined} />} disabled={current.status !== 'APPROVED'} onClick={() => void publishProcess(current.id).then((item) => refresh(item.id)).catch((error) => message.error(error.message))}>发布</Button></Space>}>
          <div className="process-workbench">
            <aside className="process-toolbar"><Typography.Text strong>流程组件</Typography.Text><Button onClick={() => addNode('start')}>开始</Button><Button onClick={() => addNode('task')}>处理节点</Button><Button onClick={() => addNode('decision')}>判断节点</Button><Button onClick={() => addNode('end')}>结束</Button><Typography.Text type="secondary">从节点端口拖动可创建连线。按 Ctrl + 滚轮缩放。</Typography.Text></aside>
            <div className="process-canvas" ref={containerRef} />
            <aside className="process-properties"><Typography.Title level={5}>{selectedCell?.kind === 'EDGE' ? '连线属性' : '节点属性'}</Typography.Title>{selectedCell ? <><Typography.Text type="secondary">对象 ID</Typography.Text><Input value={selectedCell.id} readOnly /><Typography.Text type="secondary">对象名称</Typography.Text><Input value={selectedCell.label} onChange={(event) => { const label = event.target.value; setSelectedCell({ ...selectedCell, label }); graphRef.current?.getCellById(selectedCell.id)?.attr('label/text', label); }} disabled={current.status !== 'DRAFT'} /><Typography.Text type="secondary">制度证据</Typography.Text><List size="small" dataSource={selectedEvidence} locale={{ emptyText: '尚未绑定证据' }} renderItem={(item) => <List.Item actions={current.status === 'DRAFT' ? [<Button key="delete" danger type="link" onClick={() => void deleteProcessEvidence(current.id, item.id).then(() => listProcessEvidence(current.id).then(setEvidence))}>删除</Button>] : undefined}><div><Tag color={item.validation_status === 'VALID' ? 'green' : 'red'}>{item.validation_status}</Tag><Typography.Text ellipsis>{item.quote_snapshot}</Typography.Text><small>Document {item.document_id} / Node {item.primary_node_id} / 第{item.page_start ?? '-'}页</small></div></List.Item>} /><Button block disabled={current.status !== 'DRAFT'} onClick={() => setEvidenceOpen(true)}>绑定制度证据</Button></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择一个节点或连线" />}</aside>
          </div>
        </Card>
      )}
      <Modal title="新建流程草稿" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => void create()} okText="创建"><Form form={form} layout="vertical"><Form.Item label="流程名称" name="name" rules={[{ required: true, message: '请输入流程名称' }]}><Input /></Form.Item><Form.Item label="流程说明" name="description"><Input.TextArea rows={3} /></Form.Item></Form></Modal>
      <EvidenceBindingModal open={evidenceOpen} ownerKind={selectedCell?.kind ?? 'NODE'} cellId={selectedCell?.id ?? ''} onCancel={() => setEvidenceOpen(false)} onSubmit={async (payload) => { if (!current) return; await bindProcessEvidence(current.id, payload); setEvidence(await listProcessEvidence(current.id)); setEvidenceOpen(false); message.success('流程证据已绑定'); }} />
    </div>
  );
}
