/**
 * 文件说明：提供正式文件版本、制度系列、元数据修订、废止和索引发布的一体化治理页面。
 */
import { CheckOutlined, EditOutlined, FileSyncOutlined, LinkOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Drawer, Form, Input, List, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  assignPolicySeries, confirmIndexPublication, createIndexPublication, createMetadataDraft,
  getManagedDocument, listIndexPublications, listManagedDocuments, listPolicySeries,
  retryIndexPublication, reviewMetadataRevision, submitMetadataRevision, updateMetadataRevision,
} from '../../api/admin';
import type { IndexPublication, ManagedDocument, ManagedDocumentDetail, MetadataRevision, PolicySeries } from '../../api/admin';
import { UiIcon } from '../../components/UiIcon';

const lifecycleLabels: Record<string, string> = {
  DRAFT: '元数据草稿', PENDING_REVIEW: '元数据待审核', APPROVED: '元数据审核通过（待纳入索引）',
  PUBLISHED: '已在当前快照生效', REJECTED: '元数据已驳回', SUPERSEDED: '历史元数据版本',
};

const publicationLabels: Record<string, string> = {
  DRAFT: '发布草稿', BUILD_QUEUED: '等待 Worker 构建', BUILDING: '索引构建中',
  READY_TO_PUBLISH: '索引已构建，待确认发布', PUBLISH_QUEUED: '等待 Alias 切换',
  PUBLISHING: 'Alias 切换中', PUBLISHED: '已正式发布', FAILED: '发布失败',
};

const fieldLabels: Record<string, string> = {
  title: '制度名称', document_code: '文号', document_type: '文种', issuing_org: '发布机构',
  owner_department: '责任部门', publish_date: '发布日期', effective_date: '生效日期',
  expiry_date: '失效日期', status: '制度状态', version: '文件版本', authority_level: '效力层级',
  confidentiality_level: '密级', addressee_text: '主送对象',
};

export function KnowledgeGovernancePage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<ManagedDocument[]>([]);
  const [series, setSeries] = useState<PolicySeries[]>([]);
  const [publications, setPublications] = useState<IndexPublication[]>([]);
  const [selectedIds, setSelectedIds] = useState<Key[]>([]);
  const [detail, setDetail] = useState<ManagedDocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [metadataStatus, setMetadataStatus] = useState<string>();
  const [sortBy, setSortBy] = useState('ACTION_REQUIRED');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [seriesOpen, setSeriesOpen] = useState(false);
  const [form] = Form.useForm<Partial<MetadataRevision>>();
  const [seriesForm] = Form.useForm<{ series_id?: number; canonical_title?: string }>();

  const refresh = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [documentRows, seriesRows, publicationRows] = await Promise.all([
        listManagedDocuments({ keyword, metadata_status: metadataStatus, sort_by: sortBy, page }), listPolicySeries(), listIndexPublications(),
      ]);
      setDocuments(documentRows.items); setTotal(documentRows.total); setSeries(seriesRows); setPublications(publicationRows);
    } catch (error) { message.error(error instanceof Error ? error.message : '制度治理数据加载失败'); }
    finally { if (!silent) setLoading(false); }
  };
  useEffect(() => { void refresh(); }, [keyword, metadataStatus, sortBy, page]);
  useEffect(() => {
    const active = publications.some((item) => ['BUILD_QUEUED', 'BUILDING', 'PUBLISH_QUEUED', 'PUBLISHING'].includes(item.status));
    const poll = () => { if (document.visibilityState === 'visible') void refresh(true); };
    const timer = window.setInterval(poll, active ? 5000 : 30000);
    document.addEventListener('visibilitychange', poll);
    window.addEventListener('focus', poll);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
      window.removeEventListener('focus', poll);
    };
  }, [publications.map((item) => `${item.id}:${item.status}`).join('|')]);

  const current = detail?.revisions[0] ?? null;
  useEffect(() => { if (current) form.setFieldsValue(current); else form.resetFields(); }, [current?.id]);
  const candidateGroups = useMemo(() => {
    const groups: Record<string, ManagedDocumentDetail['candidates']> = {};
    for (const item of detail?.candidates ?? []) (groups[item.field_name] ??= []).push(item);
    return groups;
  }, [detail]);

  const openDetail = async (documentId: number) => {
    try { setDetail(await getManagedDocument(documentId)); }
    catch (error) { message.error(error instanceof Error ? error.message : '元数据详情加载失败'); }
  };
  const reloadDetail = async () => { if (detail) await openDetail(detail.document.id); await refresh(); };

  const save = async () => {
    if (!detail || !current) return;
    try {
      const values = await form.validateFields();
      await updateMetadataRevision(detail.document.id, current.id, values);
      message.success('元数据草稿已保存'); await reloadDetail();
    } catch (error) { if (error instanceof Error) message.error(error.message); }
  };
  const createDraft = async (type: 'CORRECTION' | 'REPEAL') => {
    if (!detail) return;
    try {
      await createMetadataDraft(detail.document.id, type, type === 'REPEAL' ? '登记制度废止' : '修订制度元数据');
      message.success(type === 'REPEAL' ? '已创建废止修订草稿' : '已创建元数据修订草稿'); await reloadDetail();
    } catch (error) { message.error(error instanceof Error ? error.message : '创建修订失败'); }
  };
  const submit = async () => {
    if (!detail || !current) return;
    setActionLoading(true);
    try {
      const values = await form.validateFields();
      await updateMetadataRevision(detail.document.id, current.id, values);
      await submitMetadataRevision(detail.document.id, current.id);
      message.success('当前内容已保存并提交审核');
      await reloadDetail();
    } catch (error) { if (error instanceof Error) message.error(error.message); }
    finally { setActionLoading(false); }
  };
  const review = async (approved: boolean) => {
    if (!detail || !current) return;
    try { await reviewMetadataRevision(detail.document.id, current.id, approved, approved ? '元数据核对通过' : '元数据退回修改'); message.success(approved ? '审核通过，等待纳入IndexRun' : '已驳回'); await reloadDetail(); }
    catch (error) { message.error(error instanceof Error ? error.message : '审核失败'); }
  };
  const saveSeries = async () => {
    if (!detail) return;
    try {
      const values = await seriesForm.validateFields();
      await assignPolicySeries(detail.document.id, { series_id: values.series_id ?? null, canonical_title: values.canonical_title });
      message.success('制度系列归属已更新'); setSeriesOpen(false); await reloadDetail();
    } catch (error) { if (error instanceof Error) message.error(error.message); }
  };
  const buildPublication = async () => {
    const ids = selectedIds.map(Number);
    if (!ids.length) { message.warning('请选择至少一个已完成审核的制度文件'); return; }
    try { await createIndexPublication(ids); message.success('已创建全局索引快照构建请求'); setSelectedIds([]); await refresh(); }
    catch (error) { message.error(error instanceof Error ? error.message : '创建发布请求失败'); }
  };

  const canCreateRevision = current?.lifecycle_status === 'PUBLISHED' || current?.lifecycle_status === 'REJECTED';
  const canRegisterRepeal = current?.lifecycle_status === 'PUBLISHED' && current?.status === 'effective';

  const columns = [
    { title: '正式文件版本', key: 'title', render: (_: unknown, row: ManagedDocument) => <div><strong>{row.title || row.file_name}</strong><div><Typography.Text type="secondary">Document {row.id} · 系列版本 {row.document_version_no}</Typography.Text></div></div> },
    { title: '文号', dataIndex: 'document_code', width: 180, render: (value: string | null) => value || '-' },
    { title: '发布机构', dataIndex: 'issuing_org', width: 180, render: (value: string | null) => value || '-' },
    { title: '元数据', dataIndex: 'request_status', width: 135, render: (value: string) => <Tag color={value === 'PUBLISHED' ? 'green' : value === 'APPROVED' ? 'blue' : 'orange'}>{lifecycleLabels[value] ?? value}</Tag> },
    { title: '制度状态', dataIndex: 'status', width: 110, render: (value: string) => value === 'unknown' ? '待确认' : value },
    { title: '操作', width: 100, render: (_: unknown, row: ManagedDocument) => <Button type="link" onClick={() => void openDetail(row.id)}>治理</Button> },
  ];

  return <div className="admin-page governance-page">
    <div className="admin-page-title"><div><Typography.Title level={2}>制度治理与发布</Typography.Title><Typography.Text type="secondary">正式文件版本、制度系列、元数据修订和全局索引发布</Typography.Text></div><Space><Button icon={<UiIcon icon={ReloadOutlined} />} onClick={() => void refresh()}>刷新</Button><Button type="primary" icon={<UiIcon icon={FileSyncOutlined} />} onClick={() => void buildPublication()}>构建索引快照</Button></Space></div>
    <Alert showIcon type="info" message="只有Alias切换成功才算正式发布" description="元数据审核通过只形成候选版本；IndexRun会冻结Document、ParseRun、ChunkRun和MetadataRevision。切换失败时，旧索引和旧元数据继续生效。" />
    <Card variant="borderless" className="admin-table-card">
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search value={keywordInput} allowClear placeholder="搜索制度名称、文号、机构或责任部门" style={{ width: 360 }} onChange={(event) => setKeywordInput(event.target.value)} onSearch={(value) => { setPage(1); setKeyword(value.trim()); }} />
        <Select allowClear placeholder="元数据状态" style={{ width: 190 }} value={metadataStatus} onChange={(value) => { setPage(1); setMetadataStatus(value); }} options={[
          { value: 'ACTION_REQUIRED', label: '需要处理' }, { value: 'DRAFT', label: '草稿' },
          { value: 'PENDING_REVIEW', label: '待审核' }, { value: 'APPROVED', label: '审核通过待发布' },
          { value: 'PUBLISHED', label: '当前快照生效' }, { value: 'REJECTED', label: '已驳回' },
        ]} />
        <Select style={{ width: 190 }} value={sortBy} onChange={(value) => { setPage(1); setSortBy(value); }} options={[
          { value: 'ACTION_REQUIRED', label: '需要处理优先' }, { value: 'UPDATED_DESC', label: '最近更新优先' },
          { value: 'PUBLISH_DATE_DESC', label: '发布日期倒序' }, { value: 'TITLE_ASC', label: '制度名称排序' },
        ]} />
      </Space>
      <Table<ManagedDocument> rowKey="id" loading={loading} columns={columns} dataSource={documents} rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }} pagination={{ current: page, pageSize: 10, total, showSizeChanger: false, onChange: setPage }} />
    </Card>
    <Card title="索引发布生命周期" variant="borderless"><List dataSource={publications.slice(0, 8)} locale={{ emptyText: '尚无V2发布请求' }} renderItem={(item) => <List.Item actions={item.status === 'READY_TO_PUBLISH' ? [<Popconfirm key="publish" title="确认切换Alias并正式发布？" onConfirm={() => void confirmIndexPublication(item.id).then(() => { message.success('发布已排队'); return refresh(); }).catch((error) => message.error(error.message))}><Button type="primary" size="small">确认发布</Button></Popconfirm>] : item.status === 'FAILED' && item.can_retry ? [<Popconfirm key="retry" title="按原发布请求重试？" onConfirm={() => void retryIndexPublication(item.id).then(() => { message.success('发布请求已重新排队'); return refresh(); }).catch((error) => message.error(error.message))}><Button size="small">重试原请求</Button></Popconfirm>] : undefined}><Space><Tag color={item.status === 'PUBLISHED' ? 'green' : item.status === 'FAILED' ? 'red' : 'blue'}>{publicationLabels[item.status] ?? item.status}</Tag><Typography.Text>制度 {item.document_ids.join('、')} · IndexRun {item.index_run_id ?? '待生成'}</Typography.Text>{item.status === 'FAILED' && !item.can_retry && <Tag>历史记录，仅供审计</Tag>}{item.error_summary && <Typography.Text type="danger">{item.error_summary}</Typography.Text>}</Space></List.Item>} /></Card>

    <Drawer width={980} title="制度元数据治理" open={Boolean(detail)} onClose={() => setDetail(null)} extra={<Space><Button icon={<UiIcon icon={LinkOutlined} />} onClick={() => { seriesForm.setFieldsValue({ series_id: Number(detail?.document.series_id) }); setSeriesOpen(true); }}>制度系列</Button>{canCreateRevision && <Button icon={<UiIcon icon={EditOutlined} />} onClick={() => void createDraft('CORRECTION')}>新建修订</Button>}{canRegisterRepeal && <Button danger icon={<UiIcon icon={StopOutlined} />} onClick={() => void createDraft('REPEAL')}>登记废止</Button>}</Space>}>
      {detail && current && <div className="metadata-workbench">
        <section><Card size="small" title={`修订 ${current.revision_no} · ${lifecycleLabels[current.lifecycle_status] ?? current.lifecycle_status}`}>
          <Form form={form} layout="vertical" disabled={current.lifecycle_status !== 'DRAFT'}>
            <div className="metadata-form-grid">
              {Object.entries(fieldLabels).map(([name, label]) => name === 'status' ? <Form.Item key={name} name={name} label={label}><Select options={[{ value: 'effective', label: '现行有效' }, { value: 'repealed', label: '已废止' }, { value: 'expired', label: '已失效' }, { value: 'unknown', label: '状态待确认' }]} /></Form.Item> : <Form.Item key={name} name={name} label={label}><Input /></Form.Item>)}
            </div>
            <Form.Item name="status_confirmation_note" label="状态待确认保留原因"><Input.TextArea rows={2} /></Form.Item>
            <Form.Item name="change_reason" label="修订原因"><Input.TextArea rows={2} /></Form.Item>
            {(current.source_type === 'REPEAL' || current.status === 'repealed') && <><div className="metadata-form-grid"><Form.Item name="repeal_date" label="废止日期"><Input /></Form.Item><Form.Item name="repeal_reason" label="废止原因"><Input /></Form.Item><Form.Item name="repeal_evidence" label="废止依据"><Input /></Form.Item></div><Alert showIcon type="info" message="废止状态与制度关系分别留痕" description="本页确认该文件版本的废止元数据；如果由另一份制度废止，还应在制度关系页建立REPEALS关系并绑定原文证据。" action={<Button size="small" onClick={() => navigate('/admin/relations')}>前往制度关系</Button>} /></>}
          </Form>
          <Space>{current.lifecycle_status === 'DRAFT' && <><Button onClick={() => void save()}>保存草稿</Button><Button type="primary" loading={actionLoading} onClick={() => void submit()}>保存并提交审核</Button></>}{current.lifecycle_status === 'PENDING_REVIEW' && <><Button type="primary" icon={<UiIcon icon={CheckOutlined} />} onClick={() => void review(true)}>审核通过</Button><Button danger onClick={() => void review(false)}>驳回</Button></>}</Space>
        </Card></section>
        <aside><Card size="small" title="解析识别候选"><List size="small" dataSource={Object.entries(candidateGroups)} renderItem={([field, items]) => <List.Item><div><strong>{fieldLabels[field] ?? field}</strong>{items.slice(0, 3).map((item) => <p key={item.id}><Button type="link" size="small" disabled={current.lifecycle_status !== 'DRAFT'} onClick={() => form.setFieldValue(field as keyof MetadataRevision, item.normalized_value || item.raw_value)}>{item.normalized_value || item.raw_value}</Button><small>置信度 {(item.confidence * 100).toFixed(0)}% · 第{item.page_start ?? '-'}页</small></p>)}</div></List.Item>} /></Card><Card size="small" title="修订历史"><List size="small" dataSource={detail.revisions} renderItem={(item) => <List.Item><Space><Tag>{item.revision_no}</Tag><span>{lifecycleLabels[item.lifecycle_status] ?? item.lifecycle_status}</span></Space></List.Item>} /></Card></aside>
      </div>}
    </Drawer>
    <Modal title="设置制度系列" open={seriesOpen} onCancel={() => setSeriesOpen(false)} onOk={() => void saveSeries()}><Form form={seriesForm} layout="vertical"><Form.Item name="series_id" label="归入既有制度系列"><Select allowClear showSearch optionFilterProp="label" options={series.map((item) => ({ value: item.id, label: `${item.canonical_title}（${item.document_count}个版本）` }))} /></Form.Item><Form.Item name="canonical_title" label="系列标准名称"><Input placeholder="未选择既有系列时将创建新系列" /></Form.Item></Form></Modal>
  </div>;
}
