/**
 * 文件说明：提供面向普通用户的制度搜索门户，统一管理搜索、筛选、排序、分页和 URL 状态恢复。
 * 页面仅调用 Platform Document API，不展示或访问 RAG 内部技术数据。
 */
import {
  BankOutlined,
  CalendarOutlined,
  EllipsisOutlined,
  FilePdfOutlined,
  LinkOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Input,
  Pagination,
  Popover,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { MenuProps, TableColumnsType } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { getDocumentFacets, listDocuments, type DocumentFilters } from '../api/documents';
import { UiIcon } from '../components/UiIcon';
import type { DocumentFacetsResponse, DocumentListResponse, DocumentSummary } from '../types/documents';
import { documentStatusClass } from '../utils/documentStatus';
import { documentPdfUrl } from '../utils/pdf';

const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_SORT: Pick<DocumentFilters, 'sort_by' | 'sort_order'> = {
  sort_by: 'publish_date',
  sort_order: 'desc',
};
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const SORT_OPTIONS = [
  { key: 'publish_date:desc', label: '最新发布', sort_by: 'publish_date', sort_order: 'desc' },
  { key: 'publish_date:asc', label: '最早发布', sort_by: 'publish_date', sort_order: 'asc' },
  { key: 'updated_at:desc', label: '最近更新', sort_by: 'updated_at', sort_order: 'desc' },
  { key: 'title:asc', label: '制度名称', sort_by: 'title', sort_order: 'asc' },
  { key: 'document_code:asc', label: '文号', sort_by: 'document_code', sort_order: 'asc' },
  { key: 'issuer:asc', label: '发布机构', sort_by: 'issuer', sort_order: 'asc' },
  { key: 'status:asc', label: '状态', sort_by: 'status', sort_order: 'asc' },
  { key: 'responsibility_department:asc', label: '责任部门', sort_by: 'responsibility_department', sort_order: 'asc' },
] as const;

type SortBy = NonNullable<DocumentFilters['sort_by']>;
type SortOrder = NonNullable<DocumentFilters['sort_order']>;
type DocumentPageFilters = Required<Omit<DocumentFilters, 'query_scope'>>;

const SORTABLE_FIELDS: readonly SortBy[] = [
  'updated_at',
  'title',
  'document_code',
  'issuer',
  'publish_date',
  'effective_date',
  'status',
  'responsibility_department',
];
const COLUMN_SORT_LABELS: Record<SortBy, string> = {
  updated_at: '最近更新',
  title: '制度名称',
  document_code: '文号',
  issuer: '发布机构',
  publish_date: '发布日期',
  effective_date: '生效日期',
  status: '状态',
  responsibility_department: '责任部门',
};

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function filtersFromParams(params: URLSearchParams): DocumentPageFilters {
  const sortByParam = params.get('sort_by');
  const sortOrderParam = params.get('sort_order');
  const requestedSortBy = SORTABLE_FIELDS.includes(sortByParam as SortBy) ? sortByParam as SortBy : DEFAULT_SORT.sort_by!;
  const requestedSortOrder = sortOrderParam === 'asc' || sortOrderParam === 'desc' ? sortOrderParam : DEFAULT_SORT.sort_order!;
  const requestedPageSize = positiveInteger(params.get('page_size'), DEFAULT_PAGE_SIZE);
  return {
    keyword: params.get('q') ?? params.get('keyword') ?? '',
    status: params.get('status') ?? '',
    issuer: params.get('issuer') ?? '',
    department: params.get('department') ?? '',
    publish_date_from: params.get('publish_date_from') ?? '',
    publish_date_to: params.get('publish_date_to') ?? '',
    sort_by: requestedSortBy,
    sort_order: requestedSortOrder,
    page: positiveInteger(params.get('page'), 1),
    page_size: PAGE_SIZE_OPTIONS.includes(requestedPageSize) ? requestedPageSize : DEFAULT_PAGE_SIZE,
  };
}

function paramsFromFilters(filters: DocumentPageFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.keyword) params.set('q', filters.keyword);
  if (filters.status) params.set('status', filters.status);
  if (filters.issuer) params.set('issuer', filters.issuer);
  if (filters.department) params.set('department', filters.department);
  if (filters.publish_date_from) params.set('publish_date_from', filters.publish_date_from);
  if (filters.publish_date_to) params.set('publish_date_to', filters.publish_date_to);
  if (filters.sort_by !== DEFAULT_SORT.sort_by || filters.sort_order !== DEFAULT_SORT.sort_order) {
    params.set('sort_by', filters.sort_by);
    params.set('sort_order', filters.sort_order);
  }
  if (filters.page > 1) params.set('page', String(filters.page));
  if (filters.page_size !== DEFAULT_PAGE_SIZE) params.set('page_size', String(filters.page_size));
  return params;
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

function filterOptions(values: string[]) {
  return values.map((value) => ({ value, label: value }));
}

export function DocumentsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams]);
  const [data, setData] = useState<DocumentListResponse | null>(null);
  const [facets, setFacets] = useState<DocumentFacetsResponse>({ statuses: [], issuers: [], departments: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [draftKeyword, setDraftKeyword] = useState(filters.keyword);
  const [dateOpen, setDateOpen] = useState(false);
  const [draftDateFrom, setDraftDateFrom] = useState(filters.publish_date_from);
  const [draftDateTo, setDraftDateTo] = useState(filters.publish_date_to);

  useEffect(() => {
    setDraftKeyword(filters.keyword);
  }, [filters.keyword]);

  useEffect(() => {
    getDocumentFacets()
      .then(setFacets)
      .catch(() => setFacets({ statuses: [], issuers: [], departments: [] }));
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    listDocuments(filters)
      .then(setData)
      .catch((requestError: unknown) => {
        setData(null);
        setError(requestError instanceof Error ? requestError.message : '制度列表加载失败');
      })
      .finally(() => setLoading(false));
  }, [filters, refreshKey]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') setRefreshKey((key) => key + 1);
    };
    const timer = window.setInterval(refreshWhenVisible, 30000);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    window.addEventListener('focus', refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      window.removeEventListener('focus', refreshWhenVisible);
    };
  }, []);

  const writeFilters = (next: DocumentPageFilters) => setSearchParams(paramsFromFilters(next));
  const updateFilters = (patch: Partial<DocumentPageFilters>, resetPage = true) => {
    writeFilters({ ...filters, ...patch, page: resetPage ? 1 : (patch.page ?? filters.page) });
  };
  const currentSort = SORT_OPTIONS.find(
    (option) => option.sort_by === filters.sort_by && option.sort_order === filters.sort_order,
  );
  const currentSortLabel = currentSort?.label
    ?? `${COLUMN_SORT_LABELS[filters.sort_by]}（${filters.sort_order === 'asc' ? '升序' : '降序'}）`;
  const tableSortOrder = (field: SortBy) => (
    filters.sort_by === field ? (filters.sort_order === 'asc' ? 'ascend' : 'descend') : null
  );

  const applySearch = (value: string) => {
    const keyword = value.trim();
    setDraftKeyword(keyword);
    updateFilters({ keyword });
  };

  const documentDetailUrl = (documentId: number) => {
    const params = new URLSearchParams();
    if (filters.keyword) params.set('highlight', filters.keyword);
    const query = params.toString();
    return `/documents/${documentId}${query ? `?${query}` : ''}`;
  };

  const openDateFilter = (open: boolean) => {
    setDateOpen(open);
    if (open) {
      setDraftDateFrom(filters.publish_date_from);
      setDraftDateTo(filters.publish_date_to);
    }
  };

  const applyDateFilter = () => {
    if (draftDateFrom && draftDateTo && draftDateFrom > draftDateTo) {
      message.warning('发布日期起始时间不能晚于结束时间');
      return;
    }
    updateFilters({ publish_date_from: draftDateFrom, publish_date_to: draftDateTo });
    setDateOpen(false);
  };

  const activeChips = [
    filters.keyword ? { key: 'keyword', label: `关键词：${filters.keyword}`, clear: () => updateFilters({ keyword: '' }) } : null,
    filters.status ? { key: 'status', label: filters.status, clear: () => updateFilters({ status: '' }) } : null,
    filters.issuer ? { key: 'issuer', label: filters.issuer, clear: () => updateFilters({ issuer: '' }) } : null,
    filters.department ? { key: 'department', label: filters.department, clear: () => updateFilters({ department: '' }) } : null,
    filters.publish_date_from || filters.publish_date_to ? {
      key: 'publish_date',
      label: `发布日期：${filters.publish_date_from || '不限'} 至 ${filters.publish_date_to || '不限'}`,
      clear: () => updateFilters({ publish_date_from: '', publish_date_to: '' }),
    } : null,
  ].filter((item): item is { key: string; label: string; clear: () => void } => item != null);

  const handleRowAction = async (key: string, record: DocumentSummary) => {
    if (key === 'pdf') {
      window.open(documentPdfUrl(record.id), '_blank', 'noopener,noreferrer');
      return;
    }
    if (key === 'copy') {
      try {
        await copyToClipboard(new URL(`/documents/${record.id}`, window.location.origin).toString());
        message.success('制度链接已复制');
      } catch {
        message.error('复制失败，请重试');
      }
    }
  };

  const columns: TableColumnsType<DocumentSummary> = [
    {
      title: '制度名称',
      dataIndex: 'title',
      width: 380,
      sorter: true,
      sortOrder: tableSortOrder('title'),
      render: (title: string, record) => (
        <Tooltip title={title} placement="topLeft" mouseEnterDelay={0.5}>
          <Link className="document-title-link" to={documentDetailUrl(record.id)}>{title}</Link>
        </Tooltip>
      ),
    },
    { title: '文号', dataIndex: 'document_code', width: 170, sorter: true, sortOrder: tableSortOrder('document_code'), render: (value: string | null) => <span className="document-meta-text">{value ?? '-'}</span> },
    { title: '发布机构', dataIndex: 'issuer', width: 210, responsive: ['xl'], sorter: true, sortOrder: tableSortOrder('issuer'), render: (value: string | null) => <span className="document-meta-text">{value ?? '-'}</span> },
    { title: '发布日期', dataIndex: 'publish_date', width: 125, sorter: true, sortOrder: tableSortOrder('publish_date'), render: (value: string | null) => <span className="document-meta-text">{value ?? '-'}</span> },
    { title: '状态', dataIndex: 'status', width: 110, sorter: true, sortOrder: tableSortOrder('status'), render: (value: string) => <Tag className={`document-status-tag ${documentStatusClass(value)}`}>{value}</Tag> },
    { title: '责任部门', dataIndex: 'responsibility_department', width: 190, responsive: ['lg'], sorter: true, sortOrder: tableSortOrder('responsibility_department'), render: (value: string | null) => <span className="document-meta-text">{value ?? '-'}</span> },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, record) => {
        const menuItems: MenuProps['items'] = [
          ...(record.has_pdf ? [{ key: 'pdf', icon: <UiIcon icon={FilePdfOutlined} />, label: '查看PDF' }] : []),
          { key: 'copy', icon: <UiIcon icon={LinkOutlined} />, label: '复制链接' },
        ];
        return (
          <Space size={0} className="document-row-actions">
            <Button type="link" size="small" onClick={() => navigate(documentDetailUrl(record.id))}>查看正文</Button>
            <Tooltip title="更多操作">
              <Dropdown menu={{ items: menuItems, onClick: ({ key }) => void handleRowAction(key, record) }} trigger={['click']}>
                <Button type="text" size="small" icon={<UiIcon icon={EllipsisOutlined} />} aria-label="更多操作" />
              </Dropdown>
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  const dateLabel = filters.publish_date_from || filters.publish_date_to
    ? `${filters.publish_date_from || '不限'} 至 ${filters.publish_date_to || '不限'}`
    : '发布日期：不限';

  return (
    <div className="page-stack document-library-page">
      <header className="document-library-header">
        <Typography.Title level={2} className="page-heading">制度库</Typography.Title>
        <Typography.Text type="secondary">查询当前有效制度及历史制度</Typography.Text>
      </header>

      <Input.Search
        className="document-library-search"
        size="large"
        allowClear
        enterButton="搜索"
        maxLength={200}
        placeholder="搜索制度名称、文号或正文内容……"
        value={draftKeyword}
        onChange={(event) => {
          const value = event.target.value;
          setDraftKeyword(value);
          if (!value && filters.keyword) updateFilters({ keyword: '' });
        }}
        onSearch={applySearch}
      />

      <section className="document-core-filters" aria-label="制度筛选">
        <Select
          className="document-core-filter"
          allowClear
          prefix={<UiIcon icon={SafetyCertificateOutlined} />}
          placeholder="状态：全部"
          value={filters.status || undefined}
          options={filterOptions(facets.statuses)}
          onChange={(status) => updateFilters({ status: status ?? '' })}
        />
        <Select
          className="document-core-filter document-core-filter-wide"
          allowClear
          showSearch
          optionFilterProp="label"
          prefix={<UiIcon icon={BankOutlined} />}
          placeholder="发布机构：全部"
          value={filters.issuer || undefined}
          options={filterOptions(facets.issuers)}
          onChange={(issuer) => updateFilters({ issuer: issuer ?? '' })}
        />
        <Select
          className="document-core-filter document-core-filter-wide"
          allowClear
          showSearch
          optionFilterProp="label"
          prefix={<UiIcon icon={TeamOutlined} />}
          placeholder="责任部门：全部"
          value={filters.department || undefined}
          options={filterOptions(facets.departments)}
          onChange={(department) => updateFilters({ department: department ?? '' })}
        />
        <Popover
          open={dateOpen}
          onOpenChange={openDateFilter}
          trigger="click"
          placement="bottomLeft"
          content={(
            <div className="document-date-filter">
              <Typography.Text strong>发布日期范围</Typography.Text>
              <Space align="center">
                <Input aria-label="发布日期从" type="date" value={draftDateFrom} onChange={(event) => setDraftDateFrom(event.target.value)} />
                <Typography.Text type="secondary">至</Typography.Text>
                <Input aria-label="发布日期至" type="date" value={draftDateTo} onChange={(event) => setDraftDateTo(event.target.value)} />
              </Space>
              <Space className="document-date-actions">
                <Button onClick={() => { setDraftDateFrom(''); setDraftDateTo(''); }}>清空</Button>
                <Button type="primary" onClick={applyDateFilter}>应用</Button>
              </Space>
            </div>
          )}
        >
          <Button className="document-date-trigger" icon={<UiIcon icon={CalendarOutlined} />}>{dateLabel}</Button>
        </Popover>
      </section>

      {activeChips.length ? (
        <div className="document-active-filters">
          <Typography.Text type="secondary">当前筛选：</Typography.Text>
          <Space size={[6, 8]} wrap>
            {activeChips.map((chip) => (
              <Tag
                key={chip.key}
                closable
                className="document-filter-chip"
                onClose={(event) => { event.preventDefault(); chip.clear(); }}
              >
                {chip.label}
              </Tag>
            ))}
          </Space>
          <Button type="link" size="small" onClick={() => setSearchParams({})}>清除全部</Button>
        </div>
      ) : null}

      <section className="document-results" aria-label="制度查询结果">
        <div className="document-results-toolbar">
          <Typography.Text>找到 <strong>{data?.total ?? 0}</strong> 项制度</Typography.Text>
          <Space size={4}>
            <Dropdown
              trigger={['click']}
              menu={{
                selectedKeys: currentSort ? [currentSort.key] : [],
                items: SORT_OPTIONS.map((option) => ({ key: option.key, label: option.label })),
                onClick: ({ key }) => {
                  const selected = SORT_OPTIONS.find((option) => option.key === key);
                  if (selected) updateFilters({ sort_by: selected.sort_by as SortBy, sort_order: selected.sort_order as SortOrder });
                },
              }}
            >
              <Button type="text">排序：{currentSortLabel}</Button>
            </Dropdown>
            <Tooltip title="刷新结果">
              <Button type="text" icon={<UiIcon icon={ReloadOutlined} />} aria-label="刷新结果" loading={loading} onClick={() => setRefreshKey((key) => key + 1)} />
            </Tooltip>
          </Space>
        </div>

        {error ? (
          <Alert
            className="document-results-error"
            type="error"
            showIcon
            message="制度列表加载失败"
            description={error}
            action={<Button size="small" onClick={() => setRefreshKey((key) => key + 1)}>重试</Button>}
          />
        ) : (
          <>
            <Table<DocumentSummary>
              className="document-library-table"
              rowKey="id"
              loading={loading}
              dataSource={data?.items ?? []}
              columns={columns}
              scroll={{ x: 1080 }}
              pagination={false}
              sortDirections={['ascend', 'descend', 'ascend']}
              showSorterTooltip={{ target: 'sorter-icon' }}
              onChange={(_, __, sorter) => {
                const selectedSorter = Array.isArray(sorter) ? sorter[0] : sorter;
                const field = selectedSorter.field;
                if (selectedSorter.order && typeof field === 'string' && SORTABLE_FIELDS.includes(field as SortBy)) {
                  updateFilters({
                    sort_by: field as SortBy,
                    sort_order: selectedSorter.order === 'ascend' ? 'asc' : 'desc',
                  });
                }
              }}
              locale={{ emptyText: <Empty description="没有符合条件的制度，请调整搜索或筛选条件" /> }}
            />
            <div className="document-pagination">
              <Pagination
                current={data?.page ?? filters.page}
                pageSize={data?.page_size ?? filters.page_size}
                total={data?.total ?? 0}
                showSizeChanger
                pageSizeOptions={PAGE_SIZE_OPTIONS}
                showTotal={(total) => `共 ${total} 项`}
                onChange={(page, pageSize) => updateFilters({ page, page_size: pageSize }, false)}
              />
            </div>
          </>
        )}
      </section>
    </div>
  );
}
