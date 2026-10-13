/**
 * 文件说明：提供平台统一导航，并为智能问答路由切换沉浸式满高工作区布局。
 */
import { FileProtectOutlined, MenuOutlined } from '@ant-design/icons';
import { Badge, Button, Drawer, Layout, Menu, Space, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { getPlatformReadiness } from '../api/health';
import { UiIcon } from '../components/UiIcon';
import { useFeatures } from '../api/learning';
import { useAuth } from '../auth/AuthContext';
import { PortalAccount } from '../portal/PortalAccount';
import { portalEnabled } from '../portal/config';

const { Header, Content } = Layout;

export const navigationItems = [
  { key: '/', label: '首页' },
  { key: '/chat', label: '智能问答' },
  { key: '/documents', label: '制度库' },
  { key: '/admin/jobs', label: '管理后台' },
];

export function resolveSelectedKey(pathname: string): string {
  if (pathname.startsWith('/chat')) return '/chat';
  if (pathname.startsWith('/learning')) return '/learning';
  if (pathname.startsWith('/materials')) return '/materials';
  if (pathname.startsWith('/documents')) return '/documents';
  if (pathname.startsWith('/admin')) return '/admin/jobs';
  if (pathname.startsWith('/diagnostics')) return '/diagnostics';
  return '/';
}

export function BasicLayout() {
  const features = useFeatures();
  const { user } = useAuth();
  const visibleNavigation = [...navigationItems.slice(0, 3),
  ...(user?.permissions.includes('material.read') ? [{ key: '/materials', label: '配套资料库' }] : []),
  ...(features?.learning_assessment ? [{ key: '/learning', label: '学习检测' }] : []), ...navigationItems.slice(3)];
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [platformReady, setPlatformReady] = useState<boolean | null>(null);
  const selectedKeys = useMemo(
    () => [resolveSelectedKey(location.pathname)],
    [location.pathname],
  );
  const isChatRoute = location.pathname.startsWith('/chat');

  const handleNavigate = (key: string) => {
    navigate(key);
    setDrawerOpen(false);
  };

  useEffect(() => {
    getPlatformReadiness()
      .then((result) => setPlatformReady(result.status === 'ok'))
      .catch(() => setPlatformReady(false));
  }, [location.pathname]);

  return (
    <Layout className={`app-shell${isChatRoute ? ' app-shell-chat' : ''}`}>
      {!isChatRoute ? <Header className="app-header">
        <div className="brand-block">
          <Button
            className="mobile-nav-trigger"
            type="text"
            aria-label="打开导航菜单"
            icon={<UiIcon icon={MenuOutlined} />}
            onClick={() => setDrawerOpen(true)}
          />
          <button type="button" className="brand-home-button" onClick={() => handleNavigate('/')}>
            <span className="brand-mark"><UiIcon icon={FileProtectOutlined} /></span>
            <Typography.Title level={4} className="brand-title">
              制度管理模块
            </Typography.Title>
          </button>
        </div>
        <Menu
          className="desktop-nav"
          mode="horizontal"
          disabledOverflow
          selectedKeys={selectedKeys}
          items={visibleNavigation}
          onClick={({ key }) => handleNavigate(key)}
        />
        {portalEnabled ? <PortalAccount /> : <Space className="service-state" size={8}>
          <Badge status={platformReady === null ? 'processing' : platformReady ? 'success' : 'error'} />
          <Typography.Text>{platformReady === null ? '状态检查中' : platformReady ? '平台服务正常' : '平台服务不可用'}</Typography.Text>
        </Space>}
      </Header> : null}

      <Content className={`app-content${isChatRoute ? ' app-content-chat' : ''}`}>
        <Outlet />
      </Content>

      <Drawer
        title="平台导航"
        placement="left"
        width={280}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Menu
          mode="inline"
          selectedKeys={selectedKeys}
          items={visibleNavigation}
          onClick={({ key }) => handleNavigate(key)}
        />
      </Drawer>
    </Layout>
  );
}
