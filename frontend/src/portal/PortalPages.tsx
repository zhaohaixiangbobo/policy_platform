/** 文件说明：统一门户、专用登录及五模块占位；共享原AuthProvider和服务端会话。 */
import { useEffect, useState, type AnimationEvent, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Button, Form, Input, Result, Spin, Tooltip, message } from 'antd';
import {
  ArrowRightOutlined, AuditOutlined, EditFilled, FileDoneOutlined, FileSearchOutlined, FileTextFilled, FundFilled,
  LineChartOutlined, LockOutlined, LogoutOutlined, ReadOutlined, SafetyCertificateFilled, SearchOutlined, TeamOutlined,
  UserOutlined, WarningFilled,
} from '@ant-design/icons';
import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';
import { parsePortalTargets, portalModules, portalTitle, safeReturn, type PortalTargets } from './config';
import './portal.css';

// 按模块顺序对应：主图标用于渐变图标块，水印图标作为卡片右下角的低对比装饰。
const icons = [FileTextFilled, TeamOutlined, SafetyCertificateFilled, SearchOutlined, FundFilled, EditFilled];
const marks = [ReadOutlined, TeamOutlined, AuditOutlined, FileSearchOutlined, LineChartOutlined, FileDoneOutlined];
const slogan = ['贯通协同', '信息共享', '数智赋能', '提质增效'];
// 登录卡顶部色带取六模块主色，与工作台卡片配色呼应。
const spectrum = { backgroundImage: `linear-gradient(90deg, ${[...portalModules, portalModules[0]].map((m) => m.color).join(', ')})` };

function Heading() {
  return <header className="portal-heading"><h1>{portalTitle}</h1>
    <p className="portal-slogan" aria-label={slogan.join(' · ')}><span className="portal-rule" aria-hidden="true" />
      {slogan.map((word, index) => <span key={word} className="portal-slogan-word">{index > 0 && <i aria-hidden="true" />}{word}</span>)}
      <span className="portal-rule is-end" aria-hidden="true" /></p></header>;
}

/** 记录指针在卡片内的位置，驱动跟随光斑；只写CSS变量，不触发React重渲染。 */
function trackSpot(event: PointerEvent<HTMLAnchorElement>) {
  const rect = event.currentTarget.getBoundingClientRect();
  event.currentTarget.style.setProperty('--mx', `${event.clientX - rect.left}px`);
  event.currentTarget.style.setProperty('--my', `${event.clientY - rect.top}px`);
}

export function PortalPage() {
  const auth = useAuth(); const navigate = useNavigate();
  const [targets, setTargets] = useState<PortalTargets>({});
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timer = window.setTimeout(() => controller.abort(), 5000);
    // 配置无凭据请求、不缓存；任何加载/校验失败都保留安全的站内占位入口。
    fetch('/runtime/portal-config.json', { cache: 'no-store', credentials: 'omit', signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('配置读取失败'); return response.json(); })
      .then(value => { if (active) setTargets(parsePortalTargets(value)); })
      .catch(() => { if (active) { setTargets({}); message.warning('外部模块配置不可用，暂显示建设中入口'); } })
      .finally(() => window.clearTimeout(timer));
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, []);
  const name = auth.user?.display_name || '当前用户';
  const logout = () => void auth.logout().then(() => navigate('/login', { replace: true })).catch(() => message.error('退出失败，请重试'));
  return <main className="portal-shell">
    {/* 默认只露出退出按钮；悬停或键盘聚焦时向左展开当前用户 */}
    <div className="portal-account"><span className="portal-account-who"><span className="portal-avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <span className="portal-account-name">{name}</span></span>
      <Tooltip title="退出登录" placement="bottom"><Button className="portal-exit" type="text" shape="circle" aria-label={`退出登录（${name}）`} icon={<UiIcon icon={LogoutOutlined} />} onClick={logout} /></Tooltip></div>
    <Heading /><section className="portal-grid" aria-label="业务模块">{portalModules.map((item, index) => {
      // 八位十六进制补透明度，派生浅底、描边和投影三档模块色，兼容Chrome 89。
      const style = {
        '--c': item.color, '--c-deep': item.deep, '--c-soft': `${item.color}1a`, '--c-line': `${item.color}66`,
        '--c-shadow': `${item.color}40`, '--i': index
      } as CSSProperties;
      const content = <>
        <span className="portal-card-spot" aria-hidden="true" />
        <span className="portal-mark" aria-hidden="true"><UiIcon icon={marks[index]} /></span>
        <span className="portal-icon" aria-hidden="true"><span className="portal-icon-core"><UiIcon icon={icons[index]} /></span></span>
        <div className="portal-card-body">
          <h2 className="portal-card-title">{item.title}</h2>
          {item.lines.map((line) => <p key={line}>{line.split(' · ').map((word, i) => <span key={word}>{i > 0 && <i aria-hidden="true" />}{word}</span>)}</p>)}
        </div>
        <span className="portal-arrow" aria-hidden="true"><UiIcon icon={ArrowRightOutlined} /></span>
      </>;
      const target = targets[item.id];
      return target
        ? <a key={item.id} href={target.url} target={target.openMode === 'newTab' ? '_blank' : '_self'}
            rel="noopener noreferrer" referrerPolicy="no-referrer" className="portal-card" style={style}
            onPointerMove={trackSpot} aria-label={`${item.title}（外部系统）`}>{content}</a>
        : <Link key={item.id} to={item.path} className="portal-card" style={style} onPointerMove={trackSpot}
            aria-label={item.title}>{content}</Link>;
    })}</section>
    <footer className="portal-footer">内部工作平台 · 请妥善保管账号信息</footer></main>;
}
export function PortalLoginPage() {
  const auth = useAuth(); const location = useLocation(); const navigate = useNavigate(); const [busy, setBusy] = useState(false);
  const [capsLock, setCapsLock] = useState(false); const [shake, setShake] = useState(false);
  const target = safeReturn(location.state?.from, '/portal');
  // 密码框内实时检测大写锁定，避免用户反复输错。
  const detectCaps = (event: KeyboardEvent<HTMLInputElement>) => setCapsLock(event.getModifierState('CapsLock'));
  // 失败时卡片轻摇一次，动画结束即复位，以便下次失败可再次触发。
  const endShake = (event: AnimationEvent<HTMLElement>) => { if (event.animationName === 'portal-shake') setShake(false); };
  if (auth.loading) return <Spin fullscreen />;
  if (auth.user) return <Navigate replace to={auth.user.must_change_password ? '/change-password' : target} state={{ from: target }} />;
  async function submit(values: { username: string; password: string }) {
    setBusy(true);
    try { const user = await auth.login(values.username, values.password); navigate(user.must_change_password ? '/change-password' : target, { replace: true, state: { from: target } }); }
    catch (error) { message.error(error instanceof Error ? error.message : '登录失败'); setShake(true); }
    finally { setBusy(false); }
  }
  return <main className="portal-shell portal-login"><Heading />
    <section className={`portal-login-card${shake ? ' is-shake' : ''}`} onAnimationEnd={endShake} aria-labelledby="portal-login-title">
      <span className="portal-login-spectrum" style={spectrum} aria-hidden="true" />
      <span className="portal-login-badge" aria-hidden="true"><UiIcon icon={SafetyCertificateFilled} /></span>
      <h2 id="portal-login-title">平台登录</h2><p>统一身份认证 · 业务协同工作台</p>
      <Form className="portal-login-form" layout="vertical" onFinish={submit} requiredMark={false} size="large">
        <Form.Item name="username" rules={[{ required: true, message: '请输入用户名或工号' }]}>
          <Input prefix={<UiIcon icon={UserOutlined} />} placeholder="用户名 / 工号" aria-label="用户名 / 工号" autoComplete="username" /></Form.Item>
        <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}
          extra={capsLock ? <span className="portal-caps"><UiIcon icon={WarningFilled} />大写锁定已开启</span> : null}>
          <Input.Password prefix={<UiIcon icon={LockOutlined} />} placeholder="密码" aria-label="密码" autoComplete="current-password"
            onKeyDown={detectCaps} onKeyUp={detectCaps} onBlur={() => setCapsLock(false)} /></Form.Item>
        <Button className="portal-login-submit" type="primary" htmlType="submit" loading={busy} block>
          <span className="portal-login-shine" aria-hidden="true" /><span>登录工作台</span><UiIcon className="portal-login-go" icon={ArrowRightOutlined} aria-hidden="true" />
        </Button>
      </Form><small>使用现有账号登录</small></section></main>;
}
export function ModulePlaceholderPage() {
  const { moduleId } = useParams(); const item = portalModules.find(m => m.id === moduleId && m.id !== 'policy');
  return <main className="portal-shell"><Heading /><div className="portal-placeholder"><Result status={item ? 'info' : '404'} title={item ? item.title : '模块不存在'} subTitle={item ? '模块建设中，敬请期待' : undefined} extra={<Link to="/portal"><Button type="primary">返回工作台</Button></Link>} /></div></main>;
}
