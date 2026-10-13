/** 文件说明：轻量个人自测配置、生成进度、答题及原文解析；不提供考试管理功能。 */
import { Alert, Button, Card, Checkbox, Empty, Input, InputNumber, message, Modal, Pagination, Progress, Radio, Segmented, Space, Spin, Switch, Tag, TreeSelect, Typography } from 'antd';
import { BookOutlined, CheckCircleOutlined, FileTextOutlined, LeftOutlined, RightOutlined, SettingOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { createLearning, getLearning, saveLearning, submitLearning, useFeatures, type LearningState } from '../api/learning';
import { getDocument, getDocumentNodes, listDocuments } from '../api/documents';
import type { DocumentNode, DocumentSummary } from '../types/documents';
import '../styles/learning-assessment.css';
import { UiIcon } from '../components/UiIcon';
import { MaterialRecommendations } from '../components/MaterialRecommendations';
import { resolveLearningNavigation, visibleQuestionIndices } from './learningAssessmentView';

const names = { SINGLE: '单选题', MULTIPLE: '多选题', TRUE_FALSE: '判断题' };
const DEFAULT_PAGE_SIZE = 10;
/** 未渲染出条目前对单条制度高度的估算（含 10px 间距）。 */
const ESTIMATED_ITEM_HEIGHT = 100;
/** 列表上下外边距之和（与 .learning-document-list 的 margin 对应）。 */
const LIST_MARGIN = 24;
/** 窄屏无固定容器时，列表下方分页条、卡片内边距及页面底部留白之和。 */
const LIST_BOTTOM_RESERVE = 110;
/** 根据列表可用高度计算每页条数；桌面端列表在固定高度的滚动容器内，直接量容器；窄屏退回按视口计算。 */
function fitPageSize(list: HTMLElement): number {
  const items = Array.from(list.querySelectorAll<HTMLElement>('.learning-document-option'));
  const itemHeight = items.length ? items.reduce((sum, item) => sum + item.getBoundingClientRect().height, 0) / items.length + 10 : ESTIMATED_ITEM_HEIGHT;
  const scroller = list.closest<HTMLElement>('.ant-spin-nested-loading');
  const scrollable = scroller && getComputedStyle(scroller).overflowY === 'auto';
  const available = scrollable ? scroller.clientHeight - LIST_MARGIN : window.innerHeight - list.getBoundingClientRect().top - LIST_BOTTOM_RESERVE;
  return Math.max(3, Math.min(30, Math.floor(available / itemHeight)));
}
function newRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const h = Array.from(bytes, x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
function scopeTree(nodes: DocumentNode[]): { value: number; title: string; children: ReturnType<typeof scopeTree> }[] {
  const eligible = nodes.filter(n => ['chapter', 'article'].includes(n.node_type));
  const selected = new Set(eligible.map(n => n.id));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const parent = (n: DocumentNode) => {
    let id = n.parent_id; const seen = new Set<number>();
    while (id != null && !selected.has(id) && !seen.has(id)) { seen.add(id); id = byId.get(id)?.parent_id ?? null; } return id;
  };
  const build = (id: number | null): ReturnType<typeof scopeTree> => eligible.filter(n => parent(n) === id).map(n => ({ value: n.id, title: [n.node_number, n.title].filter(Boolean).join(' ') || `条款 ${n.id}`, children: build(n.id) }));
  return build(null);
}

export function LearningAssessmentPage() {
  const features = useFeatures();
  const [params] = useSearchParams();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [total, setTotal] = useState(0); const [page, setPage] = useState(1); const [keyword, setKeyword] = useState('');
  // 制度列表每页条数随视口高度自适应，尽量让一页在不滚动的情况下完整显示。
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const pageSizeRef = useRef(DEFAULT_PAGE_SIZE);
  const listRef = useRef<HTMLDivElement>(null); const measuredWithItems = useRef(false);
  const [documentId, setDocumentId] = useState<number | null>(Number(params.get('document_id')) || null);
  const [selectedDocument, setSelectedDocument] = useState<DocumentSummary | null>(null); const [nodes, setNodes] = useState<DocumentNode[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [view, setView] = useState<'config' | 'answer'>('config');
  const [questionIndex, setQuestionIndex] = useState(0);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const pendingTask = useRef<string | null>(null);
  const [scope, setScope] = useState<'FULL' | 'SELECTED'>('FULL'); const [selectedNodes, setSelectedNodes] = useState<number[]>([]);
  const [counts, setCounts] = useState({ single: 5, multiple: 3, true_false: 2 });
  const [state, setState] = useState<LearningState>({ task: null, assessment: null });
  const [answers, setAnswers] = useState<Record<string, number[]>>({});
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [onlyWrong, setOnlyWrong] = useState(false);
  const loaded = useRef(''); const requestId = useRef<string | null>(null);
  const enabled = features?.learning_assessment;
  const count = counts.single + counts.multiple + counts.true_false;
  const current = state.assessment;
  const generating = state.task?.status === 'GENERATING';
  const submitted = current?.status === 'SUBMITTED';
  const notifyError = (e: unknown) => message.error(e instanceof Error ? String(e.message) : '操作失败');

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setDocumentsLoading(true);
    listDocuments({ query_scope: 'CURRENT', keyword, page, page_size: pageSize }).then(v => { if (alive) { setDocuments(v.items); setTotal(v.total); } }).catch(e => { if (alive) notifyError(e); }).finally(() => { if (alive) setDocumentsLoading(false); });
    return () => { alive = false; };
  }, [enabled, keyword, page, pageSize]);
  useEffect(() => {
    // 首次挂载按估算高度定页容量；条目真正渲染后再用实测高度校正一次；之后只在窗口尺寸变化时重算，避免翻页时反复抖动。
    if (!enabled || view !== 'config') return;
    const measure = () => {
      if (!listRef.current) return;
      const next = fitPageSize(listRef.current);
      if (next !== pageSizeRef.current) { pageSizeRef.current = next; setPageSize(next); setPage(1); }
    };
    if (!measuredWithItems.current) {
      measure();
      if (documents.length) measuredWithItems.current = true;
    }
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [enabled, view, documents]);
  useEffect(() => {
    setNodes([]); setSelectedNodes([]); setSelectedDocument(null); requestId.current = null;
    if (!enabled || !documentId) return;
    let alive = true;
    Promise.all([getDocument(String(documentId)), getDocumentNodes(String(documentId))]).then(([doc, result]) => {
      if (alive) { setNodes(result.items); setSelectedDocument(doc); }
    }).catch(notifyError);
    return () => { alive = false; };
  }, [enabled, documentId]);
  useEffect(() => {
    if (!enabled) return;
    let alive = true; let timer: number;
    const poll = async () => {
      try { const value = await getLearning(); if (alive) { setState(value); setError(''); } }
      catch (e) { if (alive) setError(e instanceof Error ? String(e.message) : '读取检测失败'); }
      if (alive) timer = window.setTimeout(() => { void poll(); }, 4000);
    };
    void poll(); return () => { alive = false; window.clearTimeout(timer); };
  }, [enabled]);
  useEffect(() => {
    const key = current ? `${current.assessment_id}:${current.status}` : '';
    if (key !== loaded.current) { setAnswers(current?.user_answers ?? {}); loaded.current = key; setOnlyWrong(false); setQuestionIndex(0); setEvidenceOpen(false); }
  }, [current]);
  useEffect(() => {
    // 只响应本页观察到的生成任务；旧检测轮询不会反复把用户拉回答题页。
    const navigation = resolveLearningNavigation(state, pendingTask.current);
    pendingTask.current = navigation.pendingTaskId;
    if (navigation.openAnswer) setView('answer');
  }, [state]);

  async function start() {
    if (!documentId || count < 1 || count > (features?.learning_max_questions ?? 15) || (scope === 'SELECTED' && !selectedNodes.length)) {
      void message.warning('请选择制度、有效范围，并将总题量设置在1—15题以内'); return;
    }
    setBusy(true);
    try {
      requestId.current ??= newRequestId();
      await createLearning({ document_id: documentId, request_id: requestId.current, scope, node_ids: scope === 'FULL' ? [] : selectedNodes, ...counts });
      const value = await getLearning();
      pendingTask.current = value.task?.task_id ?? null;
      setState(value); requestId.current = null;
    } catch (e) { notifyError(e); } finally { setBusy(false); }
  }
  async function submit() {
    if (!current) return;
    setBusy(true);
    try { await submitLearning(current.assessment_id, answers); setState(await getLearning()); setView('answer'); }
    catch (e) { notifyError(e); } finally { setBusy(false); }
  }
  const answered = current?.questions.filter(q => answers[q.question_id]?.length).length ?? 0;
  const questionTotal = current?.questions.length ?? 0;
  const indices = visibleQuestionIndices(state, onlyWrong);
  const activeIndex = indices.includes(questionIndex) ? questionIndex : (indices[0] ?? -1);
  const question = current?.questions[activeIndex];
  const detail = current?.result?.details.find(d => d.question_id === question?.question_id);
  const position = indices.indexOf(activeIndex);
  const questionCounts = current?.questions.reduce((value, q) => ({ ...value, [q.question_type]: value[q.question_type] + 1 }), { SINGLE: 0, MULTIPLE: 0, TRUE_FALSE: 0 });
  const chooseQuestion = (index: number) => {
    setQuestionIndex(index); setEvidenceOpen(false);
    // 窄屏导航位于题目下方，切题后让题干重新进入视口。
    window.requestAnimationFrame(() => document.getElementById('learning-active-question')?.scrollIntoView({ block: 'nearest' }));
  };
  const confirmSubmit = () => Modal.confirm({
    title: '确认提交本次检测？',
    content: '还有' + (questionTotal - answered) + '题未答。提交后冻结结果，不可修改。',
    onOk: submit,
  });
  const save = async () => {
    if (!current) return;
    setBusy(true);
    try { await saveLearning(current.assessment_id, answers); void message.success('本次作答已暂存'); }
    catch (e) { notifyError(e); } finally { setBusy(false); }
  };
  if (!features) return <Spin />;
  if (!enabled) return <Empty description="学习检测未启用或当前不可用" />;
  return <div className="page-stack learning-page learning-workspace">
    <header className="learning-heading">
      <div><Typography.Title level={2}>学习检测</Typography.Title>
        <Typography.Text type="secondary">{view === 'config' ? '选择制度与出题范围，快速生成个人学习自测题目' : '通过答题检验对制度内容的掌握情况，巩固学习效果'}</Typography.Text></div>
      <Segmented aria-label="学习检测页面切换" value={view} onChange={value => setView(value as 'config' | 'answer')}
        options={[{ label: '检测配置', value: 'config', icon: <UiIcon icon={SettingOutlined} /> }, { label: '答题与结果', value: 'answer', icon: <UiIcon icon={BookOutlined} /> }]} />
    </header>
    {error && <Alert type="error" showIcon message={error} />}
    {/* 生成中的进度已在右侧“题目生成进度”区展示，顶部只保留失败等需要用户注意的任务提示。 */}
    {state.task && state.task.status !== 'READY' && !generating && <Alert className="learning-task-notice" showIcon
      type={state.task.status === 'FAILED' ? 'warning' : 'success'}
      message={state.task.error || state.task.progress || '检测任务已更新'} />}
    {view === 'config' ? <div className="learning-setup-layout">
      <Card className="learning-document-card" title={<Space><UiIcon icon={FileTextOutlined} />制度选择</Space>} bordered={false}
        extra={<Tag color="blue">现行有效 · 已发布</Tag>}>
        <div className="learning-list-heading"><span>可选制度 <strong>{total}</strong></span><Typography.Text type="secondary">选择一份制度开始检测</Typography.Text></div>
        <Input.Search aria-label="搜索制度" placeholder="搜索制度名称 / 文号 / 关键词" allowClear
          onSearch={value => { setKeyword(value); setPage(1); }} />
        <Spin spinning={documentsLoading}>
          <div ref={listRef}>
            {documents.length ? <Radio.Group className="learning-document-list" value={documentId} onChange={e => setDocumentId(e.target.value)}>
              {documents.map(doc => <Radio key={doc.id} value={doc.id} className={'learning-document-option' + (documentId === doc.id ? ' is-selected' : '')}>
                <div className="learning-document-title"><strong>{doc.title}</strong><Tag className="document-status-tag document-status-current">现行有效</Tag></div>
                <div className="learning-document-meta"><span>文号：{doc.document_code || '未登记'}</span><span>发布机构：{doc.issuer || '未登记'}</span><span>发布日期：{doc.publish_date || '未登记'}</span></div>
              </Radio>)}
            </Radio.Group> : <Empty className="learning-empty" description={keyword ? '未找到匹配的现行有效制度' : '暂无可用的现行有效制度'} />}
          </div>
        </Spin>
        <Pagination size="small" current={page} total={total} pageSize={pageSize} showSizeChanger={false}
          showTotal={value => '共 ' + value + ' 条'} onChange={setPage} />
      </Card>
      <Card className="learning-settings-card" bordered={false} title={<Space><UiIcon icon={SettingOutlined} />检测配置</Space>}
        extra={state.task?.status === 'READY' ? <Tag className="learning-generated-tag">题目已生成</Tag> : undefined}>
        {selectedDocument ? <div className="learning-selected-document">
          <UiIcon icon={FileTextOutlined} /><div><strong>{selectedDocument.title}</strong>
            <div>文号：{selectedDocument.document_code || '未登记'}</div>
            <div>发布机构：{selectedDocument.issuer || '未登记'}</div><div>发布日期：{selectedDocument.publish_date || '未登记'}</div></div>
        </div> : <div className="learning-selection-placeholder"><UiIcon icon={FileTextOutlined} /><span>{documentId ? '正在读取制度详情…' : '请从左侧选择制度'}</span></div>}
        <section className="learning-config-section">
          <h3><UiIcon icon={BookOutlined} /> 出题范围</h3>
          <Radio.Group disabled={!selectedDocument} value={scope} onChange={e => { setScope(e.target.value); requestId.current = null; }}
            options={[{ label: '全文抽样', value: 'FULL' }, { label: '指定章节／条款', value: 'SELECTED' }]} />
          {scope === 'SELECTED' && <div className="learning-scope-picker">
            <Typography.Text type="secondary">已选择 {selectedNodes.length} 个范围节点</Typography.Text>
            <TreeSelect className="full-width" treeCheckable disabled={!selectedDocument} value={selectedNodes} treeData={scopeTree(nodes)}
              maxTagCount={2} maxTagTextLength={10} maxTagPlaceholder={omitted => '+' + omitted.length} placeholder="选择章节或条款" aria-label="选择出题章节或条款"
              onChange={value => { setSelectedNodes(value); requestId.current = null; }} />
          </div>}
        </section>
        <section className="learning-config-section">
          <h3><UiIcon icon={SettingOutlined} /> 题量设置 <small>总题数 = 单选 + 多选 + 判断</small></h3>
          <div className="learning-count-grid">
            <label>总题数<InputNumber aria-label="总题数" precision={0} min={1} max={features.learning_max_questions} value={count}
              onChange={value => { const n = value ?? 1; const single = Math.ceil(n / 2); const multiple = Math.floor(n * .3); setCounts({ single, multiple, true_false: n - single - multiple }); requestId.current = null; }} /></label>
            {(['single', 'multiple', 'true_false'] as const).map((key, i) => <label key={key}>{['单选题', '多选题', '判断题'][i]}
              <InputNumber aria-label={['单选题数量', '多选题数量', '判断题数量'][i]} precision={0} min={0} max={features.learning_max_questions} value={counts[key]}
                onChange={value => { setCounts(previous => ({ ...previous, [key]: value ?? 0 })); requestId.current = null; }} /></label>)}
          </div>
          {(count < 1 || count > features.learning_max_questions) && <Typography.Text type="danger">总题数应为1—{features.learning_max_questions}题，请调整各题型数量。</Typography.Text>}
        </section>
        <div className="learning-guidance"><div><UiIcon icon={CheckCircleOutlined} /> 最多{features.learning_max_questions}题，保留{features.learning_ttl_hours}小时，仅作学习辅助</div>
          <div><UiIcon icon={CheckCircleOutlined} /> 生成成功才替换旧检测，失败保留旧结果</div>
          <div>全文为抽样检测，不保证覆盖每条；以制度原文为准，不作正式考核依据。</div></div>
        <Space direction="vertical" className="full-width">
          <Button block type="primary" icon={<UiIcon icon={FileTextOutlined} />} loading={busy || generating}
            disabled={!selectedDocument || !nodes.length || count < 1 || count > features.learning_max_questions || (scope === 'SELECTED' && !selectedNodes.length)}
            onClick={() => {
              if (current) Modal.confirm({ title: '生成成功后将覆盖当前检测', content: '当前题目、作答及结果届时不再保留。是否继续？', onOk: start }); else void start();
            }}>生成检测题目</Button>
          <div className="learning-recent-progress">
            <div className="learning-recent-heading"><span>{generating ? '题目生成进度' : '最近一次检测'}</span>
              <Button type="text" size="small" disabled={!current} onClick={() => setView('answer')}>{submitted ? '查看结果' : '继续答题'} <UiIcon icon={RightOutlined} /></Button></div>
            {generating ? <><div className="learning-indeterminate" role="status" aria-label="题目正在生成"><span /></div><small>{state.task?.progress || '等待生成'} · 完成后自动进入答题</small></>
              : <><Progress percent={questionTotal ? Math.round(answered * 100 / questionTotal) : 0} showInfo={false} strokeWidth={5} />
                <small>{current ? (submitted ? '检测已提交 · ' : '已作答 ') + answered + ' / ' + questionTotal + ' 题' : '暂无检测，生成题目后可在此查看进度'}</small></>}
          </div>
        </Space>
      </Card>
    </div> : current ? <div className="learning-answer-layout">
      <main className="learning-main-column">
        <Card bordered={false} className="learning-assessment-banner">
          <div className="learning-banner-content"><div className="learning-file-icon"><UiIcon icon={FileTextOutlined} /></div>
            <div className="learning-banner-text"><h3>{current.document_title}</h3>
              <div className="learning-document-meta"><span>来源：制度库</span><span>题目数量：{questionTotal}题</span>
                <span>单选{questionCounts?.SINGLE}题 · 多选{questionCounts?.MULTIPLE}题 · 判断{questionCounts?.TRUE_FALSE}题</span></div>
              <div className="learning-snapshot">IndexRun {current.index_run_id} · ParseRun {current.parse_run_id} · 有效至 {new Date(current.expires_at).toLocaleString()}</div>
            </div><Tag color={submitted ? 'green' : 'blue'}>{submitted ? '已完成' : '答题中'}</Tag></div>
          {current.version_changed && <Alert type="warning" showIcon message="制度正文已有新版本，本次仍按生成时原文评分" />}
        </Card>
        {question ? <Card bordered={false} className="learning-question-card">
          <div className="learning-question-toolbar"><Space wrap><Tag color="blue">{names[question.question_type]}</Tag><strong>第 {activeIndex + 1} 题 / 共 {questionTotal} 题</strong>
            <Tag color={submitted ? (detail?.correct ? 'green' : 'orange') : (answers[question.question_id]?.length ? 'blue' : 'default')}>
              {submitted ? (detail?.correct ? '正确' : detail?.unanswered ? '未答' : '错误') : (answers[question.question_id]?.length ? '已作答' : '未作答')}</Tag></Space>
          </div>
          <h2 id="learning-active-question" className="learning-question-stem">{question.question}</h2>
          {question.question_type === 'MULTIPLE' && <Typography.Paragraph type="secondary">多选题：请选出全部正确选项，少选、多选或错选均不得分。</Typography.Paragraph>}
          <div className="learning-answer-options">
            {question.question_type === 'MULTIPLE' ? <Checkbox.Group disabled={submitted || busy} value={answers[question.question_id] ?? []}
              onChange={value => setAnswers(a => ({ ...a, [question.question_id]: value as number[] }))}>
              {question.options.map((text, index) => <Checkbox key={index} value={index} className={submitted ? (question.correct_answer?.includes(index) ? 'is-correct-option' : answers[question.question_id]?.includes(index) ? 'is-wrong-option' : '') : answers[question.question_id]?.includes(index) ? 'is-chosen' : ''}><span>{String.fromCharCode(65 + index)}.</span> {text}</Checkbox>)}
            </Checkbox.Group> : <Radio.Group disabled={submitted || busy} value={answers[question.question_id]?.[0]}
              onChange={e => setAnswers(a => ({ ...a, [question.question_id]: [e.target.value] }))}>
              {question.options.map((text, index) => <Radio key={index} value={index} className={submitted ? (question.correct_answer?.includes(index) ? 'is-correct-option' : answers[question.question_id]?.includes(index) ? 'is-wrong-option' : '') : answers[question.question_id]?.includes(index) ? 'is-chosen' : ''}>
                {question.question_type !== 'TRUE_FALSE' && <span>{String.fromCharCode(65 + index)}. </span>}{text}</Radio>)}
            </Radio.Group>}
          </div>
          {submitted && <div className="learning-explanation">
            <Typography.Paragraph><strong>正确答案：</strong>{question.correct_answer?.map(index => question.options[index]).join('；')}</Typography.Paragraph>
            <Typography.Paragraph><strong>答案解析：</strong>{question.explanation}</Typography.Paragraph>
            <Typography.Text type="secondary">知识点：{question.knowledge_point}</Typography.Text>
          </div>}
          <footer className="learning-question-footer">
            {submitted ? <Space wrap><Button icon={<UiIcon icon={FileTextOutlined} />} onClick={() => setEvidenceOpen(value => !value)}>{evidenceOpen ? '收起制度依据' : '查看制度依据'}</Button>
              <MaterialRecommendations key={`${current.assessment_id}:${question.question_id}`}
                endpoint={`/api/v1/learning-assessments/${current.assessment_id}/questions/${encodeURIComponent(question.question_id)}/materials`} />
            </Space>
              : <Typography.Text type="secondary">提交后可查看答案解析与制度依据</Typography.Text>}
            <Space><Button icon={<UiIcon icon={LeftOutlined} />} disabled={position <= 0} onClick={() => chooseQuestion(indices[position - 1])}>上一题</Button>
              <Button type="primary" disabled={position >= indices.length - 1} onClick={() => chooseQuestion(indices[position + 1])}>下一题 <UiIcon icon={RightOutlined} /></Button></Space>
          </footer>
          {submitted && evidenceOpen && <div className="learning-evidence">
            <Typography.Text strong>{question.knowledge_point} · 生成时原文快照</Typography.Text>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{question.source_text_snapshot}</Typography.Paragraph>
            <Link target="_blank" rel="noopener noreferrer" to={current.version_changed ? '/documents/' + current.document_id : '/documents/' + current.document_id + '?node=' + question.primary_node_id + '&parse_run_id=' + current.parse_run_id}>
              {current.version_changed ? '查看当前制度（正文已更新）' : '查看制度原文'}</Link>
          </div>}
        </Card> : <Card bordered={false} className="learning-question-card"><Empty description="本次没有错题或未答题"><Button onClick={() => setOnlyWrong(false)}>查看全部题目</Button></Empty></Card>}
      </main>
      <aside className="learning-side-column">
        <Card bordered={false} title={submitted ? '本次检测结果' : '答题进度'}>
          {submitted && current.result && <div className="learning-score"><strong>{current.result.score}</strong><span> / 100 分</span></div>}
          <div className="learning-progress-row"><Progress percent={questionTotal ? Math.round(answered * 100 / questionTotal) : 0} showInfo={false} /><span>{answered} / {questionTotal}</span></div>
          <div className={'learning-metrics' + (submitted ? ' is-submitted' : '')}>
            <div className="is-blue"><strong>{answered}</strong><span>已答题</span></div>
            <div><strong>{questionTotal - answered}</strong><span>未答题</span></div>
            {submitted && current.result && <><div className="is-green"><strong>{current.result.correct}</strong><span>正确</span></div>
              <div className="is-red"><strong>{current.result.total - current.result.correct - current.result.unanswered}</strong><span>错误</span></div></>}
          </div>
          {!submitted && <Space direction="vertical" className="full-width"><Button block type="primary" loading={busy} onClick={confirmSubmit}>提交检测</Button>
            <Button block loading={busy} onClick={() => void save()}>暂存作答</Button><Typography.Text type="secondary">离开前请暂存；仅切换本页分区或题目会保留未暂存选项。</Typography.Text></Space>}
        </Card>
        <Card bordered={false} title="题目导航" extra={submitted ? <Space size={6}><Switch size="small" checked={onlyWrong} onChange={value => { setOnlyWrong(value); setEvidenceOpen(false); }} /><span className="learning-filter-label">仅错题／未答</span></Space> : undefined}>
          <div className="learning-nav-legend"><span><i className="is-current" />当前题</span>
            {submitted ? <><span><i className="is-correct" />正确</span><span><i className="is-wrong" />错误</span></> : <span><i className="is-answered" />已答</span>}
            <span><i />未答</span></div>
          <div className="learning-question-nav">{indices.map(index => {
            const q = current.questions[index];
            const result = current.result?.details.find(d => d.question_id === q.question_id);
            const status = submitted ? (result?.correct ? 'is-correct' : result?.unanswered ? '' : 'is-wrong') : (answers[q.question_id]?.length ? 'is-answered' : '');
            const label = submitted ? (result?.correct ? '正确' : result?.unanswered ? '未答' : '错误') : (answers[q.question_id]?.length ? '已答' : '未答');
            return <button type="button" key={q.question_id} aria-label={'第' + (index + 1) + '题，' + label} aria-current={index === activeIndex ? 'step' : undefined}
              className={status + (index === activeIndex ? ' is-current' : '')} onClick={() => chooseQuestion(index)}>{index + 1}</button>;
          })}</div>
          {!indices.length && <Typography.Text type="secondary">没有需要复习的错题或未答题。</Typography.Text>}
        </Card>
        <Card bordered={false} className="learning-review-card" title="本次建议复习">
          {submitted && current.result ? current.result.weak_points.length ? <div className="learning-review-list">{current.result.weak_points.map(point => <button type="button" key={point.primary_node_id} onClick={() => {
            const index = current.questions.findIndex(q => q.primary_node_id === point.primary_node_id);
            setOnlyWrong(false); if (index >= 0) { chooseQuestion(index); setEvidenceOpen(true); }
          }}><UiIcon icon={FileTextOutlined} /><span><strong>{point.knowledge_point}</strong><small>{point.total}题 · 错{point.wrong}题 · 未答{point.unanswered}题</small></span><UiIcon icon={RightOutlined} /></button>)}</div>
            : <Typography.Text type="secondary">本次题目均作答正确；未考查内容不代表已掌握。</Typography.Text>
            : <Typography.Text type="secondary">提交后，根据本次答题结果显示薄弱知识点与重点复习条款。</Typography.Text>}
        </Card>
      </aside>
    </div> : <Card bordered={false} className="learning-empty"><Empty description={generating ? '题目正在生成，请稍候；完成后将自动进入答题界面' : '暂无有效检测，请先选择制度生成题目'}>
      <Button type="primary" onClick={() => setView('config')}>前往检测配置</Button></Empty></Card>}
  </div>;
}
