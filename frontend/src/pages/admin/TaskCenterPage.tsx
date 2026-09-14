/**
 * 文件说明：实现基于真实入库任务数据的统计、筛选、列表和DOCX上传入口。
 */
import { CheckCircleOutlined, ClockCircleOutlined, CloudUploadOutlined, ExclamationCircleOutlined, FileAddOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Descriptions, Drawer, Empty, Form, Input, List, Modal, Select, Space, Table, Tag, Timeline, Typography, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { completeBatch, createBatch, getJobDetail, listJobs, uploadBatchJob, uploadJob } from '../../api/admin';
import type { IngestionJob, JobDetail, JobListResponse } from '../../api/admin';
import { UiIcon } from '../../components/UiIcon';

const stateLabels: Record<string, string> = {
  UPLOADED: '待处理', PREFLIGHTING: '预检中', PARSE_QUEUED: '待解析', PARSING: '解析中', PARSE_REVIEW: '解析待审核',
  METADATA_REVIEW: '元数据待确认', CHUNK_QUEUED: '待分块', CHUNKING: '分块中', CHUNK_REVIEW: '分块待审核', READY_FOR_INDEX: '可纳入索引', INDEX_QUEUED: '待索引', INDEXING: '索引中',
  READY_TO_PUBLISH: '索引已构建，待确认发布', PUBLISH_QUEUED: '等待Alias切换', PUBLISHING: 'Alias切换中', PUBLISHED: '处理完成', FAILED: '处理失败', REJECTED: '已驳回', CANCELLED: '已取消',
};

const stateColor = (state: string) => state === 'PUBLISHED' ? 'success' : state === 'FAILED' || state === 'REJECTED' ? 'error' : state.includes('REVIEW') || state === 'READY_TO_PUBLISH' ? 'warning' : 'processing';

export function TaskCenterPage() {
  const [data, setData] = useState<JobListResponse>({ items: [], total: 0, page: 1, page_size: 10, counts: {} });
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState<string>();
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [form] = Form.useForm<{ taskName?: string; initialDocumentStatus: 'effective' | 'repealed' | 'expired' }>();
  const [uploading, setUploading] = useState(false);
  const navigate = useNavigate();

  const refresh = async () => {
    setLoading(true);
    try { setData(await listJobs(state, page)); } catch (error) { message.error(error instanceof Error ? error.message : '任务加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void listJobs(state, page).then(setData).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [state, page]);

  const allTaskCount = useMemo(
    () => Object.values(data.counts).reduce((sum, count) => sum + count, 0),
    [data.counts],
  );
  const stats = useMemo(() => [
    { title: '全部任务', value: allTaskCount, icon: InboxOutlined, tone: 'blue' },
    { title: '待处理', value: (data.counts.UPLOADED ?? 0) + (data.counts.PARSE_QUEUED ?? 0) + (data.counts.CHUNK_QUEUED ?? 0), icon: ClockCircleOutlined, tone: 'orange' },
    { title: '处理中', value: ['PREFLIGHTING', 'PARSING', 'CHUNKING', 'INDEXING', 'PUBLISHING'].reduce((sum, key) => sum + (data.counts[key] ?? 0), 0), icon: CloudUploadOutlined, tone: 'blue' },
    { title: '待审核/发布', value: ['PARSE_REVIEW', 'METADATA_REVIEW', 'CHUNK_REVIEW', 'READY_FOR_INDEX', 'READY_TO_PUBLISH'].reduce((sum, key) => sum + (data.counts[key] ?? 0), 0), icon: ExclamationCircleOutlined, tone: 'orange' },
    { title: '已完成', value: data.counts.PUBLISHED ?? 0, icon: CheckCircleOutlined, tone: 'green' },
    { title: '已驳回/失败', value: (data.counts.REJECTED ?? 0) + (data.counts.FAILED ?? 0), icon: ExclamationCircleOutlined, tone: 'red' },
  ], [allTaskCount, data.counts]);

  const submitUpload = async () => {
    const rawFiles = files.flatMap((item) => item.originFileObj ? [item.originFileObj] : []);
    if (!rawFiles.length) { message.warning('请选择DOCX制度文件'); return; }
    try {
      setUploading(true);
      const values = await form.validateFields();
      if (rawFiles.length === 1) {
        await uploadJob(rawFiles[0], values.taskName, values.initialDocumentStatus);
      } else {
        const batch = await createBatch(values.taskName || `批量入库 ${new Date().toLocaleString('zh-CN')}`);
        for (let index = 0; index < rawFiles.length; index += 1) {
          message.loading({ content: `正在上传第 ${index + 1}/${rawFiles.length} 个文件`, key: 'batch-upload', duration: 0 });
          await uploadBatchJob(batch.id, rawFiles[index], values.initialDocumentStatus);
        }
        await completeBatch(batch.id);
        message.destroy('batch-upload');
      }
      message.success(`已创建 ${rawFiles.length} 个独立入库任务`);
      setModalOpen(false); setFiles([]); form.resetFields(); setPage(1);
      if (page === 1) await refresh();
    } catch (error) { message.destroy('batch-upload'); if (error instanceof Error) message.error(error.message); }
    finally { setUploading(false); }
  };

  const columns = [
    { title: '任务ID', dataIndex: 'id', width: 150, render: (value: string) => <Typography.Text copyable={{ text: value }}>{value.slice(0, 8)}</Typography.Text> },
    { title: '任务名称', dataIndex: 'task_name', ellipsis: true },
    { title: '处理阶段', dataIndex: 'state', width: 190, render: (value: string) => <Tag color={stateColor(value)}>{stateLabels[value] ?? value}</Tag> },
    { title: '尝试', dataIndex: 'attempt_no', width: 72 },
    { title: '进度', dataIndex: 'stage_progress', width: 82, render: (value: number) => `${value}%` },
    { title: '创建时间', dataIndex: 'created_at', width: 180, render: (value: string) => new Date(value).toLocaleString('zh-CN') },
    { title: '操作', key: 'actions', width: 210, render: (_: unknown, job: IngestionJob) => <Space><Button type="link" onClick={() => void getJobDetail(job.id).then(setDetail).catch((error) => message.error(error.message))}>详情</Button>{['INDEX_QUEUED', 'INDEXING'].includes(job.state) && <Typography.Text type="secondary">Worker自动处理</Typography.Text>}{['METADATA_REVIEW', 'READY_FOR_INDEX', 'READY_TO_PUBLISH'].includes(job.state) && <Button type="link" onClick={() => navigate('/admin/knowledge')}>制度治理</Button>}</Space> },
  ];

  return (
    <div className="admin-page task-center-page">
      <div className="admin-page-title"><div><Typography.Title level={2}>任务中心</Typography.Title><Typography.Text type="secondary">统一跟踪制度上传、解析、分块、索引和发布状态</Typography.Text></div><Space><Button icon={<UiIcon icon={ReloadOutlined} />} onClick={() => void refresh()}>刷新</Button><Button type="primary" icon={<UiIcon icon={FileAddOutlined} />} onClick={() => setModalOpen(true)}>新建入库任务</Button></Space></div>
      <div className="task-stats">{stats.map((item) => <Card className={`task-stat task-stat-${item.tone}`} key={item.title}><div><small>{item.title}</small><strong>{item.value}</strong></div><span><UiIcon icon={item.icon} /></span></Card>)}</div>
      <Card className="admin-table-card" variant="borderless">
        <div className="admin-filter-bar"><Select allowClear placeholder="全部状态" value={state} onChange={(value) => { setState(value); setPage(1); }} options={Object.entries(stateLabels).map(([value, label]) => ({ value, label }))} style={{ width: 180 }} /><Typography.Text type="secondary">共 {data.total} 条任务</Typography.Text></div>
        <Table<IngestionJob>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={data.items}
          pagination={{
            current: data.page,
            pageSize: 10,
            total: data.total,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条`,
            onChange: setPage,
          }}
          locale={{ emptyText: <Empty description="尚无入库任务，请上传第一份DOCX制度" /> }}
        />
      </Card>
      <Modal title="新建制度入库任务" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => void submitUpload()} okText="创建任务" confirmLoading={uploading}>
        <Form form={form} layout="vertical" initialValues={{ initialDocumentStatus: 'effective' }}><Form.Item label="任务/批次名称" name="taskName"><Input placeholder="不填写时使用文件名或当前时间" /></Form.Item><Form.Item label="制度状态（上传声明值）" name="initialDocumentStatus" tooltip="只表示上传时的初始声明，仍需在元数据审核中确认。"><Select options={[{ value: 'effective', label: '现行有效（默认）' }, { value: 'repealed', label: '已废止' }, { value: 'expired', label: '已失效' }]} /></Form.Item></Form>
        <Upload.Dragger accept=".docx" multiple maxCount={20} fileList={files} beforeUpload={() => false} onChange={({ fileList }) => setFiles(fileList)}><p className="ant-upload-drag-icon"><UiIcon icon={CloudUploadOutlined} /></p><p>拖拽或点击选择1至20个DOCX文件</p><p className="ant-upload-hint">浏览器按顺序上传；每个文件创建独立任务、独立审核结果，单Worker串行处理</p></Upload.Dragger>
      </Modal>
      <Drawer width={620} title="入库任务闭环详情" open={Boolean(detail)} onClose={() => setDetail(null)}>
        {detail && <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Descriptions column={2} bordered size="small" items={[
            { key: 'state', label: '状态', children: <Tag color={stateColor(detail.job.state)}>{stateLabels[detail.job.state] ?? detail.job.state}</Tag> },
            { key: 'progress', label: '进度', children: `${detail.job.stage_progress}%` },
            { key: 'document', label: 'Document', children: detail.job.document_id ?? '-' },
            { key: 'initial-status', label: '上传声明值', children: ({ effective: '现行有效', repealed: '已废止', expired: '已失效' } as Record<string, string>)[detail.job.initial_document_status] ?? detail.job.initial_document_status },
            { key: 'parse', label: 'ParseRun', children: detail.job.parse_run_id ?? '-' },
            { key: 'chunk', label: 'ChunkRun', children: detail.job.chunk_run_id ?? '-' },
            { key: 'index', label: 'IndexRun', children: detail.job.index_run_id ?? '-' },
          ]} />
          <Card size="small" title="状态事件"><Timeline items={detail.events.map((item) => ({ children: <div><strong>{item.from_state ?? '开始'} → {item.to_state}</strong><p>{item.reason}</p><small>{item.run_type ? `${item.run_type} ${item.run_id}` : ''} · {new Date(item.created_at).toLocaleString('zh-CN')}</small></div> }))} /></Card>
          <Card size="small" title="审核记录"><List dataSource={detail.reviews} locale={{ emptyText: '暂无审核记录' }} renderItem={(item) => <List.Item><div><Tag color={item.outcome === 'REJECT' ? 'red' : 'green'}>{item.outcome}</Tag><strong>{item.target_type} {item.target_id}</strong><p>{item.comment}</p></div></List.Item>} /></Card>
          <Card size="small" title="受控产物"><List dataSource={detail.artifacts} renderItem={(item) => <List.Item><div><Tag>{item.artifact_type}</Tag><Typography.Text copyable>{item.relative_path}</Typography.Text></div></List.Item>} /></Card>
        </Space>}
      </Drawer>
    </div>
  );
}
