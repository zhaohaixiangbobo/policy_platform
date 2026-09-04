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
  EditOutlined,
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
  Empty,
  Input,
  Modal,
  Segmented,
  Skeleton,
  Space,
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
  listMessages,
  listSessions,
  renameSession,
  sendMessage,
  submitFeedback,
} from '../api/chat';
import { EvidencePanel } from '../components/EvidencePanel';
import { UiIcon } from '../components/UiIcon';
import { commonPolicyQuestions } from '../data/commonPolicyQuestions';
import type { ChatMessage, ChatSession, CitationSnapshot, QueryScope } from '../types/chat';
import { parseChatLaunchState } from '../utils/chatNavigation';

// 当前公开回答没有推荐问题字段，以下内容只用于展示，不会写入数据库。
const followUpPrompts = [
  { key: 'basis', label: '这项规定的适用范围是什么？' },
  { key: 'materials', label: '办理时需要准备哪些材料？' },
  { key: 'exceptions', label: '是否存在例外或特殊情形？' },
];

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
  const markdown = citationMarkdown(item.content, item.citations);
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
      {item.answer_status === 'INSUFFICIENT_EVIDENCE' ? (
        <div className="answer-state answer-state-insufficient">
          <Typography.Title level={5}>暂未找到足够依据</Typography.Title>
          <Typography.Paragraph>
            当前制度库中暂未找到足够依据支持可靠结论。你可以补充适用部门、时间或具体业务情形后继续追问。
          </Typography.Paragraph>
        </div>
      ) : (
        <div className="answer-markdown">
          {item.answer_status === 'CONFLICT' ? (
            <Typography.Title level={5} className="conflict-heading">当前制度中存在不同规定</Typography.Title>
          ) : null}
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{markdown}</ReactMarkdown>
        </div>
      )}

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
  const [queryScope, setQueryScope] = useState<QueryScope>('CURRENT');
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

  const refreshSessions = async () => setSessions(await listSessions());

  useEffect(() => {
    void refreshSessions().catch((error: unknown) => (
      message.error(error instanceof Error ? error.message : '会话加载失败')
    ));
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
      .then((items) => setMessages((current) => (
        messageRevisionRef.current === loadRevision ? items : mergeMessages(items, current)
      )))
      .catch((error: unknown) => message.error(error instanceof Error ? error.message : '消息加载失败'))
      .finally(() => setLoading(false));
  }, [sessionId]);

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

  const executeSend = async (targetSessionId: string, submitted: string, scope: QueryScope) => {
    const content = submitted.trim();
    if (!content || sending) return;
    setSending(true);
    setPendingContent(content);
    setFailedContent(null);
    setDraft('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const turn = await sendMessage(targetSessionId, content, scope, controller.signal);
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

  const handleNewSession = async (initialDraft?: string, submitImmediately = false) => {
    if (sending) return;
    try {
      const created = await createSession();
      await refreshSessions();
      closeEvidence();
      setMessages([]);
      setSessionDrawerOpen(false);
      navigate(`/chat/${created.id}`, { state: null });
      if (initialDraft && submitImmediately) {
        await executeSend(created.id, initialDraft, queryScope);
      } else if (initialDraft) {
        setDraft(initialDraft);
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
      await handleNewSession(content, true);
      return;
    }
    await executeSend(sessionId, content, queryScope);
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
        {item.id === latestAssistantId && !sending ? (
          <Prompts
            rootClassName="follow-up-prompts"
            items={followUpPrompts}
            wrap
            onItemClick={({ data }) => {
              setDraft(String(data.label ?? ''));
              senderRef.current?.focus();
            }}
          />
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
              <Button type="link" size="small" onClick={() => void executeSend(sessionId ?? '', failedContent, failedScope)}>按原范围重试</Button>
            </div>
          ) : null}
          <Space size={12} wrap style={{ marginBottom: 8 }}>
            <Typography.Text type="secondary">检索范围</Typography.Text>
            <Segmented<QueryScope>
              value={queryScope}
              disabled={sending}
              options={[
                { label: '现行有效制度', value: 'CURRENT' },
                { label: '历史制度', value: 'HISTORICAL' },
              ]}
              onChange={setQueryScope}
            />
            {queryScope === 'HISTORICAL' ? <Typography.Text type="warning">仅检索已废止或已失效制度</Typography.Text> : null}
          </Space>
          <Sender
            ref={senderRef}
            rootClassName="chat-sender"
            value={draft}
            loading={sending}
            disabled={loading}
            submitType="enter"
            placeholder="询问制度相关问题……"
            autoSize={{ minRows: 1, maxRows: 6 }}
            onChange={setDraft}
            onSubmit={(value) => void handleSend(value)}
            onCancel={() => abortRef.current?.abort()}
          />
          <Typography.Text type="secondary" className="composer-hint">
            {queryScope === 'CURRENT' ? '默认仅检索现行有效制度' : '当前仅检索历史制度'}，请以制度原文为准。
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
