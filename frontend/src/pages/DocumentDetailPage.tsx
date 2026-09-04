/**
 * 文件说明：以 Reading View 展示制度正文，并保留 Citation 节点定位与右侧 PDF 对照阅读。
 * 细粒度 policy_node 仅作为数据来源，页面不改变其结构和业务含义。
 */
import { Alert, Breadcrumb, Button, Card, Descriptions, Empty, Space, Spin, Tag, Tree, Typography, message } from 'antd';
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { getDocument, getDocumentNodes } from '../api/documents';
import type { DocumentDetail, DocumentNode } from '../types/documents';
import { buildDocumentReadingView, type DocumentReadingNode } from '../utils/documentReadingView';
import { parseDocumentTable } from '../utils/documentTableView';
import { documentPdfUrl } from '../utils/pdf';

function pageLabel(entry: DocumentReadingNode): string | null {
  if (entry.pageStart == null) return null;
  return entry.pageEnd != null && entry.pageEnd !== entry.pageStart
    ? `第 ${entry.pageStart}—${entry.pageEnd} 页`
    : `第 ${entry.pageStart} 页`;
}

function textMatchesKeyword(text: string | null | undefined, keyword: string): boolean {
  return Boolean(keyword && text?.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()));
}

function HighlightedText({ text, keyword }: { text: string; keyword: string }): ReactNode {
  const query = keyword.trim();
  if (!query) return text;
  const normalizedText = text.toLocaleLowerCase();
  const normalizedQuery = query.toLocaleLowerCase();
  const fragments: ReactNode[] = [];
  let cursor = 0;
  let matchIndex = normalizedText.indexOf(normalizedQuery);

  while (matchIndex >= 0) {
    if (matchIndex > cursor) fragments.push(text.slice(cursor, matchIndex));
    const matchEnd = matchIndex + query.length;
    fragments.push(
      <mark key={`${matchIndex}-${matchEnd}`} className="reading-search-highlight">
        {text.slice(matchIndex, matchEnd)}
      </mark>,
    );
    cursor = matchEnd;
    matchIndex = normalizedText.indexOf(normalizedQuery, cursor);
  }
  if (cursor < text.length) fragments.push(text.slice(cursor));
  return fragments.length ? <>{fragments}</> : text;
}

function firstMatchingReadingNode(entries: DocumentReadingNode[], keyword: string): string | null {
  for (const entry of entries) {
    if (
      textMatchesKeyword(entry.displayTitle, keyword)
      || textMatchesKeyword(entry.displayText, keyword)
    ) return String(entry.node.id);
    const childMatch = firstMatchingReadingNode(entry.children, keyword);
    if (childMatch) return childMatch;
  }
  return null;
}

interface ReadingNodeBlockProps {
  entry: DocumentReadingNode;
  targetNode: string | null;
  highlightKeyword: string;
}

function ReadingNodeBlock({ entry, targetNode, highlightKeyword }: ReadingNodeBlockProps) {
  const { node, children, displayTitle, displayText } = entry;
  const isTarget = String(node.id) === targetNode;
  const classNames = ['reading-node', `reading-node-${node.node_type}`, isTarget ? 'reading-node-target' : ''].filter(Boolean).join(' ');
  const childContent = children.map((child) => (
    <ReadingNodeBlock
      key={child.node.id}
      entry={child}
      targetNode={targetNode}
      highlightKeyword={highlightKeyword}
    />
  ));
  const page = pageLabel(entry);
  const commonProps = {
    id: `node-${node.id}`,
    className: classNames,
    'data-node-type': node.node_type,
  };

  if (node.node_type === 'chapter') {
    return (
      <section {...commonProps}>
        <div className="reading-chapter-heading">
          <Typography.Title level={3}>{displayTitle ? <HighlightedText text={displayTitle} keyword={highlightKeyword} /> : null}</Typography.Title>
          {page ? <Typography.Text type="secondary">{page}</Typography.Text> : null}
        </div>
        {displayText ? <Typography.Paragraph className="reading-paragraph"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph> : null}
        <div className="reading-chapter-content">{childContent}</div>
      </section>
    );
  }

  if (node.node_type === 'article') {
    return (
      <article {...commonProps}>
        <div className="reading-article-heading">
          <Typography.Title level={4}>{displayTitle ? <HighlightedText text={displayTitle} keyword={highlightKeyword} /> : null}</Typography.Title>
          {page ? <Typography.Text type="secondary">{page}</Typography.Text> : null}
        </div>
        {displayText ? <Typography.Paragraph className="reading-paragraph"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph> : null}
        {children.length ? <div className="reading-article-children">{childContent}</div> : null}
      </article>
    );
  }

  if (node.node_type === 'heading' || node.node_type === 'attachment') {
    return (
      <section {...commonProps}>
        <div className="reading-section-heading">
          <Typography.Title level={3}>{displayTitle ? <HighlightedText text={displayTitle} keyword={highlightKeyword} /> : null}</Typography.Title>
          {page ? <Typography.Text type="secondary">{page}</Typography.Text> : null}
        </div>
        {displayText ? <Typography.Paragraph className="reading-paragraph"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph> : null}
        {childContent}
      </section>
    );
  }

  if (node.node_type === 'table') {
    const tableView = parseDocumentTable(displayText, node.table_structure);
    return (
      <section {...commonProps} aria-label="制度正文表格">
        {displayTitle ? <Typography.Text strong><HighlightedText text={displayTitle} keyword={highlightKeyword} /></Typography.Text> : null}
        {tableView ? (
          <div className="reading-table-block">
            {tableView.leadingNotes.map((note, index) => (
              <Typography.Paragraph key={`${node.id}-table-note-${index}`} className="reading-table-preface">
                <HighlightedText text={note} keyword={highlightKeyword} />
              </Typography.Paragraph>
            ))}
            <div className="reading-table-scroll" tabIndex={0} aria-label="表格可横向滚动">
              <table className="reading-table">
                <caption>制度正文表格</caption>
                <tbody>
                  {tableView.rows.map((row, rowIndex) => {
                    if (row.kind === 'note') {
                      return (
                        <tr key={`${node.id}-table-row-${rowIndex}`} className="reading-table-note-row">
                          <td colSpan={tableView.columnCount}><HighlightedText text={row.text} keyword={highlightKeyword} /></td>
                        </tr>
                      );
                    }
                    return (
                      <tr key={`${node.id}-table-row-${rowIndex}`} className={row.header ? 'reading-table-header-row' : undefined}>
                        {row.cells.map((cell, cellIndex) => row.header ? (
                          <th
                            key={`${node.id}-table-cell-${rowIndex}-${cellIndex}`}
                            scope="col"
                            colSpan={cell.colSpan}
                            rowSpan={cell.rowSpan}
                          >
                            <HighlightedText text={cell.text} keyword={highlightKeyword} />
                          </th>
                        ) : (
                          <td
                            key={`${node.id}-table-cell-${rowIndex}-${cellIndex}`}
                            colSpan={cell.colSpan}
                            rowSpan={cell.rowSpan}
                          >
                            <HighlightedText text={cell.text} keyword={highlightKeyword} />
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <Typography.Paragraph className="reading-paragraph reading-table-fallback"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph>
        )}
        {childContent}
      </section>
    );
  }

  if (node.node_type === 'item') {
    return (
      <div {...commonProps}>
        {displayTitle ? <span className="reading-item-marker"><HighlightedText text={displayTitle} keyword={highlightKeyword} /></span> : null}
        <div className="reading-item-content">
          {displayText ? <Typography.Paragraph className="reading-paragraph"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph> : null}
          {childContent}
        </div>
      </div>
    );
  }

  return (
    <div {...commonProps}>
      {displayTitle ? <Typography.Text strong><HighlightedText text={displayTitle} keyword={highlightKeyword} /></Typography.Text> : null}
      {displayText ? <Typography.Paragraph className="reading-paragraph"><HighlightedText text={displayText} keyword={highlightKeyword} /></Typography.Paragraph> : null}
      {childContent}
    </div>
  );
}

export function DocumentDetailPage() {
  const { documentId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const targetNode = searchParams.get('node');
  const highlightKeyword = (searchParams.get('highlight') ?? '').trim();
  const requestedPage = Number(searchParams.get('page') ?? 0);
  const evidence = searchParams.get('evidence');
  const citationParseRun = Number(searchParams.get('parse_run_id') ?? 0);
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [nodes, setNodes] = useState<DocumentNode[]>([]);
  const [loading, setLoading] = useState(true);
  const readingView = useMemo(() => buildDocumentReadingView(nodes), [nodes]);
  const firstHighlightNode = useMemo(() => {
    if (!highlightKeyword) return null;
    return firstMatchingReadingNode(readingView.body, highlightKeyword)
      ?? firstMatchingReadingNode(readingView.frontMatter, highlightKeyword)
      ?? firstMatchingReadingNode(readingView.closingMatter, highlightKeyword);
  }, [highlightKeyword, readingView]);
  const firstHighlightPage = useMemo(() => {
    if (!firstHighlightNode) return null;
    return nodes.find((node) => String(node.id) === firstHighlightNode)?.page_start ?? null;
  }, [firstHighlightNode, nodes]);
  const scrollTargetNode = targetNode ?? firstHighlightNode;

  useEffect(() => {
    setLoading(true);
    Promise.all([getDocument(documentId), getDocumentNodes(documentId)])
      .then(([detail, nodeResult]) => {
        setDocument(detail);
        setNodes(nodeResult.items);
      })
      .catch((error: unknown) => message.error(error instanceof Error ? error.message : '制度详情加载失败'))
      .finally(() => setLoading(false));
  }, [documentId]);

  useEffect(() => {
    if (loading || !scrollTargetNode) return undefined;
    const timer = window.setTimeout(() => {
      const nodeElement = window.document.getElementById(`node-${scrollTargetNode}`);
      const scrollElement = targetNode
        ? nodeElement
        : nodeElement?.querySelector<HTMLElement>('.reading-search-highlight');
      (scrollElement ?? nodeElement)?.scrollIntoView({ block: 'center' });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [loading, nodes, scrollTargetNode, targetNode]);

  if (loading) return <Spin />;
  if (!document) return <Empty description="制度不存在" />;
  const versionChanged = citationParseRun > 0 && citationParseRun !== document.active_parse_run_id;
  const pdfPage = Number.isInteger(requestedPage) && requestedPage > 0
    ? requestedPage
    : (firstHighlightPage ?? 1);
  const pdfUrl = documentPdfUrl(documentId, pdfPage);

  return (
    <div className="page-stack document-reader-page">
      <Breadcrumb items={[{ title: <Link to="/documents">制度库</Link> }, { title: document.title }]} />
      {versionChanged ? (
        <Alert
          type="warning"
          showIcon
          message="当前制度版本已变化"
          description="本页展示当前有效正文；回答时引用的原文请以会话中的证据快照为准。"
        />
      ) : null}
      {evidence ? <Alert type="info" showIcon message="已从问答引用定位到对应条款" /> : null}
      <Card bordered={false} className="document-reader-summary">
        <Space direction="vertical" size={12} className="full-width">
          <Space wrap>
            <Typography.Title level={2} className="page-heading"><HighlightedText text={document.title} keyword={highlightKeyword} /></Typography.Title>
            <Tag color="green">{document.status}</Tag>
            {highlightKeyword ? <Tag className="reading-search-keyword">正文关键词：{highlightKeyword}</Tag> : null}
          </Space>
          <Descriptions column={{ xs: 1, lg: 3 }} size="small">
            <Descriptions.Item label="制度编号">{document.document_code ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="发布机构">{document.issuer ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="责任部门">{document.responsibility_department ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="发布日期">{document.publish_date ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="生效日期">{document.effective_date ?? '-'}</Descriptions.Item>
          </Descriptions>
        </Space>
      </Card>

      <div className="document-detail-grid">
        <Card className="document-toc" title="目录" size="small">
          {readingView.toc.length ? (
            <Tree
              treeData={readingView.toc}
              defaultExpandAll
              selectedKeys={targetNode ? [targetNode] : []}
              onSelect={(keys) => {
                const key = keys[0];
                if (key) window.document.getElementById(`node-${String(key)}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无章节目录" />}
        </Card>

        <main className="document-reading-surface">
          {readingView.frontMatter.length ? (
            <section className="reading-front-matter" aria-label="制发信息">
              {readingView.frontMatter.map((entry) => <ReadingNodeBlock key={entry.node.id} entry={entry} targetNode={targetNode} highlightKeyword={highlightKeyword} />)}
            </section>
          ) : null}
          <div className="reading-main-content">
            {readingView.body.map((entry) => <ReadingNodeBlock key={entry.node.id} entry={entry} targetNode={targetNode} highlightKeyword={highlightKeyword} />)}
          </div>
          {readingView.closingMatter.length ? (
            <footer className="reading-closing-matter">
              {readingView.closingMatter.map((entry) => <ReadingNodeBlock key={entry.node.id} entry={entry} targetNode={targetNode} highlightKeyword={highlightKeyword} />)}
            </footer>
          ) : null}
        </main>

        <Card
          className="document-pdf-preview"
          title={`PDF 对照 · 第 ${pdfPage} 页`}
          size="small"
          extra={document.has_pdf ? <Button type="link" href={pdfUrl} target="_blank" rel="noreferrer">新窗口打开</Button> : null}
        >
          {document.has_pdf ? (
            <iframe title={`${document.title} PDF预览`} src={pdfUrl} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该制度暂无PDF原件" />
          )}
        </Card>
      </div>
    </div>
  );
}
