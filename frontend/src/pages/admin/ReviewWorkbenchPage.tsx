/**
 * 文件说明：展示真实ParseRun/ChunkRun详情、质量问题、PDF页码和标准审核决策。
 */
import { ArrowRightOutlined, CheckCircleOutlined, CloseCircleOutlined, FileSearchOutlined, FileTextOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Form, Input, InputNumber, List, Modal, Pagination, Popconfirm, Radio, Segmented, Select, Space, Spin, Tabs, Tag, Tree, Typography, message } from 'antd';
import type { CSSProperties, Key } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DataNode } from 'antd/es/tree';

import { batchReviewItems, createParseCorrection, decideArticleTitle, decideReview, decideReviewItem, getReviewDetail, listReviews, reviewPdfUrl } from '../../api/admin';
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
const displayStateLabel: Record<string, { text: string; color: string }> = {
  ACTION_REQUIRED: { text: '有待处理项', color: 'orange' },
  READY_TO_SUBMIT: { text: '可提交审核', color: 'blue' },
  PASS: { text: '已通过', color: 'green' },
  PASS_WITH_WARNING: { text: '警告通过', color: 'orange' },
  REJECT: { text: '已驳回', color: 'red' },
  FAILED: { text: '运行失败', color: 'red' },
};
const nodeReviewLabel: Record<string, { text: string; color: string }> = {
  pending: { text: '待确认', color: 'orange' },
  confirmed: { text: '已确认', color: 'green' },
  not_required: { text: '无需人工确认', color: 'blue' },
  rejected: { text: '已驳回', color: 'red' },
};
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

type ReviewNode = ReviewDetail['nodes'][number];

interface ReviewNodeTreeData extends DataNode {
  key: string;
  title: string;
  reviewNode: ReviewNode;
  descendantCount: number;
  children?: ReviewNodeTreeData[];
}

function reviewNodeTitle(node: ReviewNode): string {
  const number = typeof node.node_number === 'string' ? node.node_number.trim() : '';
  const title = node.title?.trim() ?? '';
  if (number && title) return `${number} ${title}`;
  return number || title || node.path_text?.trim() || node.text?.trim().slice(0, 60) || `Node ${node.id}`;
}

/** 使用Parser输出的真实parent_id构建审核树，不根据标题文本推断层级。 */
function buildReviewNodeTree(nodes: ReviewNode[]): ReviewNodeTreeData[] {
  const byId = new Map<number, ReviewNodeTreeData>();
  const roots: ReviewNodeTreeData[] = [];
  nodes.forEach((node) => {
    byId.set(node.id, {
      key: String(node.id),
      title: reviewNodeTitle(node),
      reviewNode: node,
      descendantCount: 0,
    });
  });
  nodes.forEach((node) => {
    const item = byId.get(node.id);
    const parent = node.parent_id != null && node.parent_id !== node.id ? byId.get(node.parent_id) : undefined;
    if (!item) return;
    if (parent) parent.children = [...(parent.children ?? []), item];
    else roots.push(item);
  });

  const orderOf = (item: ReviewNodeTreeData) => Number(item.reviewNode.order_no ?? item.reviewNode.id);
  const finalize = (item: ReviewNodeTreeData, visiting: Set<string>): number => {
    if (visiting.has(item.key)) return 0;
    visiting.add(item.key);
    item.children?.sort((left, right) => orderOf(left) - orderOf(right));
    item.descendantCount = (item.children ?? []).reduce(
      (count, child) => count + 1 + finalize(child, visiting),
      0,
    );
    visiting.delete(item.key);
    return item.descendantCount;
  };
  roots.sort((left, right) => orderOf(left) - orderOf(right));
  roots.forEach((root) => finalize(root, new Set()));
  return roots;
}

function filterReviewNodeTree(nodes: ReviewNodeTreeData[], keyword: string): ReviewNodeTreeData[] {
  const query = keyword.trim().toLocaleLowerCase();
  if (!query) return nodes;
  return nodes.flatMap((item) => {
    const node = item.reviewNode;
    const searchable = [item.title, node.text, node.path_text, node.node_type, `Node ${node.id}`]
      .filter((value): value is string => typeof value === 'string')
      .join(' ')
      .toLocaleLowerCase();
    const children = filterReviewNodeTree(item.children ?? [], query);
    return searchable.includes(query) || children.length ? [{ ...item, children }] : [];
  });
}

function collectReviewNodeKeys(nodes: ReviewNodeTreeData[]): string[] {
  return nodes.flatMap((item) => [item.key, ...collectReviewNodeKeys(item.children ?? [])]);
}

function reviewSourceUrl(jobId: string, page: number | null): string {
  const source = reviewPdfUrl(jobId);
  return page != null && page > 0 ? `${source}#page=${page}` : source;
}

export function ReviewWorkbenchPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [runType, setRunType] = useState<'PARSE_RUN' | 'CHUNK_RUN'>('PARSE_RUN');
  const [processingStatus, setProcessingStatus] = useState<'PENDING' | 'PROCESSED'>('PENDING');
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [reviewState, setReviewState] = useState<string | undefined>();
  const [sortBy, setSortBy] = useState<'UPDATED_DESC' | 'OLDEST_PENDING' | 'TITLE_ASC'>('UPDATED_DESC');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [queueCounts, setQueueCounts] = useState<Record<string, number>>({});
  const [queueLoading, setQueueLoading] = useState(false);
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState('');
  const [selectedSourcePage, setSelectedSourcePage] = useState<number | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<Key | null>(null);
  const [nodeKeyword, setNodeKeyword] = useState('');
  const [expandedNodeKeys, setExpandedNodeKeys] = useState<Key[]>([]);
  const [outcome, setOutcome] = useState<'PASS' | 'PASS_WITH_WARNING' | 'REJECT'>('PASS');
  const [comment, setComment] = useState('');
  const [batchIssueOpen, setBatchIssueOpen] = useState(false);
  const [batchComment, setBatchComment] = useState('');
  const [articleTitleNode, setArticleTitleNode] = useState<ReviewDetail['nodes'][number] | null>(null);
  const [articleTitleMode, setArticleTitleMode] = useState<'TITLE' | 'CONTENT'>('TITLE');
  const [articleTitleValue, setArticleTitleValue] = useState('');
  const [articleTitleComment, setArticleTitleComment] = useState('');
  const [activeTab, setActiveTab] = useState('content');
  const [nextNotice, setNextNotice] = useState<{ kind: 'METADATA_WAIT' | 'INDEX_WAIT'; jobId: string } | null>(null);
  const [correctionNode, setCorrectionNode] = useState<ReviewDetail['nodes'][number] | null>(null);
  const detailRequestRevision = useRef(0);
  const reviewMainRef = useRef<HTMLDivElement>(null);
  const [reviewMainHeight, setReviewMainHeight] = useState<number>();
  const [correctionForm] = Form.useForm<{ title?: string; node_number?: string; node_type?: string; parent_id?: number; order_no?: number }>();

  const refresh = async (
    preferred?: { jobId: string; targetType: 'PARSE_RUN' | 'CHUNK_RUN' },
    silent = false,
    overrides?: { processingStatus?: 'PENDING' | 'PROCESSED'; page?: number },
  ) => {
    if (!silent) setQueueLoading(true);
    try {
      const requestedStatus = overrides?.processingStatus ?? processingStatus;
      const requestedPage = overrides?.page ?? page;
      const result = await listReviews({
        include_history: true,
        processing_status: requestedStatus,
        target_type: runType,
        keyword: keyword || undefined,
        review_state: reviewState,
        sort_by: sortBy,
        page: requestedPage,
      });
      setItems(result.items);
      setTotal(result.total);
      setQueueCounts(result.counts);
      if (preferred) {
        const target = result.items.find((item) => item.job_id === preferred.jobId && item.target_type === preferred.targetType);
        if (target) { setSelected(target); return; }
      }
      setSelected((current) => {
        const target = result.items.find((item) => item.job_id === current?.job_id && item.target_type === current?.target_type)
          ?? result.items[0]
          ?? null;
        return target;
      });
    } catch (error) { if (!silent) message.error(error instanceof Error ? error.message : '审核队列加载失败'); }
    finally { if (!silent) setQueueLoading(false); }
  };
  useEffect(() => { void refresh(); }, [processingStatus, runType, keyword, reviewState, sortBy, page]);
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
  }, [runType, processingStatus, keyword, reviewState, sortBy, page]);
  useEffect(() => {
    const revision = detailRequestRevision.current + 1;
    detailRequestRevision.current = revision;
    setOutcome('PASS');
    setComment('');
    setNextNotice(null);
    setSelectedContent('');
    setSelectedSourcePage(null);
    setSelectedNodeKey(null);
    setNodeKeyword('');
    setExpandedNodeKeys([]);
    setActiveTab('content');
    setDetail(null);
    if (!selected) { setDetailLoading(false); return; }
    setDetailLoading(true);
    void getReviewDetail(selected.job_id, selected.target_type)
      .then((value) => {
        if (detailRequestRevision.current !== revision) return;
        setDetail(value);
        const hasOrdinaryWarning = value.issues.some(
          (item) => !item.resolved && item.severity.toLowerCase() !== 'error',
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
  useEffect(() => {
    const element = reviewMainRef.current;
    if (!selected || !element) {
      setReviewMainHeight(undefined);
      return;
    }
    const updateHeight = () => setReviewMainHeight(Math.ceil(element.getBoundingClientRect().height));
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(element);
    return () => observer.disconnect();
  }, [selected?.job_id, selected?.target_type]);

  const unresolvedIssues = useMemo(() => detail?.issues.filter((item) => !item.resolved) ?? [], [detail]);
  const pendingFieldCount = useMemo(() => detail?.fields.filter((item) => String(item.review_status) === 'pending').length ?? 0, [detail]);
  const pendingNodeCount = useMemo(() => detail?.nodes.filter((item) => String(item.review_status) === 'pending').length ?? 0, [detail]);
  const blockingIssueCount = useMemo(() => detail?.issues.filter((item) => !item.resolved && item.severity.toLowerCase() === 'error').length ?? 0, [detail]);
  const parseCount = processingStatus === 'PENDING' ? (queueCounts.pending_parse ?? 0) : (queueCounts.processed_parse ?? 0);
  const chunkCount = processingStatus === 'PENDING' ? (queueCounts.pending_chunk ?? 0) : (queueCounts.processed_chunk ?? 0);
  const pendingCount = (queueCounts.pending_parse ?? 0) + (queueCounts.pending_chunk ?? 0);
  const processedCount = (queueCounts.processed_parse ?? 0) + (queueCounts.processed_chunk ?? 0);
  const batchNodeIds = useMemo(() => detail?.target_type === 'PARSE_RUN' ? detail.nodes.filter((item) => String(item.review_status) === 'pending').map((item) => item.id) : [], [detail]);
  const batchIssueIds = useMemo(() => detail?.issues.filter((item) => !item.resolved && item.severity.toLowerCase() !== 'error').map((item) => item.id) ?? [], [detail]);
  const reviewNodeTree = useMemo(() => buildReviewNodeTree(detail?.target_type === 'PARSE_RUN' ? detail.nodes : []), [detail]);
  const filteredReviewNodeTree = useMemo(() => filterReviewNodeTree(reviewNodeTree, nodeKeyword), [reviewNodeTree, nodeKeyword]);
  const allReviewNodeKeys = useMemo(() => collectReviewNodeKeys(reviewNodeTree), [reviewNodeTree]);
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
      setProcessingStatus('PROCESSED');
      setReviewState(undefined);
      setPage(1);
    } catch (error) { message.error(error instanceof Error ? error.message : '审核提交失败'); }
  };

  const handleItem = async (target_type: 'issue' | 'field' | 'node' | 'chunk_issue' | 'chunk', target_id: number, action: 'confirm' | 'ignore') => {
    if (!selected) return;
    try {
      await decideReviewItem(selected.job_id, { target_type, target_id, action });
      const value = await getReviewDetail(selected.job_id, selected.target_type);
      setDetail(value);
      setOutcome(value.issues.some((item) => !item.resolved && item.severity.toLowerCase() !== 'error') ? 'PASS_WITH_WARNING' : 'PASS');
      message.success('审核对象已处理');
    } catch (error) { message.error(error instanceof Error ? error.message : '审核对象处理失败'); }
  };

  const handleBatch = async (targetType: 'node' | 'issue' | 'chunk_issue', targetIds: number[], batchAction: 'confirm' | 'ignore', reason?: string) => {
    if (!selected || !targetIds.length) return;
    try {
      await batchReviewItems(selected.job_id, { target_type: targetType, target_ids: targetIds, action: batchAction, comment: reason });
      const value = await getReviewDetail(selected.job_id, selected.target_type);
      setDetail(value);
      setOutcome(value.issues.some((item) => !item.resolved && item.severity.toLowerCase() !== 'error') ? 'PASS_WITH_WARNING' : 'PASS');
      setBatchIssueOpen(false); setBatchComment('');
      message.success(`已批量处理 ${targetIds.length} 项`);
    } catch (error) { message.error(error instanceof Error ? error.message : '批量处理失败'); }
  };

  const openArticleTitleDecision = (node: ReviewDetail['nodes'][number]) => {
    setArticleTitleNode(node);
    setArticleTitleMode('TITLE');
    setArticleTitleValue(node.title ?? '');
    setArticleTitleComment('');
  };

  const submitArticleTitleDecision = async () => {
    if (!selected || !articleTitleNode) return;
    try {
      await decideArticleTitle(selected.job_id, {
        node_id: articleTitleNode.id,
        mode: articleTitleMode,
        title: articleTitleMode === 'TITLE' ? articleTitleValue.trim() : undefined,
        comment: articleTitleComment.trim() || undefined,
      });
      const value = await getReviewDetail(selected.job_id, selected.target_type);
      setDetail(value);
      setOutcome(value.issues.some((item) => !item.resolved && item.severity.toLowerCase() !== 'error') ? 'PASS_WITH_WARNING' : 'PASS');
      setArticleTitleNode(null);
      message.success(articleTitleMode === 'TITLE' ? '条标题已确认' : '已恢复为条文正文');
    } catch (error) { message.error(error instanceof Error ? error.message : '条标题审核失败'); }
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
    <div className="review-node-tree-panel">
      <div className="review-node-tree-toolbar">
        <Input.Search
          allowClear
          value={nodeKeyword}
          placeholder="搜索章节、条款或正文内容"
          onChange={(event) => {
            const value = event.target.value;
            setNodeKeyword(value);
            if (value.trim()) setExpandedNodeKeys(allReviewNodeKeys);
          }}
        />
        <Space size={6}>
          <Button size="small" onClick={() => setExpandedNodeKeys(allReviewNodeKeys)}>全部展开</Button>
          <Button size="small" onClick={() => setExpandedNodeKeys([])}>全部收起</Button>
        </Space>
      </div>
      {filteredReviewNodeTree.length ? (
        <Tree<ReviewNodeTreeData>
          blockNode
          showLine
          treeData={filteredReviewNodeTree}
          expandedKeys={expandedNodeKeys}
          selectedKeys={selectedNodeKey == null ? [] : [selectedNodeKey]}
          onExpand={(keys) => setExpandedNodeKeys(keys)}
          onSelect={(_, info) => {
            const item = info.node.reviewNode;
            setSelectedNodeKey(info.node.key);
            setSelectedContent(item.text || item.title || '');
            setSelectedSourcePage(item.page_start);
          }}
          titleRender={(item) => {
            const node = item.reviewNode;
            const review = nodeReviewLabel[String(node.review_status)] ?? { text: String(node.review_status), color: 'default' };
            const isPending = String(node.review_status) === 'pending';
            const isTitleDecision = String(node.rule_id) === 'NODE_ARTICLE_TITLE_HEURISTIC_V2';
            const isApprovedRun = String(detail.run.review_status) === 'approved';
            return (
              <div className="review-node-tree-title">
                <div className="review-node-tree-main">
                  <Space size={6} wrap>
                    <Tag>{node.node_type}</Tag>
                    <strong>{item.title}</strong>
                    <Tag color={review.color}>{review.text}</Tag>
                    {item.descendantCount > 0 && <Typography.Text type="secondary">（{item.descendantCount}）</Typography.Text>}
                  </Space>
                  <small>第 {node.page_start ?? '-'}—{node.page_end ?? node.page_start ?? '-'} 页 · Node {node.id}{node.review_reason ? ` · ${node.review_reason}` : ''}</small>
                </div>
                <Space size={2} className="review-node-tree-actions">
                  {isPending && isTitleDecision ? <>
                    <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); void handleItem('node', node.id, 'confirm'); }}>确认条标题</Button>
                    <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); openArticleTitleDecision(node); }}>调整判断</Button>
                  </> : null}
                  {isPending && !isTitleDecision ? <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); void handleItem('node', node.id, 'confirm'); }}>确认结构</Button> : null}
                  {!isPending && isApprovedRun ? <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); openCorrection(node); }}>派生修正</Button> : null}
                </Space>
              </div>
            );
          }}
        />
      ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的解析节点" />}
    </div>
  ) : (
    <List dataSource={detail?.chunks ?? []} renderItem={(chunk) => (
      <List.Item className="review-content-row" onClick={() => { setSelectedContent(chunk.retrieval_text); setSelectedSourcePage(chunk.page_start); }}>
        <div><Tag color={chunk.is_retrievable ? 'blue' : 'default'}>{chunkTypeLabel[chunk.chunk_type] ?? chunk.chunk_type}</Tag><strong>{chunk.path_text || chunk.chunk_key}</strong></div>
        <small>{chunk.char_count} 字 · {chunk.token_count ?? '-'} tokens · 来源Node {chunk.sources.length}</small>
      </List.Item>
    )} />
  );

  const statusOptions = processingStatus === 'PENDING'
    ? [
        { label: '全部状态', value: '' },
        { label: '有待处理项', value: 'ACTION_REQUIRED' },
        { label: '可提交审核', value: 'READY_TO_SUBMIT' },
      ]
    : [
        { label: '全部状态', value: '' },
        { label: '已通过', value: 'PASS' },
        { label: '警告通过', value: 'PASS_WITH_WARNING' },
        { label: '已驳回', value: 'REJECT' },
        { label: '运行失败', value: 'FAILED' },
      ];

  const queuePanel = (
    <Card
      className="review-queue"
      title="运行与历史"
      variant="borderless"
      style={reviewMainHeight == null ? undefined : { height: reviewMainHeight }}
    >
      <Input.Search
        allowClear
        value={keywordInput}
        placeholder="搜索制度名称 / 文号 / 运行ID"
        onChange={(event) => {
          setKeywordInput(event.target.value);
          if (!event.target.value) { setKeyword(''); setPage(1); }
        }}
        onSearch={(value) => { setKeyword(value.trim()); setPage(1); }}
      />
      <Segmented
        block
        value={processingStatus}
        options={[{ label: `待处理 ${pendingCount}`, value: 'PENDING' }, { label: `已处理 ${processedCount}`, value: 'PROCESSED' }]}
        onChange={(value) => { setProcessingStatus(value as 'PENDING' | 'PROCESSED'); setReviewState(undefined); setPage(1); }}
      />
      <Segmented
        block
        className="review-type-switch"
        value={runType}
        options={[{ label: `解析 ${parseCount}`, value: 'PARSE_RUN' }, { label: `分块 ${chunkCount}`, value: 'CHUNK_RUN' }]}
        onChange={(value) => { setRunType(value as 'PARSE_RUN' | 'CHUNK_RUN'); setPage(1); }}
      />
      <div className="review-queue-filters">
        <Select value={reviewState ?? ''} options={statusOptions} onChange={(value) => { setReviewState(value || undefined); setPage(1); }} />
        <Select value={sortBy} options={[
          { label: '最近更新', value: 'UPDATED_DESC' },
          { label: processingStatus === 'PENDING' ? '最早待处理' : '最早更新', value: 'OLDEST_PENDING' },
          { label: '制度名称', value: 'TITLE_ASC' },
        ]} onChange={(value) => { setSortBy(value); setPage(1); }} />
      </div>
      <Typography.Text className="review-queue-total" type="secondary">共 {total} 条</Typography.Text>
      <Spin spinning={queueLoading}>
        <List
          dataSource={items}
          locale={{ emptyText: `暂无${processingStatus === 'PENDING' ? '待处理' : '已处理'}${runTypeLabel[runType]}` }}
          renderItem={(item) => {
            const display = displayStateLabel[item.display_state] ?? { text: item.display_state, color: 'default' };
            return (
              <button type="button" className={`review-queue-item${selected?.job_id === item.job_id && selected.target_type === item.target_type ? ' active' : ''}`} onClick={() => setSelected(item)}>
                <strong title={item.title}>{item.title}</strong>
                {item.document_code && <small>{item.document_code}</small>}
                <span><Tag>{runTypeLabel[item.target_type]}</Tag>运行 {item.target_id} · <Tag color={display.color}>{display.text}</Tag></span>
                <small>{new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false })}</small>
              </button>
            );
          }}
        />
      </Spin>
      {total > 0 && <Pagination size="small" current={page} pageSize={10} total={total} showSizeChanger={false} onChange={setPage} />}
    </Card>
  );

  return (
    <div className="admin-page review-page">
      <div className="admin-page-title"><div><Typography.Title level={2}>ParseRun / ChunkRun 审核工作台</Typography.Title><Typography.Text type="secondary">直接审核真实结构、字段、页码、Chunk来源和质量问题</Typography.Text></div><Tag color="blue">当前结果 {total}</Tag></div>
      {nextNotice && <Alert showIcon type="info" message={nextNotice.kind === 'METADATA_WAIT' ? '下一步：确认制度元数据' : '下一步：构建索引快照'} description={nextNotice.kind === 'METADATA_WAIT' ? `解析识别出的 ${pendingFieldCount} 个字段候选将在统一元数据页面核对；确认通过后Worker才生成ChunkRun。` : '该制度已进入“可纳入索引”，管理员可与其他制度变更合并为一次全局IndexRun。'} action={<Space><Button size="small" icon={<UiIcon icon={ReloadOutlined} />} onClick={() => void refresh()}>刷新运行</Button><Button size="small" type="primary" icon={<UiIcon icon={ArrowRightOutlined} />} onClick={() => navigate('/admin/knowledge')}>制度治理</Button></Space>} />}
      {!selected ? <div className="review-workbench">{queuePanel}<Card className="review-main" variant="borderless"><Empty image={<UiIcon icon={FileSearchOutlined} />} description="当前筛选条件下没有审核运行" /></Card></div> : (
        <div className="review-workbench">
          {queuePanel}
          <div ref={reviewMainRef} className="review-main-column">
            <Card
              className="review-main"
              variant="borderless"
              title={`${runTypeLabel[selected.target_type]}审核`}
              extra={detail?.pdf_available ? (
                <Button
                  type="link"
                  icon={<UiIcon icon={FileTextOutlined} />}
                  href={reviewSourceUrl(selected.job_id, selectedSourcePage)}
                  target="_blank"
                  rel="noreferrer"
                >
                  查看原文
                </Button>
              ) : null}
            >
              <Spin spinning={detailLoading}>
                {detail && <>
                <div className="review-document-meta"><Typography.Title level={4}>{String(detail.run.document_title ?? selected.title)}</Typography.Title><Space wrap><Tag color="blue">{stateLabel[selected.state] ?? selected.state}</Tag><span>制度ID：{selected.document_id}</span><span>审核状态：{String(detail.run.review_status ?? '-')}</span>{detail.run.render_engine && <span>渲染引擎：{detail.run.render_engine}</span>}</Space></div>
                <div className="review-metrics">{Object.entries(detail.metrics).filter(([, value]) => typeof value !== 'object').map(([key, value]) => <div key={key}><small>{metricLabel[key] ?? key}</small><strong>{renderMetric(key, value)}</strong></div>)}</div>
                {selected.processing_status === 'PENDING' && (batchNodeIds.length > 0 || batchIssueIds.length > 0) && <Alert showIcon type="info" message="当前运行可批量处理" description={batchNodeIds.length > 0 ? `有 ${batchNodeIds.length} 个节点待确认。批量操作仅作用于当前运行。` : `节点已经全部确认，当前剩余 ${batchIssueIds.length} 个普通警告；阻断问题不会进入批量接受。`} action={<Space>{batchNodeIds.length > 0 && <Popconfirm title={`确认当前运行全部 ${batchNodeIds.length} 个待确认节点？`} onConfirm={() => void handleBatch('node', batchNodeIds, 'confirm')}><Button size="small" type="primary">批量确认节点</Button></Popconfirm>}{batchIssueIds.length > 0 && <Button size="small" type="primary" onClick={() => { setActiveTab('issues'); setBatchIssueOpen(true); }}>批量接受普通警告</Button>}</Space>} />}
                <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
                  { key: 'content', label: detail.target_type === 'PARSE_RUN' ? `节点树（${detail.nodes.length}）` : `Chunk（${detail.chunks.length}）`, children: contentTab },
                  { key: 'fields', label: `字段候选（${detail.fields.length}）`, children: <List dataSource={detail.fields} locale={{ emptyText: '本运行无字段候选' }} renderItem={(field) => <List.Item><Space direction="vertical" size={0}><Space><strong>{fieldLabel[field.field_name] ?? field.field_name}</strong><Tag color="blue">供元数据页核对</Tag></Space><span>{field.normalized_value || field.raw_value}</span><small>置信度 {(field.confidence * 100).toFixed(1)}%</small></Space></List.Item>} /> },
                  { key: 'issues', label: `问题（${detail.issues.length}）`, children: <><Space style={{ marginBottom: 12 }}>{batchIssueIds.length > 0 && selected.processing_status === 'PENDING' && <Button onClick={() => setBatchIssueOpen(true)}>批量接受全部普通警告（{batchIssueIds.length}）</Button>}</Space><List dataSource={detail.issues} locale={{ emptyText: '未发现质量问题' }} renderItem={(issue) => <List.Item actions={!issue.resolved && issue.severity.toLowerCase() !== 'error' ? [<Button key="ignore" type="link" onClick={() => void handleItem(detail.target_type === 'PARSE_RUN' ? 'issue' : 'chunk_issue', issue.id, 'ignore')}>确认并接受</Button>] : undefined}><Space direction="vertical" size={2}><Space><Tag color={issue.severity.toLowerCase() === 'error' ? 'red' : 'orange'}>{issue.severity.toLowerCase() === 'error' ? '阻断问题' : '普通警告'}</Tag><Tag>{issue.issue_type}</Tag><strong>{issue.issue_code}</strong>{issue.resolved && <Tag color="green">已处理</Tag>}</Space><span>{issue.message}</span></Space></List.Item>} /></> },
                  ...(detail.pdf_available ? [{ key: 'pdf', label: `PDF（${detail.run.page_count ?? '-'}页）`, children: <iframe className="review-pdf" title="ParseRun PDF" src={reviewPdfUrl(selected.job_id)} /> }] : []),
                ]} />
                {selectedContent && <Card size="small" title="当前选中内容" className="review-selected-content"><Typography.Paragraph>{selectedContent}</Typography.Paragraph></Card>}
                {((selected.target_type === 'PARSE_RUN' && selected.state === 'PARSE_REVIEW') || (selected.target_type === 'CHUNK_RUN' && selected.state === 'CHUNK_REVIEW')) ? <div className="review-decision">{approvalBlocked && <Alert showIcon type="warning" message="暂不能通过" description={blockingIssueCount > 0 ? `还有 ${blockingIssueCount} 个阻断问题待处理。` : `还有 ${pendingNodeCount} 个结构节点待确认，请先在上方页签逐项处理。元数据字段将在下一节点统一确认。`} />}<Radio.Group value={outcome} onChange={(event) => setOutcome(event.target.value)}><Radio.Button value="PASS"><UiIcon icon={CheckCircleOutlined} /> 通过</Radio.Button><Radio.Button value="PASS_WITH_WARNING"><UiIcon icon={WarningOutlined} /> 警告通过</Radio.Button><Radio.Button value="REJECT"><UiIcon icon={CloseCircleOutlined} /> 驳回</Radio.Button></Radio.Group><Input.TextArea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder={outcome === 'PASS_WITH_WARNING' ? '请逐项说明接受警告的理由' : outcome === 'REJECT' ? '必须填写驳回原因' : '可填写审核意见'} /><Button type="primary" disabled={approvalBlocked} onClick={() => void submit()}>提交审核结果</Button></div> : <div className="review-history-notice"><Tag color="green">只读历史</Tag><Typography.Text type="secondary">该运行已完成审核，当前详情不可修改。</Typography.Text></div>}
                </>}
              </Spin>
            </Card>
          </div>
          <Card
            className="review-quality"
            title="质量检查"
            variant="borderless"
            style={reviewMainHeight == null ? undefined : ({ '--review-main-height': `${reviewMainHeight}px` } as CSSProperties)}
          >
            {detail ? <><div className="quality-list">{Object.entries(detail.metrics).filter(([, value]) => typeof value !== 'object').map(([key, value]) => <div className="quality-line" key={key}><span>{metricLabel[key] ?? key}</span><strong>{renderMetric(key, value)}</strong></div>)}</div><div className="quality-summary"><Tag color={unresolvedIssues.length ? 'orange' : 'green'}>{unresolvedIssues.length ? `${unresolvedIssues.length} 个未处理问题` : '检查通过'}</Tag></div></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Card>
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
      <Modal title="批量接受普通警告" open={batchIssueOpen} okText="确认批量接受" okButtonProps={{ disabled: !batchComment.trim() }} onCancel={() => { setBatchIssueOpen(false); setBatchComment(''); }} onOk={() => void handleBatch(detail?.target_type === 'PARSE_RUN' ? 'issue' : 'chunk_issue', batchIssueIds, 'ignore', batchComment)}>
        <Alert showIcon type="warning" message={`将接受当前运行中的 ${batchIssueIds.length} 个普通警告`} description="阻断级问题不会进入批量操作。请填写统一接受理由，审核记录将逐项留痕。" />
        <Input.TextArea style={{ marginTop: 16 }} rows={4} value={batchComment} onChange={(event) => setBatchComment(event.target.value)} placeholder="必填：说明接受这些普通警告的依据" />
      </Modal>
      <Modal title="条标题人工确认" open={Boolean(articleTitleNode)} okText="保存审核结论" okButtonProps={{ disabled: articleTitleMode === 'TITLE' && !articleTitleValue.trim() }} onCancel={() => setArticleTitleNode(null)} onOk={() => void submitArticleTitleDecision()}>
        <Alert showIcon type="info" message="请选择这段文字的真实结构" description="确认或调整标题会同步重算后代节点路径；改为条文正文时将从原始节点文字恢复正文，不改写制度原文。" />
        <Radio.Group style={{ marginTop: 16 }} value={articleTitleMode} onChange={(event) => setArticleTitleMode(event.target.value)}>
          <Radio.Button value="TITLE">作为条标题</Radio.Button>
          <Radio.Button value="CONTENT">作为条文正文</Radio.Button>
        </Radio.Group>
        {articleTitleMode === 'TITLE' && <Input style={{ marginTop: 16 }} value={articleTitleValue} onChange={(event) => setArticleTitleValue(event.target.value)} placeholder="条标题" />}
        <Input.TextArea style={{ marginTop: 16 }} rows={3} value={articleTitleComment} onChange={(event) => setArticleTitleComment(event.target.value)} placeholder="可填写判断依据" />
      </Modal>
    </div>
  );
}
