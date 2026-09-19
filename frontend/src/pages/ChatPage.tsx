/**
 * 文件说明：提供沉浸式制度问答工作区，统一管理连续消息流、会话导航、Citation定位和反馈交互。
 */
import {
  BookOutlined,
  CloseOutlined,
  CopyOutlined,
  DeleteOutlined,
  DislikeFilled,
  DislikeOutlined,
  DownOutlined,
  EditOutlined,
  FileSearchOutlined,
  FileProtectOutlined,
  HomeOutlined,
  LikeFilled,
  LikeOutlined,
  MenuOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Actions, Bubble, Conversations, Prompts, Sender } from '@ant-design/x';
import type { BubbleDataType } from '@ant-design/x/es/bubble/BubbleList';
import type { SenderRef } from '@ant-design/x/es/sender';
import {
  Button,
  Checkbox,
  Collapse,
  Drawer,
  Dropdown,
  Empty,
  Input,
  Modal,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import remarkGfm from 'remark-gfm';

import {
  createSession,
  deleteSession,
  getQueryScopeCapabilities,
  listMessages,
  listSessions,
  renameSession,
  sendMessage,
  submitFeedback,
} from '../api/chat';
import { getDocument, listDocuments } from '../api/documents';
import { EvidencePanel } from '../components/EvidencePanel';
import { UiIcon } from '../components/UiIcon';
import { commonPolicyQuestions } from '../data/commonPolicyQuestions';
import type {
  ChatMessage,
  ChatSession,
  CitationSnapshot,
  DocumentSelection,
  QueryScope,
  QueryScopeCapabilities,
} from '../types/chat';
import type { DocumentSummary } from '../types/documents';
import { parseChatLaunchState } from '../utils/chatNavigation';

const feedbackReasons = [
  { label: '未召回正确制度', value: 'retrieval_miss' },
  { label: 'Citation不能支撑答案', value: 'citation_mismatch' },
  { label: '引用正确但回答错误', value: 'answer_wrong_with_valid_citation' },
  { label: '回答不完整', value: 'answer_incomplete' },
  { label: '引用了失效制度', value: 'inactive_document_used' },
  { label: '问题理解错误', value: 'query_misunderstood' },
  { label: '冲突处理错误', value: 'conflict_mishandled' },
  { label: '其他', value: 'other' },
];

function normalizeCitationLabel(label: string): string {
  return label.replace(/^\[|\]$/g, '');
}

function formatCitationLabel(label: string): string {
  return `[${normalizeCitationLabel(label)}]`;
}

function sessionGroup(updatedAt: string): '今天' | '昨天' | '更早' {
  const updated = new Date(updatedAt);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (updated >= today) return '今天';
  if (updated >= yesterday) return '昨天';
  return '更早';
}

function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const knownIds = new Set(current.map((item) => item.id));
  return [...current, ...incoming.filter((item) => !knownIds.has(item.id))];
}

function useDesktopChat(): boolean {
  const [desktop, setDesktop] = useState(() => window.matchMedia('(min-width: 1200px)').matches);

  useEffect(() => {
    const query = window.matchMedia('(min-width: 1200px)');
    const update = (event: MediaQueryListEvent) => setDesktop(event.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return desktop;
}

async function copyToClipboard(content: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(content);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = content;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  textarea.remove();
}

function citationMarkdown(content: string, citations: CitationSnapshot[]): string {
  const labels = new Set(citations.map((item) => normalizeCitationLabel(item.label)));
  return content.replace(/\[(E?\d+)\](?!\()/g, (source, label: string) => (
    labels.has(label) ? `[${label}](#citation-${encodeURIComponent(label)})` : source
  ));
}

function markdownComponents(
  citationByLabel: Map<string, CitationSnapshot>,
  onCitation: (citation: CitationSnapshot) => void,
): Components {
  return {
    a: ({ href, children }) => {
      if (href?.startsWith('#citation-')) {
        const label = decodeURIComponent(href.slice('#citation-'.length));
        const citation = citationByLabel.get(label);
        if (citation) {
          return (
            <button type="button" className="citation-inline" onClick={() => onCitation(citation)}>
              {children}
            </button>
          );
        }
      }
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    },
  };
}

function AnswerBody({
  item,
  feedback,
  onCitation,
  onFeedback,
}: {
  item: ChatMessage;
  feedback?: 'up' | 'down';
  onCitation: (citation: CitationSnapshot) => void;
  onFeedback: (rating: 'up' | 'down') => void;
}) {
  const citationByLabel = useMemo(
    () => new Map(item.citations.map((citation) => [normalizeCitationLabel(citation.label), citation])),
    [item.citations],
  );
  // 所有回答状态共用公开正文和引用渲染，空正文才使用状态对应的兜底说明。
  const fallbackContent = item.answer_status === 'INSUFFICIENT_EVIDENCE'
    ? '当前可用证据不足以确定结论。请补充适用部门、时间或具体业务情形后继续追问。'
    : '本次回答暂无正文，请重试或查看回答详情。';
  const markdown = citationMarkdown(item.content.trim() || fallbackContent, item.citations);
  const components = useMemo(
    () => markdownComponents(citationByLabel, onCitation),
    [citationByLabel, onCitation],
  );

  const actionItems = [
    {
      key: 'copy',
      label: '复制',
      icon: <Tooltip title="复制回答"><UiIcon icon={CopyOutlined} /></Tooltip>,
    },
    {
      key: 'up',
      label: '有帮助',
      icon: <Tooltip title="有帮助">{feedback === 'up' ? <UiIcon icon={LikeFilled} /> : <UiIcon icon={LikeOutlined} />}</Tooltip>,
    },
    {
      key: 'down',
      label: '无帮助',
      icon: <Tooltip title="无帮助">{feedback === 'down' ? <UiIcon icon={DislikeFilled} /> : <UiIcon icon={DislikeOutlined} />}</Tooltip>,
    },
  ];

  return (
    <article className="assistant-answer">
      {item.rewrite_used && item.retrieval_query ? (
        <details><summary>本轮已结合你确认的条件查询</summary><Typography.Paragraph>{item.retrieval_query}</Typography.Paragraph></details>
      ) : null}
      {item.answer_status === 'ANSWER' && item.answerability === 'PARTIAL' ? (
        <div className="answer-state">
          <Typography.Title level={5}>{item.reason_code === 'MISSING_USER_CONTEXT'
            ? '已提供条件答案，仍需补充信息' : '已提供部分答案，尚不能确定完整结论'}</Typography.Title>
        </div>
      ) : null}
      {item.answer_status === 'INSUFFICIENT_EVIDENCE' ? (
        <div className="answer-state answer-state-insufficient">
          <Typography.Title level={5}>尚不能确定最终结论</Typography.Title>
        </div>
      ) : null}
      <div className="answer-markdown">
        {item.answer_status === 'CONFLICT' ? (
          <Typography.Title level={5} className="conflict-heading">当前制度中存在不同规定</Typography.Title>
        ) : null}
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{markdown}</ReactMarkdown>
      </div>

      {item.answer_status === 'CONFLICT' && item.conflicts.length > 0 ? (
        <div className="conflict-list">
          {item.conflicts.map((conflict, conflictIndex) => (
            <section key={`${conflict.topic}-${conflictIndex}`} className="conflict-item">
              <Typography.Text strong>{conflict.topic}</Typography.Text>
              {conflict.positions.map((position, positionIndex) => (
                <div key={`${position.statement}-${positionIndex}`} className="conflict-position">
                  <span>{position.statement}</span>
                  <span className="conflict-citations">
                    {position.citations.map((label) => {
                      const citation = citationByLabel.get(normalizeCitationLabel(label));
                      return citation ? (
                        <button key={label} type="button" onClick={() => onCitation(citation)}>
                          {formatCitationLabel(label)}
                        </button>
                      ) : <span key={label}>{formatCitationLabel(label)}</span>;
                    })}
                  </span>
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : null}

      {item.citations.length > 0 ? (
        <section className="answer-citations" aria-label="引用依据">
          <Typography.Text type="secondary" className="citation-heading">引用依据</Typography.Text>
          <div className="citation-chip-list">
            {item.citations.map((citation) => (
              <button
                key={citation.evidence_uid}
                type="button"
                className="citation-chip"
                onClick={() => onCitation(citation)}
              >
                <span>{formatCitationLabel(citation.label)}</span>
                <span>{citation.document_title}</span>
                {citation.path_text ? <span>{citation.path_text}</span> : null}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <div className="answer-footer">
        <Actions
          className="answer-actions"
          items={actionItems}
          onClick={({ key }) => {
            if (key === 'copy') {
              void copyToClipboard(item.content)
                .then(() => message.success('回答已复制'))
                .catch(() => message.error('复制失败，请手动选择文本'));
              return;
            }
            onFeedback(key as 'up' | 'down');
          }}
        />
        <Collapse
          ghost
          size="small"
          className="answer-details"
          items={[{
            key: 'details',
            label: '回答详情',
            children: (
              <dl className="technical-details">
                <div><dt>请求标识</dt><dd>{item.request_id}</dd></div>
                <div><dt>引擎请求标识</dt><dd>{item.engine_request_id ?? '—'}</dd></div>
                <div><dt>响应契约</dt><dd>{item.contract_version ?? '—'}</dd></div>
                <div><dt>查询范围</dt><dd>{item.query_scope === 'HISTORICAL' ? '历史制度' : '现行有效制度'}</dd></div>
                <div>
                  <dt>制度选择</dt>
                  <dd>
                    {item.document_selection_mode === 'ALL'
                      ? '全部可访问制度'
                      : `指定制度：${item.selected_document_ids.join('、')}`}
                  </dd>
                </div>
                <div><dt>范围制度数</dt><dd>{item.access_scope_count}</dd></div>
                <div><dt>查询索引</dt><dd>{item.query_index_run_id ?? '—'}</dd></div>
                <div><dt>索引运行</dt><dd>{item.index_run_id ?? '—'}</dd></div>
                <div>
                  <dt>质量门禁</dt>
                  <dd>
                    {item.quality_gate
                      ? item.quality_gate.semantic_verification === 'DISABLED'
                        ? '未启用'
                        : `${item.quality_gate.version} / ${item.quality_gate.status}`
                      : '—'}
                  </dd>
                </div>
              </dl>
            ),
          }]}
        />
      </div>
    </article>
  );
}

export function ChatPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { sessionId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const isDesktop = useDesktopChat();
  const senderRef = useRef<SenderRef>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionSearch, setSessionSearch] = useState('');
  const [draft, setDraft] = useState(searchParams.get('draft') ?? '');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [pendingContent, setPendingContent] = useState<string | null>(null);
  const [failedContent, setFailedContent] = useState<string | null>(null);
  const [failedScope, setFailedScope] = useState<QueryScope>('CURRENT');
  const [failedSelection, setFailedSelection] = useState<DocumentSelection>({ mode: 'ALL' });
  const [queryScope, setQueryScope] = useState<QueryScope>('CURRENT');
  const [documentSelectionMode, setDocumentSelectionMode] = useState<'ALL' | 'SELECTED'>('ALL');
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<number[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<DocumentSummary[]>([]);
  const [scopeCapabilities, setScopeCapabilities] = useState<QueryScopeCapabilities | null>(null);
  const [documentPickerOpen, setDocumentPickerOpen] = useState(false);
  const [documentPickerKeyword, setDocumentPickerKeyword] = useState('');
  const [documentPickerPage, setDocumentPickerPage] = useState(1);
  const [documentPickerItems, setDocumentPickerItems] = useState<DocumentSummary[]>([]);
  const [documentPickerTotal, setDocumentPickerTotal] = useState(0);
  const [documentPickerLoading, setDocumentPickerLoading] = useState(false);
  const [pickerSelectedIds, setPickerSelectedIds] = useState<number[]>([]);
  const [pickerDocumentMap, setPickerDocumentMap] = useState<Record<number, DocumentSummary>>({});
  const [feedbackTarget, setFeedbackTarget] = useState<ChatMessage | null>(null);
  const [feedbackByMessage, setFeedbackByMessage] = useState<Record<string, 'up' | 'down'>>({});
  const [reasons, setReasons] = useState<string[]>([]);
  const [comment, setComment] = useState('');
  const [markEval, setMarkEval] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ChatSession | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [selectedCitation, setSelectedCitation] = useState<CitationSnapshot | null>(null);
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false);
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messageRevisionRef = useRef(0);
  const launchRequestRef = useRef(parseChatLaunchState(location.state));

  const documentSelection = useMemo<DocumentSelection>(
    () => documentSelectionMode === 'SELECTED'
      ? { mode: 'SELECTED', document_ids: selectedDocumentIds }
      : { mode: 'ALL' },
    [documentSelectionMode, selectedDocumentIds],
  );

  const refreshSessions = async () => setSessions(await listSessions());

  useEffect(() => {
    void refreshSessions().catch((error: unknown) => (
      message.error(error instanceof Error ? error.message : '会话加载失败')
    ));
    void getQueryScopeCapabilities()
      .then(setScopeCapabilities)
      .catch(() => setScopeCapabilities(null));
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setSelectedCitation(null);
      return;
    }
    const loadRevision = messageRevisionRef.current;
    setMessages([]);
    setLoading(true);
    listMessages(sessionId)
      .then(async (items) => {
        setMessages((current) => (
          messageRevisionRef.current === loadRevision ? items : mergeMessages(items, current)
        ));
        const latestQuestion = [...items].reverse().find((item) => item.role === 'user');
        if (!latestQuestion || messageRevisionRef.current !== loadRevision) return;
        setQueryScope(latestQuestion.query_scope);
        if (latestQuestion.document_selection_mode === 'SELECTED') {
          const restored = await Promise.all(latestQuestion.selected_document_ids.map(async (documentId) => {
            try {
              return await getDocument(String(documentId));
            } catch {
              return null;
            }
          }));
          const available = restored.filter((item): item is DocumentSummary => item !== null);
          setSelectedDocumentIds(latestQuestion.selected_document_ids);
          setSelectedDocuments(available);
          setDocumentSelectionMode('SELECTED');
          if (available.length !== latestQuestion.selected_document_ids.length) {
            message.warning('历史会话的部分制度当前不可用，请重新选择后再提问');
          }
        } else {
          setDocumentSelectionMode('ALL');
          setSelectedDocumentIds([]);
          setSelectedDocuments([]);
        }
      })
      .catch((error: unknown) => message.error(error instanceof Error ? error.message : '消息加载失败'))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    if (!documentPickerOpen) return;
    let cancelled = false;
    setDocumentPickerLoading(true);
    listDocuments({
      keyword: documentPickerKeyword || undefined,
      query_scope: queryScope,
      page: documentPickerPage,
      page_size: 10,
      sort_by: 'updated_at',
      sort_order: 'desc',
    })
      .then((result) => {
        if (cancelled) return;
        setDocumentPickerItems(result.items);
        setDocumentPickerTotal(result.total);
      })
      .catch((error: unknown) => {
        if (!cancelled) message.error(error instanceof Error ? error.message : '制度列表加载失败');
      })
      .finally(() => {
        if (!cancelled) setDocumentPickerLoading(false);
      });
    return () => { cancelled = true; };
  }, [documentPickerOpen, documentPickerKeyword, documentPickerPage, queryScope]);

  const allCitations = useMemo(
    () => messages.filter((item) => item.role === 'assistant').flatMap((item) => item.citations),
    [messages],
  );
  const defaultCitation = useMemo(
    () => [...messages].reverse().find((item) => item.citations.length > 0)?.citations[0] ?? null,
    [messages],
  );

  useEffect(() => {
    const evidenceUid = searchParams.get('evidence_uid');
    const evidenceLabel = searchParams.get('evidence');
    if (!evidenceUid && !evidenceLabel) {
      setSelectedCitation(defaultCitation);
      return;
    }
    const matched = evidenceUid
      ? allCitations.find((item) => item.evidence_uid === evidenceUid)
      : [...allCitations].reverse().find((item) => normalizeCitationLabel(item.label) === normalizeCitationLabel(evidenceLabel ?? ''));
    setSelectedCitation(matched ?? null);
  }, [allCitations, defaultCitation, searchParams]);

  useEffect(() => {
    if (isDesktop) setEvidenceDrawerOpen(false);
  }, [isDesktop]);

  const closeEvidence = () => {
    setSelectedCitation(null);
    setEvidenceDrawerOpen(false);
    const next = new URLSearchParams(searchParams);
    next.delete('evidence');
    next.delete('evidence_uid');
    setSearchParams(next, { replace: true });
  };

  const selectCitation = (citation: CitationSnapshot, openDrawer = true) => {
    setSelectedCitation(citation);
    const next = new URLSearchParams(searchParams);
    next.delete('draft');
    next.set('evidence', normalizeCitationLabel(citation.label));
    next.set('evidence_uid', citation.evidence_uid);
    setSearchParams(next, { replace: true });
    if (!isDesktop && openDrawer) setEvidenceDrawerOpen(true);
  };

  const relatedCitations = useMemo(() => {
    if (!selectedCitation) return [];
    return messages.find((item) => item.citations.some(
      (citation) => citation.evidence_uid === selectedCitation.evidence_uid,
    ))?.citations ?? [];
  }, [messages, selectedCitation]);

  const executeSend = async (
    targetSessionId: string,
    submitted: string,
    scope: QueryScope,
    selection: DocumentSelection,
  ) => {
    const content = submitted.trim();
    if (!content || sending) return;
    setSending(true);
    setPendingContent(content);
    setFailedContent(null);
    setDraft('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const turn = await sendMessage(targetSessionId, content, scope, selection, controller.signal);
      // 新会话路由加载与首问响应可能并发返回，按公开消息 ID 合并可避免重复消息。
      messageRevisionRef.current += 1;
      setMessages((current) => mergeMessages(current, [turn.user_message, turn.assistant_message]));
      const firstCitation = turn.assistant_message.citations[0];
      if (firstCitation) selectCitation(firstCitation, false);
      await refreshSessions();
    } catch (error) {
      setDraft(content);
      setFailedContent(content);
      setFailedScope(scope);
      setFailedSelection(selection);
      message.error(
        error instanceof Error && error.name === 'AbortError'
          ? '已取消本地等待；请刷新会话确认后台请求状态。'
          : error instanceof Error ? error.message : '知识服务查询失败',
      );
      try {
        const restoredMessages = await listMessages(targetSessionId);
        messageRevisionRef.current += 1;
        setMessages(restoredMessages);
      } catch {
        // 保留当前消息，避免刷新失败时清空用户已经看到的历史内容。
      }
    } finally {
      abortRef.current = null;
      setPendingContent(null);
      setSending(false);
    }
  };

  const handleNewSession = async (
    initialDraft?: string,
    submitImmediately = false,
    initialSelection: DocumentSelection = documentSelection,
  ) => {
    if (sending) return;
    try {
      const created = await createSession();
      await refreshSessions();
      closeEvidence();
      setMessages([]);
      setSessionDrawerOpen(false);
      navigate(`/chat/${created.id}`, { state: null });
      if (initialDraft && submitImmediately) {
        await executeSend(created.id, initialDraft, queryScope, initialSelection);
      } else if (initialDraft) {
        setDraft(initialDraft);
      } else {
        setQueryScope('CURRENT');
        setDocumentSelectionMode('ALL');
        setSelectedDocumentIds([]);
        setSelectedDocuments([]);
      }
      window.setTimeout(() => senderRef.current?.focus(), 0);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '新建会话失败');
    }
  };

  const handleSend = async (submitted?: string) => {
    const content = (submitted ?? draft).trim();
    if (!content) return;
    if (!sessionId) {
      await handleNewSession(content, true, documentSelection);
      return;
    }
    await executeSend(sessionId, content, queryScope, documentSelection);
  };

  const changeQueryScope = (nextScope: QueryScope) => {
    if (nextScope === queryScope) return;
    if (nextScope === 'HISTORICAL' && (!scopeCapabilities || scopeCapabilities.historical_document_count === 0)) {
      message.info('当前正式索引中暂无历史制度');
      return;
    }
    setQueryScope(nextScope);
    if (documentSelectionMode === 'SELECTED') {
      setDocumentSelectionMode('ALL');
      setSelectedDocumentIds([]);
      setSelectedDocuments([]);
      message.info('检索范围已变化，请重新选择具体制度');
    }
  };

  const openDocumentPicker = () => {
    const availableIds = selectedDocuments.map((item) => item.id);
    setPickerSelectedIds(availableIds);
    setPickerDocumentMap(Object.fromEntries(selectedDocuments.map((item) => [item.id, item])));
    if (availableIds.length !== selectedDocumentIds.length) {
      message.info('已移除当前不可用的历史选择，请重新确认制度范围');
    }
    setDocumentPickerKeyword('');
    setDocumentPickerPage(1);
    setDocumentPickerOpen(true);
  };

  const confirmDocumentPicker = () => {
    if (pickerSelectedIds.length === 0) {
      message.warning('请至少选择一份制度');
      return;
    }
    const values = pickerSelectedIds
      .map((documentId) => pickerDocumentMap[documentId])
      .filter((item): item is DocumentSummary => Boolean(item));
    if (values.length !== pickerSelectedIds.length) {
      message.error('部分制度信息已经失效，请重新选择');
      return;
    }
    setSelectedDocumentIds(pickerSelectedIds);
    setSelectedDocuments(values);
    setDocumentSelectionMode('SELECTED');
    setDocumentPickerOpen(false);
  };

  useEffect(() => {
    const request = launchRequestRef.current;
    if (!request) return;
    launchRequestRef.current = null;
    void handleNewSession(request.question, request.autoSubmit);
  }, []);

  const openRename = (session: ChatSession) => {
    setRenameTarget(session);
    setRenameTitle(session.title);
  };

  const handleRename = async () => {
    if (!renameTarget || !renameTitle.trim()) return;
    await renameSession(renameTarget.id, renameTitle.trim());
    setRenameTarget(null);
    await refreshSessions();
  };

  const confirmDelete = (target: ChatSession) => {
    Modal.confirm({
      title: '删除这个会话？',
      content: `“${target.title}”删除后将不再出现在会话列表中。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await deleteSession(target.id);
        await refreshSessions();
        if (target.id === sessionId) {
          closeEvidence();
          navigate('/chat');
        }
      },
    });
  };

  const submitPositiveFeedback = async (item: ChatMessage) => {
    if (feedbackByMessage[item.id]) return;
    try {
      await submitFeedback(item.id, {
        rating: 'up',
        reason_codes: [],
        mark_as_eval_case: false,
      });
      setFeedbackByMessage((current) => ({ ...current, [item.id]: 'up' }));
      message.success('感谢反馈');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '反馈提交失败');
    }
  };

  const openNegativeFeedback = (item: ChatMessage) => {
    if (feedbackByMessage[item.id]) return;
    setFeedbackTarget(item);
    setReasons([]);
    setComment('');
    setMarkEval(false);
  };

  const handleNegativeFeedback = async () => {
    if (!feedbackTarget) return;
    if (reasons.length === 0) {
      message.warning('请至少选择一个需要改进的原因');
      return;
    }
    await submitFeedback(feedbackTarget.id, {
      rating: 'down',
      reason_codes: reasons,
      comment: comment || undefined,
      mark_as_eval_case: markEval,
    });
    setFeedbackByMessage((current) => ({ ...current, [feedbackTarget.id]: 'down' }));
    message.success('反馈已保存');
    setFeedbackTarget(null);
  };

  const handleFeedback = (item: ChatMessage, rating: 'up' | 'down') => {
    if (rating === 'up') void submitPositiveFeedback(item);
    else openNegativeFeedback(item);
  };

  const filteredSessions = sessions.filter((item) => (
    item.title.toLowerCase().includes(sessionSearch.trim().toLowerCase())
  ));
  const conversationItems = filteredSessions.map((item) => ({
    key: item.id,
    label: item.title,
    timestamp: new Date(item.updated_at).getTime(),
    group: sessionGroup(item.updated_at),
  }));

  const selectSession = (key: string) => {
    closeEvidence();
    navigate(`/chat/${key}`);
    setSessionDrawerOpen(false);
  };

  const sessionList = (
    <div className="conversation-list-wrap">
      <Conversations
        items={conversationItems}
        activeKey={sessionId}
        onActiveChange={selectSession}
        groupable={{
          sort: (left, right) => ['今天', '昨天', '更早'].indexOf(left) - ['今天', '昨天', '更早'].indexOf(right),
        }}
        menu={(conversation) => ({
          trigger: <UiIcon icon={MoreOutlined} aria-label="会话操作" />,
          items: [
            { key: 'rename', label: '重命名', icon: <UiIcon icon={EditOutlined} /> },
            { key: 'delete', label: '删除', danger: true, icon: <UiIcon icon={DeleteOutlined} /> },
          ],
          onClick: ({ key, domEvent }) => {
            domEvent.stopPropagation();
            const target = sessions.find((item) => item.id === conversation.key);
            if (!target) return;
            if (key === 'rename') openRename(target);
            if (key === 'delete') confirmDelete(target);
          },
        })}
      />
      {filteredSessions.length === 0 ? (
        <Typography.Text type="secondary" className="session-empty">没有匹配的会话</Typography.Text>
      ) : null}
    </div>
  );

  const sidebar = (
    <div className="chat-sidebar-inner">
      <div className="chat-brand">
        <span className="chat-brand-mark"><UiIcon icon={FileProtectOutlined} /></span>
        <span className="chat-brand-copy">
          <Typography.Text strong>制度智能助手</Typography.Text>
          <Tooltip title="返回平台首页" placement="right">
            <button type="button" className="platform-home-link" onClick={() => navigate('/')}>
              点击返回平台首页
            </button>
          </Tooltip>
        </span>
        {!isDesktop ? (
          <Button type="text" shape="circle" aria-label="关闭会话列表" icon={<UiIcon icon={CloseOutlined} />} onClick={() => setSessionDrawerOpen(false)} />
        ) : null}
      </div>
      <Button type="primary" size="large" className="new-chat-button" icon={<UiIcon icon={PlusOutlined} />} onClick={() => void handleNewSession()}>
        新建对话
      </Button>
      <Input
        allowClear
        className="session-search"
        prefix={<UiIcon icon={SearchOutlined} />}
        placeholder="搜索会话"
        value={sessionSearch}
        onChange={(event) => setSessionSearch(event.target.value)}
      />
      {sessionList}
      <nav className="chat-sidebar-nav" aria-label="平台快捷导航">
        <Button type="text" icon={<UiIcon icon={HomeOutlined} />} onClick={() => navigate('/')}>首页</Button>
        <Button type="text" icon={<UiIcon icon={BookOutlined} />} onClick={() => navigate('/documents')}>制度库</Button>
        <Button type="text" icon={<UiIcon icon={SettingOutlined} />} onClick={() => navigate('/settings/about')}>服务说明</Button>
      </nav>
    </div>
  );

  const latestAssistantId = [...messages].reverse().find((item) => item.role === 'assistant')?.id;
  const bubbleItems: BubbleDataType[] = messages.map((item) => ({
    key: item.id,
    role: item.role,
    placement: item.role === 'user' ? 'end' as const : 'start' as const,
    variant: item.role === 'user' ? 'filled' as const : 'borderless' as const,
    shape: 'round' as const,
    className: item.role === 'user' ? 'user-message-bubble' : 'assistant-message-bubble',
    avatar: item.role === 'user'
      ? { icon: <UiIcon icon={UserOutlined} />, className: 'message-avatar user-message-avatar' }
      : { icon: <UiIcon icon={FileProtectOutlined} />, className: 'message-avatar assistant-message-avatar' },
    content: item.role === 'assistant' ? (
      <>
        <AnswerBody
          item={item}
          feedback={feedbackByMessage[item.id]}
          onCitation={selectCitation}
          onFeedback={(rating) => handleFeedback(item, rating)}
        />
        {item.id === latestAssistantId && !sending && item.answerability === 'PARTIAL'
          && item.reason_code === 'MISSING_USER_CONTEXT' && item.clarification_question ? (
          <section className="follow-up-prompts" aria-label="需要补充">
            <Typography.Text strong>需要补充</Typography.Text>
            <Typography.Paragraph>{item.clarification_question}</Typography.Paragraph>
            <Button onClick={() => {
              // S3由服务端承接最近的澄清轮次，只提交用户本轮明确补充的信息。
              setDraft('补充信息：');
              senderRef.current?.focus();
            }}>补充信息</Button>
          </section>
        ) : null}
      </>
    ) : <div className="user-message-content">{item.content}</div>,
  }));

  if (pendingContent) {
    const persistedPendingUser = messages.some(
      (item) => item.role === 'user' && item.content === pendingContent,
    );
    if (!persistedPendingUser) {
      bubbleItems.push({
        key: 'pending-user',
        role: 'user',
        placement: 'end',
        variant: 'filled',
        shape: 'round',
        className: 'user-message-bubble',
        avatar: { icon: <UiIcon icon={UserOutlined} />, className: 'message-avatar user-message-avatar' },
        content: <div className="user-message-content">{pendingContent}</div>,
      });
    }
    bubbleItems.push({
      key: 'pending-assistant',
      role: 'assistant',
      placement: 'start',
      variant: 'borderless',
      shape: 'round',
      className: 'assistant-message-bubble assistant-message-loading',
      avatar: { icon: <UiIcon icon={FileProtectOutlined} />, className: 'message-avatar assistant-message-avatar' },
      loading: true,
      content: <span />,
    });
  }

  const evidenceContent = (
    <EvidencePanel
      citation={selectedCitation}
      relatedCitations={relatedCitations}
      onSelect={selectCitation}
      onClose={!isDesktop ? () => setEvidenceDrawerOpen(false) : undefined}
    />
  );

  return (
    <div className="chat-workspace">
      <aside className="chat-sidebar">{sidebar}</aside>

      <main className="chat-main">
        <header className="chat-main-header">
          <Button
            className="session-drawer-trigger"
            type="text"
            shape="circle"
            aria-label="打开会话列表"
            icon={<UiIcon icon={MenuOutlined} />}
            onClick={() => setSessionDrawerOpen(true)}
          />
          <Typography.Text strong ellipsis>
            {sessions.find((item) => item.id === sessionId)?.title ?? '制度智能助手'}
          </Typography.Text>
          <span className="chat-main-header-spacer" />
          {selectedCitation && !isDesktop ? (
            <Button type="text" onClick={() => setEvidenceDrawerOpen(true)}>查看证据</Button>
          ) : null}
        </header>

        <div className="message-scroll-region">
          {!sessionId ? (
            <div className="chat-welcome">
              <span className="welcome-mark"><UiIcon icon={FileProtectOutlined} /></span>
              <Typography.Title level={2}>今天想查询哪项制度？</Typography.Title>
              <Typography.Paragraph type="secondary">
                我会基于制度库中的公开证据回答，并提供可核验的制度原文。
              </Typography.Paragraph>
              <Prompts
                rootClassName="starter-prompts"
                title="你可以这样问"
                items={commonPolicyQuestions.slice(0, 3)}
                wrap
                onItemClick={({ data }) => {
                  const prompt = String(data.label ?? '');
                  if (prompt) void handleNewSession(prompt);
                }}
              />
              <Button type="primary" icon={<UiIcon icon={PlusOutlined} />} onClick={() => void handleNewSession()}>新建对话</Button>
            </div>
          ) : loading ? (
            <div className="message-loading"><Skeleton active paragraph={{ rows: 4 }} /></div>
          ) : messages.length === 0 && !pendingContent ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="输入问题，开始查询制度依据" />
          ) : (
            <Bubble.List rootClassName="message-list" items={bubbleItems} autoScroll />
          )}
        </div>

        <div className="composer-region">
          {failedContent ? (
            <div className="send-failure">
              <span>上次发送未完成，问题已保留。</span>
              <Button
                type="link"
                size="small"
                onClick={() => void executeSend(
                  sessionId ?? '',
                  failedContent,
                  failedScope,
                  failedSelection,
                )}
              >
                按原范围重试
              </Button>
            </div>
          ) : null}
          <Sender
            ref={senderRef}
            rootClassName="chat-sender"
            value={draft}
            loading={sending}
            disabled={loading || (queryScope === 'HISTORICAL' && (!scopeCapabilities || scopeCapabilities.historical_document_count === 0))}
            submitType="enter"
            placeholder="询问制度相关问题……"
            autoSize={{ minRows: 1, maxRows: 6 }}
            actions={false}
            footer={({ components }) => {
              const ActionButton = sending ? components.LoadingButton : components.SendButton;
              return (
                <div className="composer-toolbar">
                  <div className="composer-tools">
                    <Dropdown
                      disabled={sending}
                      trigger={['click']}
                      menu={{
                        selectedKeys: [documentSelectionMode],
                        items: [
                          { key: 'ALL', label: '全部可访问制度' },
                          { key: 'SELECTED', label: '选择具体制度' },
                        ],
                        onClick: ({ key }) => {
                          if (key === 'ALL') {
                            setDocumentSelectionMode('ALL');
                            setSelectedDocumentIds([]);
                            setSelectedDocuments([]);
                          } else {
                            openDocumentPicker();
                          }
                        },
                      }}
                    >
                      <Button className="composer-tool-button" icon={<UiIcon icon={FileSearchOutlined} />}>
                        {documentSelectionMode === 'SELECTED'
                          ? `已选 ${selectedDocumentIds.length} 份制度`
                          : '全部可访问制度'}
                        <UiIcon icon={DownOutlined} />
                      </Button>
                    </Dropdown>
                    <Dropdown
                      disabled={sending}
                      trigger={['click']}
                      menu={{
                        selectedKeys: [queryScope],
                        items: [
                          {
                            key: 'CURRENT',
                            label: `现行有效制度（${scopeCapabilities?.current_document_count ?? '—'}）`,
                          },
                          {
                            key: 'HISTORICAL',
                            label: scopeCapabilities?.historical_document_count === 0
                              ? '历史制度（暂无可查询制度）'
                              : `历史制度（${scopeCapabilities?.historical_document_count ?? '—'}）`,
                            disabled: !scopeCapabilities || scopeCapabilities.historical_document_count === 0,
                          },
                        ],
                        onClick: ({ key }) => changeQueryScope(key as QueryScope),
                      }}
                    >
                      <Button className="composer-tool-button">
                        {queryScope === 'CURRENT' ? '现行有效制度' : '历史制度'}
                        <UiIcon icon={DownOutlined} />
                      </Button>
                    </Dropdown>
                  </div>
                  <div className="composer-submit-area">
                    <span className="composer-keyboard-hint">按 Enter 发送，Shift + Enter 换行</span>
                    <ActionButton className="composer-submit-button" shape="circle" type="primary" />
                  </div>
                </div>
              );
            }}
            onChange={setDraft}
            onSubmit={(value) => void handleSend(value)}
            onCancel={() => abortRef.current?.abort()}
          />
          <Typography.Text type="secondary" className="composer-hint">
            {queryScope === 'HISTORICAL' && scopeCapabilities?.historical_document_count === 0
              ? '当前正式索引中暂无历史制度，请切换到现行有效制度。'
              : '答案仅基于当前选择范围内的正式制度，请以引用原文为准。'}
          </Typography.Text>
        </div>
      </main>

      <aside className="evidence-sidebar">{evidenceContent}</aside>

      <Drawer
        className="chat-session-drawer"
        placement="left"
        width={300}
        open={sessionDrawerOpen}
        closable={false}
        onClose={() => setSessionDrawerOpen(false)}
      >
        {sidebar}
      </Drawer>
      <Drawer
        className="chat-evidence-drawer"
        title={null}
        width={400}
        open={!isDesktop && evidenceDrawerOpen && Boolean(selectedCitation)}
        closable={false}
        onClose={() => setEvidenceDrawerOpen(false)}
      >
        {evidenceContent}
      </Drawer>

      <Modal
        title={`选择具体制度 · ${queryScope === 'CURRENT' ? '现行有效' : '历史制度'}`}
        width={820}
        open={documentPickerOpen}
        okText={`确认选择（${pickerSelectedIds.length}）`}
        okButtonProps={{ disabled: pickerSelectedIds.length === 0 }}
        onOk={confirmDocumentPicker}
        onCancel={() => setDocumentPickerOpen(false)}
      >
        <Input.Search
          allowClear
          className="document-picker-search"
          placeholder="搜索制度名称、文号、发布机构或正文关键词"
          value={documentPickerKeyword}
          onChange={(event) => {
            setDocumentPickerKeyword(event.target.value);
            setDocumentPickerPage(1);
          }}
        />
        <Table<DocumentSummary>
          rowKey="id"
          size="small"
          loading={documentPickerLoading}
          dataSource={documentPickerItems}
          columns={[
            {
              title: '制度名称',
              dataIndex: 'title',
              ellipsis: true,
              render: (value: string, item) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>{value}</Typography.Text>
                  <Typography.Text type="secondary">{item.document_code ?? '暂无文号'}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '发布日期',
              dataIndex: 'publish_date',
              width: 130,
              render: (value: string | null) => value ?? '—',
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (value: string) => <Tag color={value === '现行有效' ? 'green' : 'orange'}>{value}</Tag>,
            },
          ]}
          rowSelection={{
            selectedRowKeys: pickerSelectedIds,
            preserveSelectedRowKeys: true,
            getCheckboxProps: (record) => ({
              disabled: pickerSelectedIds.length >= 20 && !pickerSelectedIds.includes(record.id),
            }),
            onChange: (keys, rows) => {
              const nextIds = keys.map(Number);
              if (nextIds.length > 20) {
                message.warning('一次最多选择20份制度');
                return;
              }
              setPickerSelectedIds(nextIds);
              setPickerDocumentMap((current) => {
                const merged = { ...current };
                rows.forEach((item) => { merged[item.id] = item; });
                Object.keys(merged).forEach((key) => {
                  if (!nextIds.includes(Number(key))) delete merged[Number(key)];
                });
                return merged;
              });
            },
          }}
          pagination={{
            current: documentPickerPage,
            pageSize: 10,
            total: documentPickerTotal,
            showSizeChanger: false,
            onChange: setDocumentPickerPage,
          }}
        />
      </Modal>

      <Modal
        title="重命名会话"
        open={Boolean(renameTarget)}
        okText="保存"
        onOk={() => void handleRename()}
        onCancel={() => setRenameTarget(null)}
      >
        <Input
          value={renameTitle}
          maxLength={200}
          onChange={(event) => setRenameTitle(event.target.value)}
          onPressEnter={() => void handleRename()}
        />
      </Modal>
      <Modal
        title="这条回答哪里需要改进？"
        open={Boolean(feedbackTarget)}
        okText="提交反馈"
        onOk={() => void handleNegativeFeedback()}
        onCancel={() => setFeedbackTarget(null)}
      >
        <Space direction="vertical" size={16} className="full-width">
          <Checkbox.Group
            className="feedback-reasons"
            options={feedbackReasons}
            value={reasons}
            onChange={(values) => setReasons(values as string[])}
          />
          <Input.TextArea
            value={comment}
            maxLength={2000}
            placeholder="补充说明（可选）"
            onChange={(event) => setComment(event.target.value)}
          />
          <Checkbox checked={markEval} onChange={(event) => setMarkEval(event.target.checked)}>
            提交为待管理员审核的候选评测案例
          </Checkbox>
        </Space>
      </Modal>
    </div>
  );
}
