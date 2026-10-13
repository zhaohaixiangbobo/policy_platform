/** 文件说明：配套资料库；十列案例导入、三字段图片、版本管理和受控图片查看。 */
import { FileTextOutlined, FilterOutlined, PictureOutlined, ShareAltOutlined, UploadOutlined, ImportOutlined, ReloadOutlined, EditOutlined, DownOutlined, DownloadOutlined, FullscreenOutlined, TagsOutlined, SafetyCertificateOutlined, ReadOutlined } from '@ant-design/icons';
import { Alert, App, Button, Card, Checkbox, Drawer, Dropdown, Empty, Form, Image, Input, Modal, Pagination, Select, Space, Spin, Table, Tabs, Tag, Typography, Upload } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';
import { confirmCases, emptyImageFields, materialTags, getMaterial, listMaterials, materialAction, previewCases, saveMaterial, uploadMaterialImage } from '../api/materials';
import type { ImportPreview, MaterialFields, ImageFields, MaterialItem, MaterialsResult } from '../api/materials';
import '../styles/materials.css';

const states: Record<string, string> = { DRAFT: '草稿', PUBLISHED: '已发布', OFFLINE: '已下架', SUPERSEDED: '历史版本' };
const initialFilters = { q: '', kind: '', state: 'PUBLISHED', domain: '', sort: 'updated', page: '1' };

function EditFields({ kind }: { kind: 'CASE' | 'IMAGE' }) {
  return <>
    <Form.Item name="title" label="资料标题" rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>
    {kind === 'IMAGE' ? <>
      <Form.Item name="tags" label="标签 / 关键词" rules={[{ required: true, type: 'array', min: 1 }]}><Select mode="tags" tokenSeparators={['；', ';']} /></Form.Item>
      <Form.Item name="summary" label="简介" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={4} maxLength={10000} /></Form.Item>
    </> : <>
      <div className="material-form-grid">{[['person_category', '人员类别'], ['position', '职务/岗位'], ['rank', '职级/岗级'], ['political_status', '政治面貌'], ['age', '涉事年龄']].map(([key, label]) =>
        <Form.Item key={key} name={key} label={label}><Input maxLength={1000} /></Form.Item>)}</div>
      <Form.Item name="domains" label="涉及领域"><Select mode="tags" tokenSeparators={['；', ';']} /></Form.Item>
      <Form.Item name="problem_types" label="问题性质"><Select mode="tags" tokenSeparators={['；', ';']} /></Form.Item>
      <Form.Item name="outcome" label="处理结果"><Input.TextArea rows={4} placeholder="留空表示未公布" /></Form.Item>
      <Form.Item name="original" label="案情描述（原文保留）"><Input.TextArea rows={6} disabled /></Form.Item>
    </>}
    <Typography.Paragraph type="secondary">平台内具备资料读取权限的用户可见，发布前请核对人员信息。</Typography.Paragraph>
  </>;
}

const caseSections = [
  { key: 'info', label: '人员信息' },
  { key: 'problems', label: '问题性质' }, { key: 'outcome', label: '处理结果' }, { key: 'original', label: '案情描述' },
];

function MaterialSection({ section, title, icon = FileTextOutlined, tone = 'blue', children }: {
  section: string; title: string; icon?: unknown; tone?: string; children: ReactNode;
}) {
  return <section id={`material-section-${section}`} className={`material-detail-section is-${section}`}>
    <h3><UiIcon icon={icon} className={`material-section-icon is-${tone}`} />{title}</h3>
    {children}
  </section>;
}

function MaterialInfo({ detail }: { detail: MaterialItem }) {
  const f = detail.fields;
  const entries = detail.kind === 'CASE' ? [
    ['人员类别', f.person_category], ['职务/岗位', f.position], ['职级/岗级', f.rank],
    ['政治面貌', f.political_status], ['涉事年龄', f.age], ['涉及领域', f.domains?.join('、')],
  ] : [['标签 / 关键词', f.tags?.join('、')]];
  return <dl className={`material-info-grid${detail.kind === 'IMAGE' ? ' is-compact' : ''}`}>
    {entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '未填写'}</dd></div>)}
  </dl>;
}

/** 流程图默认完整适配内容区；精细缩放交给全屏查看器，避免正文预览被工具栏挤占。 */
function MaterialImageViewer({ detail }: { detail: MaterialItem }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [naturalWidth, setNaturalWidth] = useState(detail.file?.width || 0);
  const [naturalHeight, setNaturalHeight] = useState(detail.file?.height || 0);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [previewOpen, setPreviewOpen] = useState(false);
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const measure = () => setViewportWidth(node.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const fitScale = naturalWidth && viewportWidth ? Math.min(1, Math.max(1, viewportWidth - 40) / naturalWidth) : 1;
  return <div className="material-image-viewer">
    <div className="material-image-toolbar" aria-label="流程图查看工具">
      <h3><UiIcon icon={PictureOutlined} className="material-section-icon" />流程图预览</h3>
      <Space size={8}>
        <Button size="small" disabled={!ready} icon={<UiIcon icon={FullscreenOutlined} />} onClick={() => setPreviewOpen(true)}>全屏查看</Button>
        <Button size="small" disabled={!ready} icon={<UiIcon icon={DownloadOutlined} />} href={ready ? detail.file_url || undefined : undefined} download={detail.file?.filename || `${detail.fields.title}.png`}>下载</Button>
      </Space>
    </div>
    <div className="material-image-viewport" ref={viewport} tabIndex={0} aria-label="流程图图片，可滚动查看">
      {!detail.file_url ? <Empty description="该资料暂无可查看的图片" /> : failed ? <Alert type="warning" showIcon message="图片加载失败" description="请确认访问权限或稍后重试。" action={<Button size="small" onClick={() => { setFailed(false); setReady(false); setRetry((n) => n + 1); }}>重试</Button>} /> : <>
        {!ready && <div className="material-image-loading"><Spin tip="正在加载图片"><div /></Spin></div>}
        <div className="material-image-canvas" style={{ width: naturalWidth ? Math.max(viewportWidth, naturalWidth * fitScale + 40) : '100%' }}>
          <Image key={retry} src={detail.file_url} alt={detail.fields.title} width={naturalWidth ? naturalWidth * fitScale : '100%'}
            onLoad={(e) => { setNaturalWidth(e.currentTarget.naturalWidth); setNaturalHeight(e.currentTarget.naturalHeight); setReady(true); }}
            onError={() => { setFailed(true); setReady(false); setPreviewOpen(false); }}
            preview={{ visible: previewOpen, onVisibleChange: setPreviewOpen, rootClassName: 'material-image-preview', mask: '全屏查看' }} />
        </div>
      </>}
    </div>
    <div className="material-image-caption"><span>{detail.file?.filename || '流程图 / 图片'}</span>{naturalWidth > 0 && <span>{naturalWidth} × {naturalHeight} px</span>}</div>
  </div>;
}

function MaterialDetailReading({ detail }: { detail: MaterialItem }) {
  const scrollArea = useRef<HTMLDivElement>(null);
  const [activeSection, setActiveSection] = useState('info');
  const jumpTo = (key: string) => {
    const root = scrollArea.current;
    const target = root?.querySelector<HTMLElement>(`#material-section-${key}`);
    if (root && target) {
      setActiveSection(key);
      root.scrollTo({ top: root.scrollTop + target.getBoundingClientRect().top - root.getBoundingClientRect().top - 20, behavior: 'smooth' });
    }
  };
  const trackSection = () => {
    const root = scrollArea.current;
    if (!root) return;
    // 原文较短时无法滚到容器顶部，到达底部仍应正确高亮最后一节。
    if (root.scrollHeight > root.clientHeight && root.scrollTop + root.clientHeight >= root.scrollHeight - 2) {
      setActiveSection('original');
      return;
    }
    const current = [...caseSections].reverse().find(({ key }) => {
      const target = root.querySelector<HTMLElement>(`#material-section-${key}`);
      return target && target.getBoundingClientRect().top <= root.getBoundingClientRect().top + 40;
    });
    setActiveSection(current?.key || 'info');
  };
  return <>
    {detail.kind === 'CASE' && <nav className="material-detail-nav" aria-label="案例内容导航">{caseSections.map(({ key, label }) =>
      <button key={key} type="button" className={activeSection === key ? 'is-active' : ''} aria-current={activeSection === key ? 'location' : undefined} onClick={() => jumpTo(key)}>{label}</button>
    )}</nav>}
    <div ref={scrollArea} className={`material-detail-scroll${detail.kind === 'IMAGE' ? ' is-image' : ''}`} onScroll={detail.kind === 'CASE' ? trackSection : undefined}>
      {detail.kind === 'CASE' ? <div className="material-case-sections">
        <MaterialSection section="info" title="人员信息"><MaterialInfo detail={detail} /></MaterialSection>
        <MaterialSection section="problems" title="问题性质" icon={TagsOutlined} tone="purple"><p className="material-text">{(detail.fields.problem_types ?? []).join('、') || '未填写'}</p></MaterialSection>
        <MaterialSection section="outcome" title="处理结果" icon={SafetyCertificateOutlined} tone="green"><p className="material-text">{detail.fields.outcome || '未公布'}</p></MaterialSection>
        <MaterialSection section="original" title="案情描述" icon={ReadOutlined}><div className="material-original">{detail.fields.original || '未填写'}</div>
          {detail.provenance?.filename && <p className="material-provenance">导入来源：{detail.provenance.filename} / {detail.provenance.sheet} / 第{detail.provenance.row}行</p>}
        </MaterialSection>
        <Alert type="info" showIcon message="案例仅供学习参考，不替代制度依据或一般处理标准。" />
      </div> : <div className="material-image-layout">
        <section id="material-section-image" className="material-detail-section is-image"><MaterialImageViewer detail={detail} /></section>
        <aside className="material-image-sidebar" aria-label="流程图资料信息">
          <MaterialSection section="info" title="资料信息"><MaterialInfo detail={detail} /></MaterialSection>
          <MaterialSection section="summary" title="内容简介"><p className="material-text">{detail.fields.summary || '未填写'}</p></MaterialSection>
        </aside>
      </div>}
    </div>
  </>;
}

export function MaterialsPage() {
  const { user } = useAuth();
  const manage = !!user?.permissions.includes('material.manage');
  const allowed = !!user?.permissions.includes('material.read');
  const { message, modal } = App.useApp();
  const [filters, setFilters] = useState(initialFilters);
  const [search, setSearch] = useState('');
  const [data, setData] = useState<MaterialsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [detail, setDetail] = useState<MaterialItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [editForm] = Form.useForm<MaterialFields>();
  const [imageForm] = Form.useForm<ImageFields>();
  const listRequest = useRef(0);
  const detailRequest = useRef(0);

  const refresh = useCallback(async () => {
    if (!allowed) return;
    const request = ++listRequest.current;
    setLoading(true); setError('');
    try { const result = await listMaterials(filters); if (request === listRequest.current) { setData(result); setSelected([]); } }
    catch (e) { if (request === listRequest.current) setError((e as Error).message); }
    finally { if (request === listRequest.current) setLoading(false); }
  }, [allowed, filters]);
  useEffect(() => { void refresh(); return () => { listRequest.current++; }; }, [refresh]);
  const filter = (key: string, value: string) => setFilters((f) => ({ ...f, [key]: value, page: '1' }));
  const openDetail = async (id: string, revision?: string) => {
    const request = ++detailRequest.current;
    setDetailOpen(true); setDetailLoading(true); setEditing(false); setDetail(null);
    try { const result = await getMaterial(id, revision); if (request === detailRequest.current) setDetail(result); }
    catch (e) { if (request === detailRequest.current) { void message.error((e as Error).message); setDetailOpen(false); } }
    finally { if (request === detailRequest.current) setDetailLoading(false); }
  };
  const act = (action: 'PUBLISH' | 'OFFLINE', items: MaterialItem[]) => {
    modal.confirm({
      title: action === 'PUBLISH' ? `确认发布 ${items.length} 份资料？` : `确认下架 ${items.length} 份资料？`,
      content: action === 'PUBLISH' ? '确认内容、人员信息与可见范围正确。发布后平台内授权用户可查看；案例仅供学习参考。' : '下架后普通用户无法检索或打开资料，历史版本仍保留。',
      onOk: async () => {
        try { await materialAction(action, items); void message.success('操作完成'); await refresh(); if (detail && items.some((i) => i.id === detail.id)) await openDetail(detail.id); }
        catch (e) { void message.error((e as Error).message); throw e; }
      }
    });
  };
  const submitEdit = async () => {
    if (!detail) return;
    const values = await editForm.validateFields(); setBusy(true);
    try { const result = await saveMaterial(detail, values); setDetail(result); setEditing(false); void message.success('已保存；修改发布版本时生成独立草稿'); await refresh(); }
    catch (e) { void message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const upload = async () => {
    const values = await imageForm.validateFields();
    if (!imageFile) { void message.warning('请选择PNG/JPEG图片'); return; }
    setBusy(true);
    try { const result = await uploadMaterialImage(imageFile, { ...emptyImageFields, ...values }); setUploadOpen(false); setImageFile(null); imageForm.resetFields(); void message.success('图片已保存为草稿'); setFilters({ ...initialFilters, state: 'DRAFT' }); setSearch(''); await refresh(); await openDetail(result.id); }
    catch (e) { void message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const doPreview = async () => {
    if (!excelFile) { void message.warning('请选择标准十列Excel'); return; }
    setBusy(true); setPreview(null);
    try { setPreview(await previewCases(excelFile)); }
    catch (e) { void message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const doImport = async () => {
    if (!preview) return; setBusy(true);
    try { const result = await confirmCases(preview.batch_id); void message.success(`导入${result.created}条草稿，跳过${result.skipped}条重复资料`); setImportOpen(false); setPreview(null); setFilters({ ...initialFilters, state: 'DRAFT' }); setSearch(''); }
    catch (e) { void message.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const latest = detail && (!detail.history?.length || detail.history[0].id === detail.revision_id);
  const picked = data?.items.filter((i) => selected.includes(i.id)) ?? [];
  const detailActions = detail && manage && latest && !editing ? <Space className="material-detail-actions">
    <Button type="primary" disabled={busy} icon={<UiIcon icon={EditOutlined} />} onClick={() => { editForm.resetFields(); editForm.setFieldsValue(detail.fields); setEditing(true); }}>编辑</Button>
    <Dropdown trigger={['click']} menu={{
      items: [
        { key: 'PUBLISH', label: '发布当前修订' },
        ...(detail.state === 'PUBLISHED' ? [{ key: 'OFFLINE', label: '下架资料', danger: true }] : []),
      ], onClick: ({ key }) => act(key as 'PUBLISH' | 'OFFLINE', [detail])
    }}>
      <Button disabled={busy}>更多<UiIcon icon={DownOutlined} /></Button>
    </Dropdown>
  </Space> : null;
  const versionControl = detail && manage ? <div className="material-detail-version"><span>查看版本</span>
    <Select aria-label="资料历史版本" size="small" disabled={busy || editing} value={detail.revision_id} onChange={(v) => void openDetail(detail.id, v)} options={detail.history?.map((h) => ({ value: h.id, label: `v${h.revision_no} · ${states[h.state]}` }))} />
    {!latest ? <span>当前为历史修订，仅供查看。</span> : detail.has_draft && detail.state === 'PUBLISHED' ? <span>当前展示待发布修订；读者仍查看已发布版本。</span> : null}
  </div> : null;
  if (!allowed) return <Empty description="当前账号没有配套资料读取权限" />;

  return <div className="materials-page">
    <header className="materials-header"><div><Typography.Title level={2}>配套资料库</Typography.Title><Typography.Text type="secondary">集中管理案例、流程图等配套资料，辅助制度学习与业务办理</Typography.Text></div>
      <Space wrap><Input.Search aria-label="搜索资料" placeholder="搜索标题、关键词、案情描述…" value={search} allowClear onChange={(e) => setSearch(e.target.value)} onSearch={(v) => filter('q', v)} className="materials-search" />
        {manage && <><Button type="primary" icon={<UiIcon icon={UploadOutlined} />} onClick={() => { imageForm.setFieldsValue(emptyImageFields); setImageFile(null); setUploadOpen(true); }}>上传图片</Button>
          <Button icon={<UiIcon icon={ImportOutlined} />} onClick={() => { setPreview(null); setExcelFile(null); setImportOpen(true); }}>导入案例</Button></>}
      </Space></header>
    <div className="materials-layout"><Card className="materials-filters" title={<Space><UiIcon icon={FilterOutlined} />筛选条件</Space>} extra={<Button type="text" size="small" onClick={() => { setFilters(initialFilters); setSearch(''); }}>重置</Button>}>
      <label>资料类型</label><Select aria-label="资料类型" value={filters.kind} onChange={(v) => filter('kind', v)} options={[{ value: '', label: '全部' }, { value: 'CASE', label: '案例' }, { value: 'IMAGE', label: '流程图 / 图片' }]} />
      <label>涉及领域</label><Select aria-label="涉及领域" value={filters.domain} onChange={(v) => filter('domain', v)} options={[{ value: '', label: '全部领域' }, ...(data?.domains ?? []).map((v) => ({ value: v, label: v }))]} />
      <label>发布状态</label><Select aria-label="发布状态" value={filters.state} onChange={(v) => filter('state', v)} options={manage ? [{ value: '', label: '全部状态' }, ...Object.entries(states).filter(([k]) => k !== 'SUPERSEDED').map(([value, label]) => ({ value, label }))] : [{ value: 'PUBLISHED', label: '已发布' }]} />
      {/* 资料统计：三张带图标的色块卡，分别对应全部/案例/流程图 */}
      <div className="materials-statistics"><span>资料统计</span><div>
        <div className="is-all"><UiIcon icon={FileTextOutlined} />全部资料<strong>{(data?.counts.CASE ?? 0) + (data?.counts.IMAGE ?? 0)}</strong></div>
        <div className="is-case"><UiIcon icon={FileTextOutlined} />案例<strong>{data?.counts.CASE ?? 0}</strong></div>
        <div className="is-image"><UiIcon icon={ShareAltOutlined} />流程图<strong>{data?.counts.IMAGE ?? 0}</strong></div>
      </div></div>
    </Card>
      <section className="materials-results">
        <div className="materials-toolbar"><Tabs activeKey={filters.kind} onChange={(v) => filter('kind', v)} items={[{ key: '', label: '全部资料' }, { key: 'CASE', label: `案例（${data?.counts.CASE ?? 0}）` }, { key: 'IMAGE', label: `流程图 / 图片（${data?.counts.IMAGE ?? 0}）` }]} />
          <Space><Select aria-label="排序方式" value={filters.sort} onChange={(v) => filter('sort', v)} options={[{ value: 'updated', label: '最近更新' }, { value: 'published', label: '最近发布' }, { value: 'relevance', label: '匹配优先' }]} /><Button aria-label="刷新资料" icon={<UiIcon icon={ReloadOutlined} />} onClick={() => void refresh()} /></Space></div>
        {manage && <div className="materials-batch"><Checkbox checked={!!data?.items.length && selected.length === data.items.length} indeterminate={selected.length > 0 && selected.length < (data?.items.length ?? 0)} onChange={(e) => setSelected(e.target.checked ? data?.items.map((i) => i.id) ?? [] : [])}>选择本页</Checkbox><span>已选 {selected.length} 项</span><Button size="small" disabled={!picked.length || loading} onClick={() => act('PUBLISH', picked)}>批量发布</Button><Button size="small" disabled={!picked.length || loading || picked.some((i) => i.state !== 'PUBLISHED')} onClick={() => act('OFFLINE', picked)}>批量下架</Button></div>}
        {error && <Alert type="error" showIcon message={error} />}
        <Spin spinning={loading}><div className="materials-grid">{data?.items.map((item) => <Card key={item.id} className="material-card">
          <div className="material-card-main"><div className={`material-thumbnail ${item.kind === 'CASE' ? 'is-case' : ''}`}>{item.file_url ? <Image src={item.file_url} alt={item.fields.title} preview={{ mask: '查看大图', rootClassName: 'material-image-preview' }} /> : <UiIcon icon={FileTextOutlined} />}</div>
            <div className="material-card-copy"><Space size={4} wrap><Tag color={item.kind === 'CASE' ? 'green' : 'purple'}>{item.kind === 'CASE' ? '案例' : '流程图 / 图片'}</Tag>{manage && <Tag>{states[item.state]}</Tag>}{item.has_draft && item.state !== 'DRAFT' && <Tag color="orange">有待发布修订</Tag>}</Space>
              <button className="material-title" onClick={() => void openDetail(item.id)}>{item.fields.title}</button><p>{item.preview_text}</p><div className="material-tags">{materialTags(item).slice(0, 3).map((tag) => <Tag key={tag}>{tag}</Tag>)}{materialTags(item).length > 3 && <Tag>+{materialTags(item).length - 3}</Tag>}</div>
            </div></div>{item.match_excerpt && <div className="material-match">命中片段：{item.match_excerpt}</div>}
          <footer>{manage && <Checkbox aria-label={`选择${item.fields.title}`} checked={selected.includes(item.id)} onChange={(e) => setSelected((s) => e.target.checked ? [...s, item.id] : s.filter((v) => v !== item.id))} />}<span>更新：{new Date(item.updated_at).toLocaleDateString()} · v{item.revision_no}</span><Button size="small" onClick={() => void openDetail(item.id)}>查看详情</Button></footer>
        </Card>)}</div>{!data?.items.length && !loading && <Empty description="当前条件下暂无资料" />}</Spin>
        <Pagination current={Number(filters.page)} pageSize={10} total={data?.total ?? 0} showSizeChanger={false} showTotal={(n) => `共 ${n} 份资料`} onChange={(p) => setFilters((f) => ({ ...f, page: String(p) }))} />
      </section></div>

    <Drawer title="资料详情" rootClassName="material-detail-drawer" width={detail?.kind === 'IMAGE' ? 'min(1120px, 96vw, max(52vw, 680px))' : 'min(960px, 96vw)'} open={detailOpen} onClose={() => { if (!busy) { detailRequest.current++; setDetailOpen(false); } }}>
      {detailLoading ? <div className="material-detail-loading"><Spin tip="正在加载资料"><div /></Spin></div> : detail && <div className="material-detail-shell">
        <header className="material-detail-header is-compact">
          <div className="material-detail-title-row">
            <div className="material-detail-heading">
              <Tag color={detail.kind === 'CASE' ? 'volcano' : 'green'}>{detail.kind === 'CASE' ? '案例' : '流程图 / 图片'}</Tag>
              <Typography.Title level={3}>{detail.fields.title}</Typography.Title>
            </div>
            {detailActions}
          </div>
          <div className="material-detail-meta">
            <Tag color={detail.state === 'PUBLISHED' ? 'success' : detail.state === 'DRAFT' ? 'warning' : 'default'}>{states[detail.state]}</Tag>
            <span>{detail.published_at ? `发布于 ${new Date(detail.published_at).toLocaleDateString('zh-CN')}` : '当前修订尚未发布'}</span>
            <span>更新 {new Date(detail.updated_at).toLocaleDateString('zh-CN')}</span>
            <span>v{detail.revision_no} · {states[detail.revision_state]}</span>
            {versionControl}
          </div>
        </header>
        {editing ? <div className="material-detail-scroll material-detail-edit"><Form form={editForm} disabled={busy} layout="vertical" onFinish={() => void submitEdit()}>
          <Typography.Title level={5}>编辑资料信息</Typography.Title><EditFields kind={detail.kind} />
          <div className="material-edit-actions"><Button type="primary" htmlType="submit" loading={busy}>保存草稿</Button><Button disabled={busy} onClick={() => setEditing(false)}>取消</Button></div>
        </Form></div> : <MaterialDetailReading key={detail.revision_id} detail={detail} />}
      </div>}
    </Drawer>

    <Modal title={<Space><UiIcon icon={PictureOutlined} />上传流程图 / 图片</Space>} open={uploadOpen} width={760} onCancel={() => !busy && setUploadOpen(false)} onOk={() => void upload()} confirmLoading={busy} okText="保存为草稿" destroyOnClose>
      <Upload disabled={busy} accept=".png,.jpg,.jpeg" maxCount={1} fileList={imageFile ? [{ uid: 'image', name: imageFile.name, status: 'done' }] : []} beforeUpload={(file) => { setImageFile(file); imageForm.setFieldValue('title', file.name.replace(/\.[^.]+$/, '')); return false; }} onRemove={() => { setImageFile(null); }}><Button icon={<UiIcon icon={UploadOutlined} />}>选择图片（最多10MB）</Button></Upload>
      <Typography.Paragraph type="secondary">标题默认来自文件名。不自动理解图片，请填写简介和标签 / 关键词。</Typography.Paragraph><Form form={imageForm} disabled={busy} layout="vertical" initialValues={emptyImageFields}><EditFields kind="IMAGE" /></Form>
    </Modal>
    <Modal title="导入案例 · 标准十列Excel" open={importOpen} width={980} onCancel={() => !busy && setImportOpen(false)} footer={<Space><Button disabled={busy} onClick={() => setImportOpen(false)}>取消</Button><Button loading={busy} onClick={() => void doPreview()}>预览校验</Button><Button type="primary" loading={busy} disabled={!preview || !!preview.errors || !preview.new} onClick={() => void doImport()}>确认导入草稿</Button></Space>}>
      <Typography.Paragraph>第一张工作表使用：标题、人员类别、职务/岗位、职级/岗级、政治面貌、涉事年龄、涉及领域、问题性质、处理结果、案情描述。多值用分号分隔，每批最多200行。不会再次调用模型。</Typography.Paragraph>
      <Space><Button href="/api/v1/materials/case-template">下载十列模板</Button><Upload disabled={busy} accept=".xlsx" maxCount={1} fileList={excelFile ? [{ uid: 'excel', name: excelFile.name, status: 'done' }] : []} beforeUpload={(file) => { setExcelFile(file); setPreview(null); return false; }} onRemove={() => { setExcelFile(null); setPreview(null); }}><Button>选择Excel</Button></Upload></Space>
      {preview && <><Alert type={preview.errors ? 'warning' : 'info'} showIcon message={`共${preview.total}行 · 新增${preview.new} · 重复${preview.duplicates} · 错误${preview.errors}（错误需修正后重新上传）`} /><Table size="small" rowKey="row" dataSource={preview.rows} pagination={{ pageSize: 5, showSizeChanger: false }} expandable={{ expandedRowRender: (r) => <div className="material-text"><p>涉及领域：{r.fields?.domains?.join('、')}</p><p>问题性质：{r.fields?.problem_types?.join('、')}</p>{[['person_category', '人员类别'], ['position', '职务/岗位'], ['rank', '职级/岗级'], ['political_status', '政治面貌'], ['age', '涉事年龄']].map(([key, label]) => <p key={key}>{label}：{String(r.fields?.[key as keyof MaterialFields] ?? '')}</p>)}<p>处理结果：{r.fields?.outcome || '未公布'}</p><p>原文：{r.fields?.original}</p></div> }} columns={[{ title: '原表行号', dataIndex: 'row', width: 90 }, { title: '标题', render: (_, r) => r.fields?.title || '字段错误' }, { title: '校验结果', render: (_, r) => r.error ? <Typography.Text type="danger">{r.error}</Typography.Text> : r.duplicate ? <Tag>重复，跳过</Tag> : <Tag color="green">可导入草稿</Tag> }]} /></>}
    </Modal>
  </div>;
}
