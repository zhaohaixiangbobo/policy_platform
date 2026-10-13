/** 文件说明：回答之外的实时辅助资料；失败静默降级，详情重新鉴权，不参与制度答案。 */
import { FileTextOutlined, ReadOutlined, SafetyCertificateOutlined, ApartmentOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { Button, Drawer, Image, Space, Tabs, Typography, message } from 'antd';
import { Link } from 'react-router-dom';
import { getMaterial, type MaterialItem } from '../api/materials';
import { requestJson } from '../api/httpClient';
import { UiIcon } from './UiIcon';
import '../styles/material-recommendations.css';

function CaseDetailSection({
  title,
  icon,
  tone,
  children,
}: {
  title: string;
  icon: typeof FileTextOutlined;
  tone: 'orange' | 'green' | 'blue';
  children: React.ReactNode;
}) {
  return <section className={`recommendation-case-section is-${tone}`}>
    <h3><UiIcon icon={icon} className="recommendation-case-icon" />{title}</h3>
    {children}
  </section>;
}

export function MaterialRecommendations({ query = '', endpoint, materialKind }: { query?: string; endpoint?: string; materialKind?: 'CASE' | 'IMAGE' }) {
  const [items, setItems] = useState<MaterialItem[]>([]);
  const [detail, setDetail] = useState<MaterialItem | null>(null);
  const [activeKind, setActiveKind] = useState('IMAGE');
  useEffect(() => {
    let active = true;
    setItems([]);
    setActiveKind(query.includes('案例') && !query.includes('流程') ? 'CASE' : 'IMAGE');
    if (endpoint || query.trim()) void requestJson<{ items: MaterialItem[] }>(
      endpoint || `/api/v1/materials/recommendations?${new URLSearchParams({ q: query.slice(0, 2000), ...(materialKind ? { kind: materialKind } : {}) })}`,
    ).then((result) => { if (active) setItems(result.items); }).catch(() => { });
    return () => { active = false; };
  }, [query, endpoint, materialKind]);
  async function open(item: MaterialItem) {
    try { setDetail(await getMaterial(item.id, item.revision_id)); }
    catch { message.info('资料已更新、下架或不可访问，请到配套资料库重新查询'); }
  }
  if (!items.length) return null;
  // Tab仅切换已获取的卡片，不重复请求；单类结果直接展示，不出现空页签。
  const groups = (['IMAGE', 'CASE'] as const).map((kind) => {
    const group = items.filter((item) => item.kind === kind);
    return { key: kind, label: `${kind === 'IMAGE' ? '流程图 / 图片' : '案例'}（${group.length}）`, group };
  }).filter(({ group }) => group.length > 0);
  const cards = (group: MaterialItem[]) => group.map((item) => <div key={item.id} style={{ padding: '10px 0' }}>
    <Space align="start">
      {item.file_url && <Image className="recommendation-thumbnail" preview={false} src={item.file_url} width={72} height={64} style={{ objectFit: 'contain' }} />}
      <div><Button type="link" style={{ padding: 0, height: 'auto', whiteSpace: 'normal', textAlign: 'left' }} onClick={() => void open(item)}>{item.fields.title}</Button>
        {item.match_reason && <Typography.Text type="secondary">{item.match_reason}</Typography.Text>}
        <Typography.Paragraph ellipsis={{ rows: 3 }} style={{ margin: '4px 0' }}>{item.match_excerpt ? `相关原文：${item.match_excerpt}` : `原文预览：${item.preview_text}`}</Typography.Paragraph>
      </div>
    </Space>
  </div>);
  return <section aria-label="相关配套资料" style={endpoint ? { display: 'inline-flex' } : { margin: '16px 0', padding: 16, background: '#f7f9fc', borderRadius: 12 }}>
    {endpoint ? <Space wrap>{items.map((item) => <Button key={item.id} className="learning-material-button"
      icon={<UiIcon icon={item.kind === 'IMAGE' ? ApartmentOutlined : ReadOutlined} />}
      title="辅助学习资料，不作为本题出题或评分依据" onClick={() => void open(item)}>
      {item.kind === 'IMAGE' ? '相关流程图' : '相关案例'}（1）
    </Button>)}</Space> : <>
      <Typography.Paragraph type="secondary">当前相关资料仅供辅助参考，不作为本次回答的制度依据。</Typography.Paragraph>
      {groups.length > 1 ? <Tabs size="small" activeKey={groups.some((g) => g.key === activeKind) ? activeKind : groups[0].key}
        onChange={setActiveKind} items={groups.map(({ key, label, group }) => ({ key, label, children: cards(group) }))} />
        : <><Typography.Text strong>{groups[0].label}</Typography.Text>{cards(groups[0].group)}</>}
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text type="secondary">数量为本次推荐数，每类最多2条</Typography.Text>
        <Link to="/materials">前往资料库</Link>
      </Space>
    </>}
    <Drawer
      title={detail?.fields.title}
      rootClassName="recommendation-detail-drawer"
      open={Boolean(detail)}
      onClose={() => setDetail(null)}
      width="min(760px, 96vw)"
    >
      {detail && <>
        <Typography.Paragraph type="secondary" className="recommendation-detail-meta">辅助资料 · 修订 {detail.revision_no}{endpoint ? ' · 不作为本题出题或评分依据' : ''}</Typography.Paragraph>
        {detail.kind === 'IMAGE' ? (detail.file_url
          ? <Image src={detail.file_url} width="100%" preview={{ rootClassName: 'recommendation-image-preview' }} />
          : <Typography.Text type="secondary">暂无可查看的图片</Typography.Text>) : <>
          <div className="recommendation-case-content">
            <CaseDetailSection title="人员与问题信息" icon={FileTextOutlined} tone="orange">
              {[['人员类别', detail.fields.person_category], ['职务/岗位', detail.fields.position], ['职级/岗级', detail.fields.rank], ['政治面貌', detail.fields.political_status], ['涉事年龄', detail.fields.age], ['涉及领域', detail.fields.domains?.join('、')], ['问题性质', detail.fields.problem_types?.join('、')]].map(([label, value]) => <p key={label}>{label}：{value || '未填写'}</p>)}
            </CaseDetailSection>
            <CaseDetailSection title="处理结果" icon={SafetyCertificateOutlined} tone="green">
              <p>{detail.fields.outcome || '未公布'}</p>
            </CaseDetailSection>
            <CaseDetailSection title="案情描述" icon={ReadOutlined} tone="blue">
              <div className="recommendation-case-original">{detail.fields.original || '未填写'}</div>
            </CaseDetailSection>
          </div>
        </>}
      </>}
    </Drawer>
  </section>;
}
