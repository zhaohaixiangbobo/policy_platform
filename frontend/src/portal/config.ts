/** 文件说明：门户开关、模块文案与安全站内回跳；不新增权限模型。 */
export const portalEnabled = import.meta.env.VITE_PORTAL_ENABLED !== 'false';
export const portalTitle = '天津烟草行业内部监督贯通协同工作平台';
// color/deep 为模块主色与深色渐变端；除制度管理外，其余模块 path 指向占位页。
export const portalModules = [
  { id: 'policy', title: '制度管理模块', lines: ['制度查询 · 智能解答', '学习培训 · 案例分析'], path: '/', color: '#3978ef', deep: '#1f4fd6' },
  { id: 'meetings', title: '会议管理模块', lines: ['会议计划 · 会议组织', '会议纪要 · 督办落实'], path: '/portal/modules/meetings', color: '#13aaa1', deep: '#0a8077' },
  { id: 'discipline', title: '纪检工作流程管控模块', lines: ['信访举报 · 线索处置', '案件查办 · 预警提示'], path: '/portal/modules/discipline', color: '#eb777f', deep: '#d4465b' },
  { id: 'inspection', title: '巡察工作流程管控模块', lines: ['巡察计划 · 巡察组织', '整改监督 · 成果运用'], path: '/portal/modules/inspection', color: '#8170ed', deep: '#5a45d4' },
  { id: 'supervision', title: '业务穿透式监管模块', lines: ['数据监测 · 风险预警', '监督问效 · 执纪问责'], path: '/portal/modules/supervision', color: '#e7a13d', deep: '#d4771a' },
  { id: 'documents', title: '文书智能生成模块', lines: ['文书起草 · 模板管理', '智能生成 · 规范校核'], path: '/portal/modules/documents', color: '#6079f4', deep: '#3d52df' },
];

export type PortalTarget = { url: string; openMode: 'newTab' | 'sameTab' };
export type PortalTargets = Record<string, PortalTarget>;

/** 运行时配置只影响五个外部入口；制度入口及站内登录回跳规则保持独立。 */
export function parsePortalTargets(value: unknown): PortalTargets {
  if (!value || typeof value !== 'object') throw new Error('工作台配置格式错误');
  const config = value as { version?: unknown; modules?: unknown };
  if (config.version !== 1 || !config.modules || typeof config.modules !== 'object' || Array.isArray(config.modules)) {
    throw new Error('工作台配置版本或模块格式错误');
  }
  const modules = config.modules as Record<string, unknown>;
  const targets: PortalTargets = {};
  for (const item of portalModules.filter(m => m.id !== 'policy')) {
    const entry = modules[item.id];
    if (entry === undefined) continue;
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error(`${item.title}配置格式错误`);
    const { enabled, url, openMode } = entry as { enabled?: unknown; url?: unknown; openMode?: unknown };
    if (typeof enabled !== 'boolean') throw new Error(`${item.title}需明确 enabled`);
    if (!enabled || url === '' || url === undefined) continue;
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url) || /[\s\\\u0000-\u001f\u007f]/.test(url)) {
      throw new Error(`${item.title}仅允许完整 HTTP/HTTPS 地址`);
    }
    const parsed = new URL(url);
    if (parsed.username || parsed.password) throw new Error('模块地址不能包含账号密码');
    if (openMode !== undefined && openMode !== 'newTab' && openMode !== 'sameTab') throw new Error('模块打开方式无效');
    targets[item.id] = { url: parsed.href, openMode: openMode ?? 'newTab' };
  }
  return targets;
}
export function safeReturn(value: unknown, fallback: string): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\s%]/.test(value.split('?')[0])) return fallback;
  const parsed = new URL(value, 'https://platform.invalid');
  if (parsed.origin !== 'https://platform.invalid') return fallback;
  const path = parsed.pathname;
  if (['/login', '/portal/login', '/change-password'].includes(path)) return fallback;
  return path + parsed.search + parsed.hash;
}
