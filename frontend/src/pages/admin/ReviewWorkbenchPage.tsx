/**
 * 文件说明：展示真实ParseRun/ChunkRun详情、质量问题、PDF页码和标准审核决策。
 */
import { ArrowRightOutlined, CheckCircleOutlined, CloseCircleOutlined, FileSearchOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Form, Input, InputNumber, List, Modal, Radio, Segmented, Select, Space, Spin, Tabs, Tag, Typography, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { createParseCorrection, decideReview, decideReviewItem, getReviewDetail, listReviews, reviewPdfUrl } from '../../api/admin';
import type { ReviewDetail, ReviewQueueItem } from '../../api/admin';
import { UiIcon } from '../../components/UiIcon';

const metricLabel: Record<string, string> = {
  node_count: '章节节点', source_block_count: '原始块', field_count: '字段候选', issue_count: '问题数',
  open_issue_count: '未处理问题', page_mapping_coverage: '页码覆盖率', character_coverage: '字符覆盖率',
  chunk_count: 'Chunk总数', retrievable_count: '可检索Chunk', context_count: '上下文Chunk',
  block_coverage: '原始块覆盖率', table_cell_coverage: '表格单元格覆盖率',
  eligible_node_count: '应覆盖节点', mapped_node_count: '已映射节点', eligible_node_coverage: '节点覆盖率',
  eligible_character_coverage: '有效字符覆盖率', retrievable_character_coverage: '可检索字符覆盖率',
  unmapped_node_count: '未映射节点', duplicate_count: '重复数', validation_issue_count: '校验问题',
};

const runTypeLabel = { PARSE_RUN: '解析结果', CHUNK_RUN: '分块结果' } as const;
const stateLabel: Record<string, string> = {
  PARSE_REVIEW: '解析待审核', CHUNK_QUEUED: '等待分块', CHUNKING: '分块中', CHUNK_REVIEW: '分块待审核',
  INDEX_QUEUED: '等待索引', INDEXING: '索引构建中', READY_TO_PUBLISH: '索引已构建，待确认发布',
  PUBLISH_QUEUED: '等待Alias切换', PUBLISHING: 'Alias切换中', PUBLISHED: '处理完成', REJECTED: '已驳回',
};
const fieldLabel: Record<string, string> = {
  title: '制度名称', document_code: '文号', document_type: '文种', issuing_org: '发布机构',
  addressee_text: '主送对象', publish_date: '发布日期', effective_date: '生效日期', expiry_date: '失效日期',
  owner_department: '责任部门', authority_level: '效力层级', confidentiality_level: '密级', status: '制度状态',
  version: '制度版本', parser_profile: '解析结构类型',
};
const chunkTypeLabel: Record<string, string> = {
  paragraph: '正文段落', article: '条款', context: '上下文', table: '表格', heading: '标题', attachment: '附件',
};

const percentMetrics = new Set(['page_mapping_coverage', 'character_coverage', 'block_coverage', 'table_cell_coverage', 'eligible_node_coverage', 'eligible_character_coverage', 'retrievable_character_coverage']);

function renderMetric(key: string, value: unknown) {
  if (percentMetrics.has(key) && typeof value === 'number') return `${(value * 100).toFixed(1)}%`;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '-');
}

export function ReviewWorkbenchPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [runType, setRunType] = useState<'PARSE_RUN' | 'CHUNK_RUN'>('PARSE_RUN');
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState('');
  const [outcome, setOutcome] = useState<'PASS' | 'PASS_WITH_WARNING' | 'REJECT'>('PASS');
  const [comment, setComment] = useState('');
  const [nextNotice, setNextNotice] = useState<{ kind: 'METADATA_WAIT' | 'INDEX_WAIT'; jobId: string } | null>(null);
  const [correctionNode, setCorrectionNode] = useState<ReviewDetail['nodes'][number] | null>(null);
  const detailRequestRevision = useRef(0);
  const [correctionForm] = Form.useForm<{ title?: string; node_number?: string; node_type?: string; parent_id?: number; order_no?: number }>();

  const refresh = async (preferred?: { jobId: string; targetType: 'PARSE_RUN' | 'CHUNK_RUN' }, silent = false) => {
    try {
      const result = await listReviews(true);
      setItems(result);
      if (preferred) {
        const target = result.find((item) => item.job_id === preferred.jobId && item.target_type === preferred.targetType);
        if (target) { setRunType(preferred.targetType); setSelected(target); return; }
      }
      if (!result.some((item) => item.target_type === runType) && result[0]) setRunType(result[0].target_type);
      setSelected((current) => result.find((item) => item.job_id === current?.job_id && item.target_type === current?.target_type)
        ?? result.find((item) => item.target_type === runType)
        ?? result[0]
        ?? null);
    } catch (error) { if (!silent) message.error(error instanceof Error ? error.message : '审核队列加载失败'); }
  };
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    const poll = () => { if (document.visibilityState === 'visible') void refresh(undefined, true); };
    const timer = window.setInterval(poll, 5000);
    document.addEventListener('visibilitychange', poll);
    window.addEventListener('focus', poll);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
      window.removeEventListener('focus', poll);
    };
  }, [runType]);
  useEffect(() => {
    const revision = detailRequestRevision.current + 1;
    detailRequestRevision.current = revision;
    setOutcome('PASS');
    setComment('');
    setNextNotice(null);
    setSelectedContent('');
    setDetail(null);
    if (!selected) { setDetailLoading(false); return; }
    setDetailLoading(true);
    void getReviewDetail(selected.job_id, selected.target_type)
      .then((value) => {
        if (detailRequestRevision.current !== revision) return;
        setDetail(value);
        const hasOrdinaryWarning = value.issues.some(
          (item) => !item.resolved && item.severity.toLowerCase() === 'warning',
        );
        setOutcome(hasOrdinaryWarning ? 'PASS_WITH_WARNING' : 'PASS');
      })
      .catch((error) => {
        if (detailRequestRevision.current === revision) message.error(error instanceof Error ? error.message : '运行详情加载失败');
      })
      .finally(() => {
        if (detailRequestRevision.current === revision) setDetailLoading(false);
      });
  }, [selected?.job_id, selected?.target_type]);

  const unresolvedIssues = useMemo(() => detail?.issues.filter((item) => !item.resolved) ?? [], [detail]);
  const pendingFieldCount = useMemo(() => detail?.fields.filter((item) => String(item.review_status) === 'pending').length ?? 0, [detail]);
  const pendingNodeCount = useMemo(() => detail?.nodes.filter((item) => String(item.review_status) === 'pending').length ?? 0, [detail]);
  const blockingIssueCount = useMemo(() => detail?.issues.filter((item) => !item.resolved && item.severity.toLowerCase() === 'error').length ?? 0, [detail]);
  const filteredItems = useMemo(() => items.filter((item) => item.target_type === runType), [items, runType]);
  const parseCount = useMemo(() => items.filter((item) => item.target_type === 'PARSE_RUN').length, [items]);
  const chunkCount = items.length - parseCount;
  const approvalBlocked = outcome !== 'REJECT' && (
    (selected?.target_type === 'PARSE_RUN' && pendingNodeCount > 0) || blockingIssueCount > 0
  );

  const submit = async () => {
    if (!selected) return;
    try {
      await decideReview(selected.job_id, outcome, comment || undefined);
      setComment('');
      if (outcome !== 'REJECT' && selected.target_type === 'PARSE_RUN') {
        setNextNotice({ kind: 'METADATA_WAIT', jobId: selected.job_id });
        message.success('ParseRun结构审核通过，请继续确认制度元数据');
      } else if (outcome !== 'REJECT' && selected.target_type === 'CHUNK_RUN') {
        setNextNotice({ kind: 'INDEX_WAIT', jobId: selected.job_id });
        message.success('ChunkRun审核通过，可在制度治理页纳入索引快照');
      } else {
        setNextNotice(null); message.success('审核结果已提交');
      }
      await refresh({ jobId: selected.job_id, targetType: selected.target_type });
    } catch (error) { message.error(error instanceof Error ? error.message : '审核提交失败'); }
  };

  const handleItem = async (target_type: 'issue' | 'field' | 'node' | 'chunk_issue' | 'chunk', target_id: number, action: 'confirm' | 'ignore') => {
    if (!selected) return;
    try {
      await decideReviewItem(selected.job_id, { target_type, target_id, action });
      setDetail(await getReviewDetail(selected.job_id, selected.target_type));
      message.success('审核对象已处理');
    } catch (error) { message.error(error instanceof Error ? error.message : '审核对象处理失败'); }
  };

  const openCorrection = (node: ReviewDetail['nodes'][number]) => {
    setCorrectionNode(node);
    correctionForm.setFieldsValue({
      title: node.title ?? undefined,
      node_number: typeof node.node_number === 'string' ? node.node_number : undefined,
      node_type: node.node_type,
      parent_id: node.parent_id ?? undefined,
      order_no: typeof node.order_no === 'number' ? node.order_no : undefined,
    });
  };

  const submitCorrection = async () => {
    if (!selected?.document_id || !correctionNode) return;
    try {
      const values = await correctionForm.validateFields();
      await createParseCorrection(selected.document_id, {
        source_parse_run_id: Number(selected.target_id),
        source_node_id: correctionNode.id,
        ...values,
      });
      message.success('已生成MANUAL_CORRECTION派生ParseRun和新返工任务');
      setCorrectionNode(null); correctionForm.resetFields(); await refresh();
    } catch (error) { if (error instanceof Error) message.error(error.message); }
  };

  const contentTab = detail?.target_type === 'PARSE_RUN' ? (
      <List dataSource={detail.nodes} renderItem={(node) => (
      <List.Item
        className="review-content-row"
        actions={String(node.review_status) === 'pending'
          ? [<Button key="confirm" type="link" onClick={(event) => { event.stopPropagation(); void handleItem('node', node.id, 'confirm'); }}>确认结构</Button>]
          : String(detail.run.review_status) === 'approved'
            ? [<Button key="correct" type="link" onClick={(event) => { event.stopPropagation(); openCorrection(node); }}>派生修正</Button>]
            : undefined}
        onClick={() => setSelectedContent(node.text || node.title || '')}
      >
        <div><Tag>{node.node_type}</Tag><strong>{node.path_text || node.title || `Node ${node.id}`}</strong></div>
        <small>第 {node.page_start ?? '-'}—{node.page_end ?? node.page_start ?? '-'} 页 · Node {node.id} · {String(node.review_status) === 'pending' ? '待确认' : '已确认'}</small>
      </List.Item>
    )} />
  ) : (
    <List dataSource={detail?.chunks ?? []} renderItem={(chunk) => (
      <List.Item className="review-content-row" onClick={() => setSelectedContent(chunk.retrieval_text)}>
        <div><Tag color={chunk.is_retrievable ? 'blue' : 'default'}>{chunkTypeLabel[chunk.chunk_type] ?? chunk.chunk_type}</Tag><strong>{chunk.path_text || chunk.chunk_key}</strong></div>
        <small>{chunk.char_count} 字 · {chunk.token_count ?? '-'} tokens · 来源Node {chunk.sources.length}</small>
      </List.Item>
    )} />
  );

  return (
    <div className="admin-page review-page">
      <div className="admin-page-title"><div><Typography.Title level={2}>ParseRun / ChunkRun 审核工作台</Typography.Title><Typography.Text type="secondary">直接审核真实结构、字段、页码、Chunk来源和质量问题</Typography.Text></div><Tag color="blue">运行记录 {items.length}</Tag></div>
      {nextNotice && <Alert showIcon type="info" message={nextNotice.kind === 'METADATA_WAIT' ? '下一步：确认制度元数据' : '下一步：构建索引快照'} description={nextNotice.kind === 'METADATA_WAIT' ? `解析识别出的 ${pendingFieldCount} 个字段候选将在统一元数据页面核对；确认通过后Worker才生成ChunkRun。` : '该制度已进入“可纳入索引”，管理员可与其他制度变更合并为一次全局IndexRun。'} action={<Space><Button size="small" icon={<UiIcon icon={ReloadOutlined} />} onClick={() => void refresh()}>刷新运行</Button><Button size="small" type="primary" icon={<UiIcon icon={ArrowRightOutlined} />} onClick={() => navigate('/admin/knowledge')}>制度治理</Button></Space>} />}
      {!selected ? <Card variant="borderless"><Empty image={<UiIcon icon={FileSearchOutlined} />} description="当前没有待审核的 ParseRun 或 ChunkRun" /></Card> : (
        <div className="review-workbench">
          <Card className="review-queue" title="运行与历史" variant="borderless"><Segmented block className="review-type-switch" value={runType} options={[{ label: `解析 ${parseCount}`, value: 'PARSE_RUN' }, { label: `分块 ${chunkCount}`, value: 'CHUNK_RUN' }]} onChange={(value) => { const type = value as 'PARSE_RUN' | 'CHUNK_RUN'; const next = items.find((item) => item.target_type === type); if (!next) { message.info(`暂无${runTypeLabel[type]}`); return; } setRunType(type); setSelected(next); }} /><List dataSource={filteredItems} locale={{ emptyText: `暂无${runTypeLabel[runType]}` }} renderItem={(item) => <button type="button" className={`review-queue-item${selected.job_id === item.job_id && selected.target_type === item.target_type ? ' active' : ''}`} onClick={() => setSelected(item)}><strong>{item.title}</strong><span><Tag>{runTypeLabel[item.target_type]}</Tag>运行 {item.target_id} · {item.issue_count} 项待处理</span></button>} /></Card>
          <Card className="review-main" variant="borderless" title={`${runTypeLabel[selected.target_type]}审核`} extra={<Typography.Text copyable>{selected.target_id}</Typography.Text>}>
            <Spin spinning={detailLoading}>
              {detail && <>
                <div className="review-document-meta"><Typography.Title level={4}>{String(detail.run.document_title ?? selected.title)}</Typography.Title><Space wrap><Tag color="blue">{stateLabel[selected.state] ?? selected.state}</Tag><span>制度ID：{selected.document_id}</span><span>审核状态：{String(detail.run.review_status ?? '-')}</span>{detail.run.render_engine && <span>渲染引擎：{detail.run.render_engine}</span>}</Space></div>
                <div className="review-metrics">{Object.entries(detail.metrics).filter(([, value]) => typeof value !== 'object').map(([key, value]) => <div key={key}><small>{metricLabel[key] ?? key}</small><strong>{renderMetric(key, value)}</strong></div>)}</div>
                <Tabs items={[
                  { key: 'content', label: detail.target_type === 'PARSE_RUN' ? `节点树（${detail.nodes.length}）` : `Chunk（${detail.chunks.length}）`, children: contentTab },
                  { key: 'fields', label: `字段候选（${detail.fields.length}）`, children: <List dataSource={detail.fields} locale={{ emptyText: '本运行无字段候选' }} renderItem={(field) => <List.Item><Space direction="vertical" size={0}><Space><strong>{fieldLabel[field.field_name] ?? field.field_name}</strong><Tag color="blue">供元数据页核对</Tag></Space><span>{field.normalized_value || field.raw_value}</span><small>置信度 {(field.confidence * 100).toFixed(1)}%</small></Space></List.Item>} /> },
                  { key: 'issues', label: `问题（${detail.issues.length}）`, children: <List dataSource={detail.issues} locale={{ emptyText: '未发现质量问题' }} renderItem={(issue) => <List.Item actions={!issue.resolved && issue.severity.toLowerCase() !== 'error' ? [<Button key="ignore" type="link" onClick={() => void handleItem(detail.target_type === 'PARSE_RUN' ? 'issue' : 'chunk_issue', issue.id, 'ignore')}>确认并接受</Button>] : undefined}><Space direction="vertical" size={2}><Space><Tag color={issue.severity.toLowerCase() === 'error' ? 'red' : 'orange'}>{issue.severity}</Tag><Tag>{issue.issue_type}</Tag><strong>{issue.issue_code}</strong>{issue.resolved && <Tag color="green">已处理</Tag>}</Space><span>{issue.message}</span></Space></List.Item>} /> },
                  ...(detail.pdf_available ? [{ key: 'pdf', label: `PDF（${detail.run.page_count ?? '-'}页）`, children: <iframe className="review-pdf" title="ParseRun PDF" src={reviewPdfUrl(selected.job_id)} /> }] : []),
                ]} />
                {selectedContent && <Card size="small" title="当前选中内容" className="review-selected-content"><Typography.Paragraph>{selectedContent}</Typography.Paragraph></Card>}
                {((selected.target_type === 'PARSE_RUN' && selected.state === 'PARSE_REVIEW') || (selected.target_type === 'CHUNK_RUN' && selected.state === 'CHUNK_REVIEW')) ? <div className="review-decision">{approvalBlocked && <Alert showIcon type="warning" message="暂不能通过" description={blockingIssueCount > 0 ? `还有 ${blockingIssueCount} 个阻断问题待处理。` : `还有 ${pendingNodeCount} 个结构节点待确认，请先在上方页签逐项处理。元数据字段将在下一节点统一确认。`} />}<Radio.Group value={outcome} onChange={(event) => setOutcome(event.target.value)}><Radio.Button value="PASS"><UiIcon icon={CheckCircleOutlined} /> 通过</Radio.Button><Radio.Button value="PASS_WITH_WARNING"><UiIcon icon={WarningOutlined} /> 警告通过</Radio.Button><Radio.Button value="REJECT"><UiIcon icon={CloseCircleOutlined} /> 驳回</Radio.Button></Radio.Group><Input.TextArea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder={outcome === 'PASS_WITH_WARNING' ? '请逐项说明接受警告的理由' : outcome === 'REJECT' ? '必须填写驳回原因' : '可填写审核意见'} /><Button type="primary" disabled={approvalBlocked} onClick={() => void submit()}>提交审核结果</Button></div> : <div className="review-history-notice"><Tag color="green">只读历史</Tag><Typography.Text type="secondary">该运行已完成审核，当前详情不可修改。</Typography.Text></div>}
              </>}
            </Spin>
          </Card>
          <Card className="review-quality" title="质量检查" variant="borderless">{detail ? <><div className="quality-list">{Object.entries(detail.metrics).filter(([, value]) => typeof value !== 'object').map(([key, value]) => <div className="quality-line" key={key}><span>{metricLabel[key] ?? key}</span><strong>{renderMetric(key, value)}</strong></div>)}</div><div className="quality-summary"><Tag color={unresolvedIssues.length ? 'orange' : 'green'}>{unresolvedIssues.length ? `${unresolvedIssues.length} 个未处理问题` : '检查通过'}</Tag></div></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}</Card>
        </div>
      )}
      <Modal title="派生ParseRun结构修正" open={Boolean(correctionNode)} onCancel={() => setCorrectionNode(null)} onOk={() => void submitCorrection()} okText="创建返工任务">
        <Alert showIcon type="info" message="历史运行保持不可变" description="本操作复制已批准ParseRun并生成MANUAL_CORRECTION运行。原文内容变化请上传修正版DOCX，不在此处改写正文。" />
        <Form form={correctionForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="title" label="节点标题"><Input /></Form.Item>
          <div className="metadata-form-grid"><Form.Item name="node_number" label="节点编号"><Input /></Form.Item><Form.Item name="node_type" label="节点类型"><Input /></Form.Item></div>
          <Form.Item name="parent_id" label="父节点"><Select allowClear showSearch optionFilterProp="label" options={(detail?.nodes ?? []).filter((item) => item.id !== correctionNode?.id).map((item) => ({ value: item.id, label: `${item.path_text || item.title || `Node ${item.id}`}（${item.id}）` }))} /></Form.Item>
          <Form.Item name="order_no" label="同级顺序"><InputNumber min={0} precision={0} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
