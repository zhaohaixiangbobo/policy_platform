/**
 * 文件说明：提供以智能问答为第一入口的制度知识门户，并展示常见问题与最近更新制度。
 * 首页只传递待提问内容，由 Chat 页面统一创建会话和发送首条消息。
 */
import {
  ArrowRightOutlined,
  ArrowUpOutlined,
  FileProtectOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  RightOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { Button, Empty, Input, Skeleton, Tag, Tooltip, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { listDocuments } from '../api/documents';
import { UiIcon } from '../components/UiIcon';
import { commonPolicyQuestions } from '../data/commonPolicyQuestions';
import type { DocumentSummary } from '../types/documents';
import { createChatLaunchState } from '../utils/chatNavigation';
import { documentStatusClass } from '../utils/documentStatus';

const QUICK_QUESTION_COUNT = 4;
const FAQ_COUNT = 4;

function documentMetadata(document: DocumentSummary): string {
  const values = [document.document_code, document.issuer].filter(Boolean);
  return values.length > 0 ? values.join(' · ') : '暂无文号和发布机构信息';
}

export function HomePage() {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const [launching, setLaunching] = useState(false);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsFailed, setDocumentsFailed] = useState(false);
  const [faqOffset, setFaqOffset] = useState(0);

  const loadLatestDocuments = async () => {
    setDocumentsLoading(true);
    setDocumentsFailed(false);
    try {
      const result = await listDocuments({
        page: 1,
        page_size: 5,
        sort_by: 'updated_at',
        sort_order: 'desc',
      });
      setDocuments(result.items);
    } catch {
      setDocumentsFailed(true);
    } finally {
      setDocumentsLoading(false);
    }
  };

  useEffect(() => {
    void loadLatestDocuments();
  }, []);

  const visibleFaqs = useMemo(
    () => Array.from(
      { length: Math.min(FAQ_COUNT, commonPolicyQuestions.length) },
      (_, index) => commonPolicyQuestions[(faqOffset + index) % commonPolicyQuestions.length],
    ),
    [faqOffset],
  );

  const launchQuestion = (question = value) => {
    const normalized = question.trim();
    if (!normalized || launching) return;
    setLaunching(true);
    navigate('/chat', { state: createChatLaunchState(normalized) });
  };

  return (
    <div className="home-page">
      <section className="home-hero" aria-labelledby="home-title">
        <span className="home-hero-orb home-hero-orb-left" aria-hidden="true" />
        <span className="home-hero-orb home-hero-orb-right" aria-hidden="true" />
        <div className="home-hero-content">
          <span className="home-assistant-mark" aria-hidden="true">
            <UiIcon icon={FileProtectOutlined} />
          </span>
          <Typography.Title id="home-title" level={1}>制度管理模块</Typography.Title>
          <Typography.Paragraph className="home-subtitle">查制度 · 问条款 · 找依据</Typography.Paragraph>

          <div className="home-question-composer">
            <Input.TextArea
              className="home-question-input"
              variant="borderless"
              value={value}
              autoSize={{ minRows: 2, maxRows: 4 }}
              aria-label="制度问题"
              placeholder="询问任何制度相关问题，例如：退休需要满足哪些条件？"
              onChange={(event) => setValue(event.target.value)}
              onPressEnter={(event) => {
                if (event.shiftKey) return;
                event.preventDefault();
                launchQuestion();
              }}
            />
            <Tooltip title={value.trim() ? '发送问题' : '请输入问题'}>
              <Button
                type="primary"
                shape="circle"
                className="home-send-button"
                loading={launching}
                disabled={!value.trim()}
                aria-label="发送问题"
                icon={<UiIcon icon={ArrowUpOutlined} />}
                onClick={() => launchQuestion()}
              />
            </Tooltip>
          </div>

          <div className="home-quick-questions" aria-label="快捷问题">
            {commonPolicyQuestions.slice(0, QUICK_QUESTION_COUNT).map((question) => (
              <button key={question.key} type="button" onClick={() => launchQuestion(question.label)}>
                <UiIcon icon={QuestionCircleOutlined} />
                <span>{question.label}</span>
              </button>
            ))}
          </div>

          <Button
            type="link"
            className="home-library-link"
            iconPosition="end"
            icon={<UiIcon icon={ArrowRightOutlined} />}
            onClick={() => navigate('/documents')}
          >
            搜索制度库
          </Button>
        </div>
      </section>

      <section className="home-content-grid" aria-label="制度信息入口">
        <article className="home-section home-faq-section">
          <header className="home-section-header">
            <Typography.Title level={4}>
              <UiIcon icon={QuestionCircleOutlined} />
              常见问题
            </Typography.Title>
            <Button
              type="link"
              size="small"
              icon={<UiIcon icon={SyncOutlined} />}
              onClick={() => setFaqOffset((current) => (current + 1) % commonPolicyQuestions.length)}
            >
              换一批
            </Button>
          </header>
          <div className="home-faq-list">
            {visibleFaqs.map((question) => (
              <button key={question.key} type="button" onClick={() => launchQuestion(question.label)}>
                <span>{question.label}</span>
                <UiIcon icon={RightOutlined} />
              </button>
            ))}
          </div>
        </article>

        <article className="home-section home-recent-section">
          <header className="home-section-header">
            <Typography.Title level={4}>
              <UiIcon icon={FileTextOutlined} />
              最近更新制度
            </Typography.Title>
            <Link to="/documents" className="home-section-more">
              查看全部 <UiIcon icon={ArrowRightOutlined} />
            </Link>
          </header>

          {documentsLoading ? (
            <div className="home-recent-loading"><Skeleton active paragraph={{ rows: 4 }} title={false} /></div>
          ) : documentsFailed ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="最近更新制度加载失败">
              <Button onClick={() => void loadLatestDocuments()}>重新加载</Button>
            </Empty>
          ) : documents.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无制度数据" />
          ) : (
            <div className="home-recent-list">
              {documents.map((document) => (
                <article key={document.id} className="home-recent-item">
                  <div className="home-recent-main">
                    <Tooltip title={document.title} placement="topLeft">
                      <Link className="home-document-title" to={`/documents/${document.id}`}>
                        {document.title}
                      </Link>
                    </Tooltip>
                    <Typography.Text type="secondary" ellipsis>{documentMetadata(document)}</Typography.Text>
                  </div>
                  <Typography.Text type="secondary" className="home-document-date">
                    {document.publish_date ?? '发布日期未提供'}
                  </Typography.Text>
                  <Tag className={`document-status-tag ${documentStatusClass(document.status)}`}>
                    {document.status}
                  </Tag>
                </article>
              ))}
            </div>
          )}
        </article>
      </section>

      <footer className="home-footer">© 2026 制度管理模块</footer>
    </div>
  );
}
