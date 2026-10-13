/**
 * 文件说明：制度模块顶栏的账户入口（仅门户开启时渲染）。
 * 默认只露出头像，悬停或点击展开账户面板：身份信息、返回工作台、退出登录。
 */
import { AppstoreOutlined, DownOutlined, LogoutOutlined } from '@ant-design/icons';
import { Dropdown, message, type MenuProps } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';
import { portalEnabled } from './config';
import './portal-account.css';

export function PortalAccount() {
  const auth = useAuth(); const navigate = useNavigate();
  if (!portalEnabled) return null;
  const name = auth.user?.display_name || '当前用户';
  const initial = name.slice(0, 1).toUpperCase();
  const roles = auth.user?.roles.join(' / ');
  const items: MenuProps['items'] = [
    { key: 'portal', icon: <UiIcon icon={AppstoreOutlined} />, label: '返回工作台' },
    { type: 'divider' },
    { key: 'logout', icon: <UiIcon icon={LogoutOutlined} />, label: '退出登录', danger: true },
  ];
  const onClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'portal') { navigate('/portal'); return; }
    void auth.logout().then(() => navigate('/login', { replace: true })).catch(() => message.error('退出失败，请重试'));
  };
  // popupRender 在菜单上方补一块身份信息头，菜单本身仍由 antd 负责键盘导航与无障碍语义。
  return <Dropdown rootClassName="account-dropdown" placement="bottomRight" trigger={['hover', 'click']} menu={{ items, onClick }}
    popupRender={(menu) => <div className="account-panel">
      <div className="account-panel-head"><span className="account-avatar is-lg" aria-hidden="true">{initial}</span>
        <span className="account-panel-who"><strong>{name}</strong>{roles ? <small>{roles}</small> : null}</span></div>
      {menu}</div>}>
    <button type="button" className="account-trigger" aria-label={`账户：${name}`}>
      <span className="account-avatar" aria-hidden="true">{initial}</span>
      <UiIcon className="account-caret" icon={DownOutlined} aria-hidden="true" />
    </button>
  </Dropdown>;
}
