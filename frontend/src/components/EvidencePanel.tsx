/**
 * 文件说明：展示单条公开Citation证据快照，并提供相关证据切换、正文定位和PDF查看入口。
 */
import {
  CloseOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { Button, Collapse, Empty, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { CitationSnapshot } from '../types/chat';
import { documentPdfUrl } from '../utils/pdf';
import { UiIcon } from './UiIcon';
import { documentStatusLabel } from '../utils/documentStatus';

interface EvidencePanelProps {
  citation?: CitationSnapshot | null;
  citations?: CitationSnapshot[];
  relatedCitations?: CitationSnapshot[];
  selectedLabel?: string | null;
  onSelect?: (citation: CitationSnapshot) => void;
  onClose?: () => void;
}

function normalizeLabel(label: string): string {
  return label.replace(/^\[|\]$/g, '');
}

function targetParams(item: CitationSnapshot): URLSearchParams {
  const params = new URLSearchParams({
    evidence: normalizeLabel(item.label),
    evidence_uid: item.evidence_uid,
    parse_run_id: String(item.parse_run_id),
  });
  if (item.primary_node_id != null) params.set('node', String(item.primary_node_id));
  if (item.page_start != null) params.set('page', String(item.page_start));
  return params;
}

function pageText(item: CitationSnapshot): string {
  if (item.page_start == null) return '未标注';
  if (item.page_end != null && item.page_end !== item.page_start) {
    return `第${item.page_start}—${item.page_end}页`;
  }
  return `第${item.page_start}页`;
}

export function EvidencePanel({
  citation,
  citations = [],
  relatedCitations,
  selectedLabel,
  onSelect,
  onClose,
}: EvidencePanelProps) {
  const navigate = useNavigate();
  const initial = citation
    ?? citations.find((item) => normalizeLabel(item.label) === normalizeLabel(selectedLabel ?? ''))
    ?? citations[0]
    ?? null;
  const [internalCitation, setInternalCitation] = useState<CitationSnapshot | null>(initial);

  useEffect(() => {
    if (citation) setInternalCitation(citation);
  }, [citation]);

  const activeCitation = citation ?? internalCitation;
  const related = relatedCitations ?? citations;

  if (!activeCitation) {
    return (
      <div className="evidence-panel">
        <header className="evidence-panel-header">
          <Typography.Title level={4}>证据详情</Typography.Title>
        </header>
        <div className="evidence-panel-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="点击回答中的引用依据查看证据"
          />
        </div>
      </div>
    );
  }

  const selectEvidence = (item: CitationSnapshot) => {
    setInternalCitation(item);
    onSelect?.(item);
  };

  return (
    <div className="evidence-panel">
      <header className="evidence-panel-header">
        <Typography.Title level={4}>证据详情</Typography.Title>
        {onClose ? (
          <Button
            type="text"
            shape="circle"
            aria-label="关闭证据详情"
            icon={<UiIcon icon={CloseOutlined} />}
            onClick={onClose}
          />
        ) : null}
      </header>

      <div className="evidence-panel-scroll">
        <section className="evidence-identity">
          <Typography.Title level={4}>《{activeCitation.document_title}》</Typography.Title>
          <Typography.Text className="evidence-path">
            {activeCitation.path_text ?? '未标注条款路径'}
          </Typography.Text>
        </section>

        <section className="evidence-original">
          <Typography.Text strong>原文</Typography.Text>
          <blockquote>{activeCitation.quote}</blockquote>
          {activeCitation.truncated ? (
            <Typography.Text type="secondary">当前内容为回答时保存的节选快照。</Typography.Text>
          ) : null}
        </section>

        <section className="evidence-source">
          <Typography.Text strong>来源信息</Typography.Text>
          <dl className="evidence-metadata">
            <div><dt>制度状态</dt><dd><Tag>{documentStatusLabel(activeCitation.document_status || 'unknown')}</Tag><Typography.Text type="secondary">回答时引用快照的状态</Typography.Text></dd></div>
            <div><dt>制度文号</dt><dd>{activeCitation.document_code ?? '未标注文号'}</dd></div>
            <div><dt>所属章节</dt><dd>{activeCitation.path_text ?? '未标注'}</dd></div>
            <div><dt>页码位置</dt><dd>{pageText(activeCitation)}</dd></div>
            <div><dt>来源标识</dt><dd>{activeCitation.source_reference || '未标注'}</dd></div>
          </dl>
          <div className="evidence-buttons">
            <Button
              type="primary"
              icon={<UiIcon icon={FileTextOutlined} />}
              onClick={() => navigate(`/documents/${activeCitation.document_id}?${targetParams(activeCitation).toString()}`)}
            >
              定位制度正文
            </Button>
            {activeCitation.page_start != null ? (
              <Button
                icon={<UiIcon icon={FilePdfOutlined} />}
                href={documentPdfUrl(activeCitation.document_id, activeCitation.page_start)}
                target="_blank"
                rel="noreferrer"
              >
                查看PDF
              </Button>
            ) : null}
          </div>
        </section>

        <Collapse
          ghost
          size="small"
          className="evidence-technical"
          items={[{
            key: 'snapshot',
            label: '证据快照详情',
            children: (
              <dl className="evidence-metadata technical-details">
                <div><dt>document_id</dt><dd>{activeCitation.document_id}</dd></div>
                <div><dt>primary_node_id</dt><dd>{activeCitation.primary_node_id ?? '—'}</dd></div>
                <div><dt>parse_run_id</dt><dd>{activeCitation.parse_run_id}</dd></div>
                <div><dt>chunk_run_id</dt><dd>{activeCitation.chunk_run_id}</dd></div>
                <div><dt>index_run_id</dt><dd>{activeCitation.index_run_id}</dd></div>
                <div><dt>chunk_id</dt><dd>{activeCitation.chunk_id}</dd></div>
                <div><dt>Citation版本</dt><dd>{activeCitation.citation_version}</dd></div>
                <div><dt>证据标识版本</dt><dd>{activeCitation.evidence_uid_version}</dd></div>
                <div><dt>证据快照哈希</dt><dd>{activeCitation.snapshot_hash}</dd></div>
              </dl>
            ),
          }]}
        />

        {related.length > 1 ? (
          <section className="related-evidence">
            <Typography.Text strong>相关证据</Typography.Text>
            <div className="related-evidence-list">
              {related
                .filter((item) => item.evidence_uid !== activeCitation.evidence_uid)
                .map((item) => (
                  <button
                    key={item.evidence_uid}
                    type="button"
                    className="related-evidence-item"
                    onClick={() => selectEvidence(item)}
                  >
                    <span className="related-label">[{normalizeLabel(item.label)}]</span>
                    <span>
                      <strong>《{item.document_title}》</strong>
                      <small>{item.path_text ?? item.source_reference}</small>
                    </span>
                    <UiIcon icon={RightOutlined} />
                  </button>
                ))}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
