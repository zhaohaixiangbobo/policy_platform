/**
 * 文件说明：把面向检索的细粒度制度节点聚合为面向阅读的正文结构。
 * 本模块只建立展示关系，不改写节点内容、父子关系或任何 RAG 标识。
 */
import type { DataNode } from 'antd/es/tree';

import type { DocumentNode } from '../types/documents';

const READING_ANCHOR_TYPES = new Set(['chapter', 'heading', 'article', 'item', 'attachment']);
const TOC_TYPES = new Set(['chapter', 'heading', 'article', 'item', 'attachment']);
const CLOSING_TYPES = new Set(['signature', 'distribution']);

export interface DocumentReadingNode {
  node: DocumentNode;
  children: DocumentReadingNode[];
  displayTitle: string | null;
  displayText: string;
  pageStart: number | null;
  pageEnd: number | null;
}

export interface DocumentReadingView {
  frontMatter: DocumentReadingNode[];
  body: DocumentReadingNode[];
  closingMatter: DocumentReadingNode[];
  toc: DataNode[];
}

function compactText(value: string | null | undefined): string {
  return (value ?? '').replace(/[\s\u00a0]+/g, ' ').trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 去掉正文开头已经由标题呈现的条款号，避免“第一条 第一条……”重复。 */
function removeRepeatedTitle(text: string, title: string | null): string {
  const source = text.trim();
  const normalizedTitle = compactText(title);
  if (!source || !normalizedTitle) return source;
  if (compactText(source) === normalizedTitle) return '';

  const flexibleTitle = normalizedTitle
    .split(' ')
    .map(escapeRegExp)
    .join('[\\s\\u00a0]*');
  return source.replace(new RegExp(`^[\\s\\u00a0]*${flexibleTitle}[\\s\\u00a0]*`), '').trim();
}

function readingTitle(node: DocumentNode): string | null {
  const title = compactText(node.title);
  if (title) return title;
  if (!READING_ANCHOR_TYPES.has(node.node_type)) return null;
  const text = compactText(node.text);
  return text || compactText(node.path_text) || null;
}

function collectPageRange(node: DocumentNode, children: DocumentReadingNode[]): [number | null, number | null] {
  const starts = [node.page_start, ...children.map((child) => child.pageStart)].filter((page): page is number => page != null);
  const ends = [node.page_end ?? node.page_start, ...children.map((child) => child.pageEnd)].filter((page): page is number => page != null);
  return [starts.length ? Math.min(...starts) : null, ends.length ? Math.max(...ends) : null];
}

function buildReadingNode(node: DocumentNode, childrenByParent: Map<number, DocumentNode[]>): DocumentReadingNode {
  const children = (childrenByParent.get(node.id) ?? []).map((child) => buildReadingNode(child, childrenByParent));
  const displayTitle = readingTitle(node);
  const [pageStart, pageEnd] = collectPageRange(node, children);
  return {
    node,
    children,
    displayTitle,
    displayText: removeRepeatedTitle(node.text, displayTitle),
    pageStart,
    pageEnd,
  };
}

function tocTitle(entry: DocumentReadingNode): string {
  if (entry.node.node_type === 'article') {
    const articleNumber = compactText(entry.node.node_number);
    if (articleNumber) return articleNumber;
  }
  return entry.displayTitle ?? compactText(entry.node.path_text) ?? `正文 ${entry.node.order_no}`;
}

function buildTocEntry(entry: DocumentReadingNode): DataNode | null {
  const children = entry.children.map(buildTocEntry).filter((item): item is DataNode => item != null);
  const isTopLevelItem = entry.node.node_type === 'item' && entry.node.parent_id == null;
  const belongsInToc = TOC_TYPES.has(entry.node.node_type)
    && (entry.node.node_type !== 'item' || isTopLevelItem);
  if (!belongsInToc) {
    return children.length === 1 ? children[0] : null;
  }
  return {
    key: String(entry.node.id),
    title: tocTitle(entry),
    children: children.length ? children : undefined,
  };
}

function flattenToc(entries: DocumentReadingNode[]): DataNode[] {
  const result: DataNode[] = [];
  entries.forEach((entry) => {
    const item = buildTocEntry(entry);
    if (item) result.push(item);
    else entry.children.forEach((child) => {
      const childItem = buildTocEntry(child);
      if (childItem) result.push(childItem);
    });
  });
  return result;
}

/**
 * Parser 负责拆细，Reader 负责聚合：所有原始节点一一保留，只改变阅读分区和呈现层级。
 */
export function buildDocumentReadingView(nodes: DocumentNode[]): DocumentReadingView {
  const sorted = [...nodes].sort((left, right) => left.order_no - right.order_no || left.id - right.id);
  const knownIds = new Set(sorted.map((node) => node.id));
  const childrenByParent = new Map<number, DocumentNode[]>();
  const roots: DocumentNode[] = [];

  sorted.forEach((node) => {
    if (node.parent_id != null && knownIds.has(node.parent_id)) {
      const siblings = childrenByParent.get(node.parent_id) ?? [];
      siblings.push(node);
      childrenByParent.set(node.parent_id, siblings);
    } else {
      roots.push(node);
    }
  });

  const readingRoots = roots.map((root) => buildReadingNode(root, childrenByParent));
  const firstBodyIndex = readingRoots.findIndex((entry) => READING_ANCHOR_TYPES.has(entry.node.node_type));
  if (firstBodyIndex < 0) {
    return { frontMatter: readingRoots, body: [], closingMatter: [], toc: [] };
  }

  const lastContentIndex = readingRoots.reduce(
    (lastIndex, entry, index) => CLOSING_TYPES.has(entry.node.node_type) ? lastIndex : index,
    firstBodyIndex,
  );
  const frontMatter = readingRoots.slice(0, firstBodyIndex);
  const body = readingRoots.slice(firstBodyIndex, lastContentIndex + 1);
  const closingMatter = readingRoots.slice(lastContentIndex + 1);

  return {
    frontMatter,
    body,
    closingMatter,
    toc: flattenToc(body),
  };
}
