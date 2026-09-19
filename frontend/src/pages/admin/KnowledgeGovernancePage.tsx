/**
 * 文件说明：提供正式文件版本、制度系列、元数据修订、废止和索引发布的一体化治理页面。
 */
import { CheckOutlined, ClockCircleOutlined, EditOutlined, FileSyncOutlined, LinkOutlined, ReloadOutlined, RollbackOutlined, StopOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Drawer, Form, Input, List, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  assignPolicySeries, confirmIndexPublication, createIndexPublication, createMetadataDraft,
  getManagedDocument, listIndexPublications, listManagedDocuments, listPolicySeries,
  retryIndexPublication, reviewMetadataRevision, submitMetadataRevision, updateMetadataRevision,
  withdrawMetadataRevision,
} from '../../api/admin';
import type { IndexPublication, ManagedDocument, ManagedDocumentDetail, MetadataRevision, PolicySeries } from '../../api/admin';
import { UiIcon } from '../../components/UiIcon';
import { documentStatusClass, documentStatusLabel } from '../../utils/documentStatus';

const lifecycleLabels: Record<string, string> = {
  DRAFT: '元数据草稿', PENDING_REVIEW: '元数据待审核', APPROVED: '元数据审核通过（待纳入索引）',
  PUBLISHED: '已在当前快照生效', REJECTED: '元数据已驳回', WITHDRAWN: '已撤回', SUPERSEDED: '历史元数据版本',
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

const candidateFieldLabels: Record<string, string> = {
  ...fieldLabels,
  parser_profile: '解析结构类型',
};

// 元数据表单可人工选择的制度状态，文案复用制度库同一套映射，不开放"草案"。
const documentStatusOptions = ['effective', 'repealed', 'expired', 'unknown'].map((value) => ({
  value,
  label: documentStatusLabel(value),
}));

type DraftRequestType = 'CORRECTION' | 'REPEAL' | 'EXPIRY';

const sourceTypeByRequest: Record<DraftRequestType, MetadataRevision['source_type']> = {
  CORRECTION: 'MANUAL_CORRECTION',
  REPEAL: 'REPEAL',
  EXPIRY: 'EXPIRY',
};

const draftActionLabels: Record<DraftRequestType, string> = {
  CORRECTION: '元数据修订',
  REPEAL: '登记废止',
  EXPIRY: '登记失效',
};

function localDateToday(): string {
  // HTML date 输入使用本地日期，避免 UTC 转换在东八区日界附近出现偏差。
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

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
  const [pendingDraftType, setPendingDraftType] = useState<DraftRequestType | null>(null);
  const [pendingDraftDirty, setPendingDraftDirty] = useState(false);
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

  const activeRevision = detail?.revisions.find(
    (item) => item.id === Number(detail.document.active_metadata_revision_id),
  );
  const actionableRevision = detail?.revisions.find(
    (item) => ['DRAFT', 'PENDING_REVIEW', 'APPROVED', 'REJECTED'].includes(item.lifecycle_status),
  );
  // WITHDRAWN只出现在历史列表；没有待处理修订时主工作区展示active快照。
  const current = actionableRevision
    ?? activeRevision
    ?? detail?.revisions.find((item) => item.lifecycle_status !== 'WITHDRAWN')
    ?? null;
  const workingRevision = useMemo<MetadataRevision | null>(() => {
    if (!pendingDraftType) return current;
    const base = activeRevision ?? current;
    if (!base) return null;
    return {
      ...base,
      id: 0,
      revision_no: Math.max(...(detail?.revisions.map((item) => item.revision_no) ?? [0])) + 1,
      lifecycle_status: 'DRAFT',
      source_type: sourceTypeByRequest[pendingDraftType],
      status: pendingDraftType === 'REPEAL' ? 'repealed' : pendingDraftType === 'EXPIRY' ? 'expired' : base.status,
      change_reason: pendingDraftType === 'REPEAL' ? '登记制度废止' : null,
      repeal_date: pendingDraftType === 'REPEAL' ? localDateToday() : null,
      repeal_reason: null,
      repeal_evidence: null,
      expiry_date: pendingDraftType === 'EXPIRY' ? null : base.expiry_date,
    };
  }, [activeRevision, current, detail?.revisions, pendingDraftType]);
  useEffect(() => {
    if (workingRevision) {
      form.setFieldsValue({
        ...workingRevision,
        repeal_date: workingRevision.source_type === 'REPEAL'
          ? workingRevision.repeal_date || localDateToday()
          : workingRevision.repeal_date,
      });
    }
    else form.resetFields();
  }, [workingRevision?.id, workingRevision?.source_type]);
  const candidateGroups = useMemo(() => {
    const groups: Record<string, ManagedDocumentDetail['candidates']> = {};
    for (const item of detail?.candidates ?? []) (groups[item.field_name] ??= []).push(item);
    return groups;
  }, [detail]);

  const openDetail = async (documentId: number) => {
    try {
      setPendingDraftType(null);
      setPendingDraftDirty(false);
      setDetail(await getManagedDocument(documentId));
    }
    catch (error) { message.error(error instanceof Error ? error.message : '元数据详情加载失败'); }
  };
  const reloadDetail = async () => { if (detail) await openDetail(detail.document.id); await refresh(); };

  const save = async () => {
    if (!detail || !workingRevision) return;
    if (pendingDraftType && !pendingDraftDirty) {
      message.info('尚未修改任何内容，未创建草稿');
      return;
    }
    let materialized = false;
    try {
      const values = await form.validateFields();
      let revisionId = workingRevision.id;
      if (pendingDraftType) {
        const created = await createMetadataDraft(
          detail.document.id,
          pendingDraftType,
          typeof values.change_reason === 'string' ? values.change_reason : undefined,
        );
        revisionId = created.revision.id;
        materialized = true;
      }
      await updateMetadataRevision(detail.document.id, revisionId, values);
      message.success('元数据草稿已保存');
      await reloadDetail();
    } catch (error) {
      if (materialized) await reloadDetail();
      if (error instanceof Error) message.error(error.message);
    }
  };
  const beginDraft = (type: DraftRequestType) => {
    if (!detail || !current) return;
    const actionLabel = draftActionLabels[type];
    const lifecycleDescription = type === 'REPEAL'
      ? '废止是管理机关主动终止制度效力，需要填写废止原因和依据。'
      : type === 'EXPIRY'
        ? '失效是制度因有效期届满等客观条件不再有效。'
        : '元数据修订只校正文号、机构、日期等信息，不改变制度效力状态。';
    Modal.confirm({
      title: `进入${actionLabel}？`,
      content: <div><p>{lifecycleDescription}</p><p>此操作只进入编辑态；保存或提交后才会创建草稿，直接退出不会保存。</p></div>,
      okText: '进入编辑',
      cancelText: '取消',
      onOk: () => {
        setPendingDraftType(type);
        setPendingDraftDirty(false);
      },
    });
  };
  const submit = async () => {
    if (!detail || !workingRevision) return;
    if (pendingDraftType && !pendingDraftDirty) {
      message.info('尚未修改任何内容，未创建草稿');
      return;
    }
    setActionLoading(true);
    let materialized = false;
    try {
      const values = await form.validateFields();
      let revisionId = workingRevision.id;
      if (pendingDraftType) {
        const created = await createMetadataDraft(
          detail.document.id,
          pendingDraftType,
          typeof values.change_reason === 'string' ? values.change_reason : undefined,
        );
        revisionId = created.revision.id;
        materialized = true;
      }
      await updateMetadataRevision(detail.document.id, revisionId, values);
      await submitMetadataRevision(detail.document.id, revisionId);
      message.success('当前内容已保存并提交审核');
      await reloadDetail();
    } catch (error) {
      if (materialized) await reloadDetail();
      if (error instanceof Error) message.error(error.message);
    }
    finally { setActionLoading(false); }
  };
  const review = async (approved: boolean) => {
    if (!detail || !current) return;
    try { await reviewMetadataRevision(detail.document.id, current.id, approved, approved ? '元数据核对通过' : '元数据退回修改'); message.success(approved ? '审核通过，等待纳入IndexRun' : '已驳回'); await reloadDetail(); }
    catch (error) { message.error(error instanceof Error ? error.message : '审核失败'); }
  };
  const withdraw = () => {
    if (!detail || !current) return;
    let reason = '';
    Modal.confirm({
      title: `撤回修订 ${current.revision_no}？`,
      content: <Input.TextArea autoFocus rows={3} maxLength={2000} placeholder="请输入撤回原因" onChange={(event) => { reason = event.target.value; }} />,
      okText: '确认撤回',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        if (!reason.trim()) {
          message.error('请输入撤回原因');
          throw new Error('撤回原因不能为空');
        }
        await withdrawMetadataRevision(detail.document.id, current.id, reason.trim());
        message.success('元数据修订已撤回，可重新创建正确修订');
        await reloadDetail();
      },
    });
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

  const canCreateRevision = !pendingDraftType && ['PUBLISHED', 'REJECTED', 'WITHDRAWN'].includes(current?.lifecycle_status ?? '');
  const lifecycleActionBlocked = Boolean(pendingDraftType) || ['DRAFT', 'PENDING_REVIEW', 'APPROVED'].includes(current?.lifecycle_status ?? '');
  const canRegisterLifecycleChange = activeRevision?.status === 'effective' && !lifecycleActionBlocked;
  const statusLocked = ['MANUAL_CORRECTION', 'REPEAL', 'EXPIRY'].includes(workingRevision?.source_type ?? '');

  const columns = [
    { title: '正式文件版本', key: 'title', render: (_: unknown, row: ManagedDocument) => <div><strong>{row.title || row.file_name}</strong><div><Typography.Text type="secondary">Document {row.id} · 系列版本 {row.document_version_no}</Typography.Text></div></div> },
    { title: '文号', dataIndex: 'document_code', width: 180, render: (value: string | null) => value || '-' },
    { title: '发布机构', dataIndex: 'issuing_org', width: 180, render: (value: string | null) => value || '-' },
    { title: '元数据', dataIndex: 'request_status', width: 135, render: (value: string) => <Tag color={value === 'PUBLISHED' ? 'green' : value === 'APPROVED' ? 'blue' : 'orange'}>{lifecycleLabels[value] ?? value}</Tag> },
    { title: '制度状态', dataIndex: 'status', width: 110, render: (value: string) => { const label = documentStatusLabel(value); return <Tag className={`document-status-tag ${documentStatusClass(label)}`}>{label}</Tag>; } },
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
          { value: 'WITHDRAWN', label: '已撤回' },
        ]} />
        <Select style={{ width: 190 }} value={sortBy} onChange={(value) => { setPage(1); setSortBy(value); }} options={[
          { value: 'ACTION_REQUIRED', label: '需要处理优先' }, { value: 'UPDATED_DESC', label: '最近更新优先' },
          { value: 'PUBLISH_DATE_DESC', label: '发布日期倒序' }, { value: 'TITLE_ASC', label: '制度名称排序' },
        ]} />
      </Space>
      <Table<ManagedDocument> rowKey="id" loading={loading} columns={columns} dataSource={documents} rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }} pagination={{ current: page, pageSize: 10, total, showSizeChanger: false, onChange: setPage }} />
    </Card>
    <Card title="索引发布生命周期" variant="borderless"><List dataSource={publications.slice(0, 8)} locale={{ emptyText: '尚无V2发布请求' }} renderItem={(item) => <List.Item actions={item.status === 'READY_TO_PUBLISH' ? [<Popconfirm key="publish" title="确认切换Alias并正式发布？" onConfirm={() => void confirmIndexPublication(item.id).then(() => { message.success('发布已排队'); return refresh(); }).catch((error) => message.error(error.message))}><Button type="primary" size="small">确认发布</Button></Popconfirm>] : item.status === 'FAILED' && item.can_retry ? [<Popconfirm key="retry" title="按原发布请求重试？" onConfirm={() => void retryIndexPublication(item.id).then(() => { message.success('发布请求已重新排队'); return refresh(); }).catch((error) => message.error(error.message))}><Button size="small">重试原请求</Button></Popconfirm>] : undefined}><Space><Tag color={item.status === 'PUBLISHED' ? 'green' : item.status === 'FAILED' ? 'red' : 'blue'}>{publicationLabels[item.status] ?? item.status}</Tag><Typography.Text>制度 {item.document_ids.join('、')} · IndexRun {item.index_run_id ?? '待生成'}</Typography.Text>{item.status === 'FAILED' && !item.can_retry && <Tag>历史记录，仅供审计</Tag>}{item.error_summary && <Typography.Text type="danger">{item.error_summary}</Typography.Text>}</Space></List.Item>} /></Card>

    <Drawer width={980} title="制度元数据治理" open={Boolean(detail)} onClose={() => { setPendingDraftType(null); setPendingDraftDirty(false); setDetail(null); }} extra={<Space><Button icon={<UiIcon icon={LinkOutlined} />} onClick={() => { seriesForm.setFieldsValue({ series_id: Number(detail?.document.series_id) }); setSeriesOpen(true); }}>制度系列</Button>{canCreateRevision && <Button icon={<UiIcon icon={EditOutlined} />} onClick={() => beginDraft('CORRECTION')}>新建修订</Button>}{canRegisterLifecycleChange && <Button icon={<UiIcon icon={ClockCircleOutlined} />} onClick={() => beginDraft('EXPIRY')}>登记失效</Button>}{canRegisterLifecycleChange && <Button danger icon={<UiIcon icon={StopOutlined} />} onClick={() => beginDraft('REPEAL')}>登记废止</Button>}</Space>}>
      {detail && workingRevision && <div className="metadata-workbench">
        <section><Card size="small" title={pendingDraftType ? `${draftActionLabels[pendingDraftType]} · 未创建草稿` : `修订 ${workingRevision.revision_no} · ${lifecycleLabels[workingRevision.lifecycle_status] ?? workingRevision.lifecycle_status}`}>
          {pendingDraftType && <Alert showIcon type="warning" message="当前只是本地编辑态" description="修改内容并点击保存或提交后才会创建服务端草稿；直接退出不会留下修订记录。" style={{ marginBottom: 16 }} />}
          <Form form={form} layout="vertical" disabled={workingRevision.lifecycle_status !== 'DRAFT'} onValuesChange={() => { if (pendingDraftType) setPendingDraftDirty(true); }}>
            <div className="metadata-form-grid">
              {Object.entries(fieldLabels).map(([name, label]) => {
                if (name === 'status') {
                  return <Form.Item key={name} name={name} label={label}><Select disabled={statusLocked} options={documentStatusOptions} /></Form.Item>;
                }
                const expiryRequired = workingRevision.source_type === 'EXPIRY' && name === 'expiry_date';
                const isDateField = ['publish_date', 'effective_date', 'expiry_date'].includes(name);
                return <Form.Item key={name} name={name} label={label} rules={expiryRequired ? [{ required: true, message: '请填写失效日期' }] : undefined}><Input type={isDateField ? 'date' : 'text'} /></Form.Item>;
              })}
            </div>
            <Form.Item name="status_confirmation_note" label="状态待确认保留原因"><Input.TextArea rows={2} /></Form.Item>
            <Form.Item name="change_reason" label={workingRevision.source_type === 'EXPIRY' ? '失效说明' : '修订原因'} rules={workingRevision.source_type === 'EXPIRY' ? [{ required: true, message: '请填写失效说明' }] : undefined}><Input.TextArea rows={2} /></Form.Item>
            {workingRevision.source_type === 'EXPIRY' && <Alert showIcon type="info" message="失效：因有效期届满等客观条件终止效力" description="请使用日期控件确认失效日期并填写失效说明；审核通过后仍需构建全量 IndexRun，并在 Alias 切换成功后正式生效。" />}
            {(workingRevision.source_type === 'REPEAL' || workingRevision.status === 'repealed') && <><div className="metadata-form-grid"><Form.Item name="repeal_date" label="废止日期" rules={workingRevision.source_type === 'REPEAL' ? [{ required: true, message: '请填写废止日期' }] : undefined}><Input type="date" /></Form.Item><Form.Item name="repeal_reason" label="废止原因" rules={workingRevision.source_type === 'REPEAL' ? [{ required: true, message: '请填写废止原因' }] : undefined}><Input /></Form.Item><Form.Item name="repeal_evidence" label="废止依据" rules={workingRevision.source_type === 'REPEAL' ? [{ required: true, message: '请填写废止依据' }] : undefined}><Input /></Form.Item></div><Alert showIcon type="info" message="废止：由管理机关主动终止制度效力" description="本页确认该文件版本的废止元数据；如果由另一份制度废止，还应在制度关系页建立REPEALS关系并绑定原文证据。" action={<Button size="small" onClick={() => navigate('/admin/relations')}>前往制度关系</Button>} /></>}
          </Form>
          <Space>{workingRevision.lifecycle_status === 'DRAFT' && <>{pendingDraftType && <Button onClick={() => { setPendingDraftType(null); setPendingDraftDirty(false); }}>退出编辑</Button>}<Button onClick={() => void save()}>保存草稿</Button><Button type="primary" loading={actionLoading} onClick={() => void submit()}>保存并提交审核</Button></>}{workingRevision.lifecycle_status === 'PENDING_REVIEW' && <><Button type="primary" icon={<UiIcon icon={CheckOutlined} />} onClick={() => void review(true)}>审核通过</Button><Button danger onClick={() => void review(false)}>驳回</Button></>}{!pendingDraftType && ['DRAFT', 'PENDING_REVIEW', 'APPROVED'].includes(workingRevision.lifecycle_status) && workingRevision.source_type !== 'PARSE_EXTRACTED' && <Button danger icon={<UiIcon icon={RollbackOutlined} />} onClick={withdraw}>撤回修订</Button>}</Space>
        </Card></section>
        <aside><Card size="small" title="解析识别候选"><List size="small" dataSource={Object.entries(candidateGroups)} renderItem={([field, items]) => <List.Item className="metadata-candidate-group"><div><strong>{candidateFieldLabels[field] ?? field}</strong>{items.slice(0, 3).map((item) => <div className="metadata-candidate-item" key={item.id}><Button block type="link" size="small" disabled={workingRevision.lifecycle_status !== 'DRAFT' || !(field in fieldLabels)} onClick={() => { form.setFieldValue(field as keyof MetadataRevision, item.normalized_value || item.raw_value); if (pendingDraftType) setPendingDraftDirty(true); }}>{item.normalized_value || item.raw_value}</Button><small>置信度 {(item.confidence * 100).toFixed(0)}% · {item.page_start ? `第${item.page_start}页` : '未定位页码'}</small></div>)}</div></List.Item>} /></Card><Card size="small" title="修订历史"><List size="small" dataSource={detail.revisions} renderItem={(item) => <List.Item><Space><Tag>{item.revision_no}</Tag><span>{lifecycleLabels[item.lifecycle_status] ?? item.lifecycle_status}</span></Space></List.Item>} /></Card></aside>
      </div>}
    </Drawer>
    <Modal title="设置制度系列" open={seriesOpen} onCancel={() => setSeriesOpen(false)} onOk={() => void saveSeries()}><Form form={seriesForm} layout="vertical"><Form.Item name="series_id" label="归入既有制度系列"><Select allowClear showSearch optionFilterProp="label" options={series.map((item) => ({ value: item.id, label: `${item.canonical_title}（${item.document_count}个版本）` }))} /></Form.Item><Form.Item name="canonical_title" label="系列标准名称"><Input placeholder="未选择既有系列时将创建新系列" /></Form.Item></Form></Modal>
  </div>;
}
