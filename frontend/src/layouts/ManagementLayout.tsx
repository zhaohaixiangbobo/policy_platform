/**
 * 文件说明：提供第二期管理后台统一顶部导航、分组侧栏、用户身份与内容工作区。
 */
import { ApartmentOutlined, AuditOutlined, DatabaseOutlined, FileProtectOutlined, LinkOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SafetyCertificateOutlined, TeamOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Avatar, Button, Dropdown, Layout, Menu, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';
import { useFeatures } from '../api/learning';
import { navigationItems, resolveSelectedKey } from './BasicLayout';

const { Header, Sider, Content } = Layout;

const sideItems = [
  {
    type: 'group' as const, label: '知识管理', children: [
      { key: '/admin/jobs', icon: <UiIcon icon={UnorderedListOutlined} />, label: '任务中心' },
      { key: '/admin/reviews', icon: <UiIcon icon={AuditOutlined} />, label: '解析与分块审核' },
      { key: '/admin/knowledge', icon: <UiIcon icon={DatabaseOutlined} />, label: '制度治理与发布' },
    ]
  },
  {
    type: 'group' as const, label: '知识应用', children: [
      { key: '/admin/relations', icon: <UiIcon icon={LinkOutlined} />, label: '制度关系' },
      { key: '/admin/processes', icon: <UiIcon icon={ApartmentOutlined} />, label: '流程管理' },
      { key: '/documents', icon: <UiIcon icon={DatabaseOutlined} />, label: '制度库' },
    ]
  },
  {
    type: 'group' as const, label: '系统管理', children: [
      { key: '/admin/users', icon: <UiIcon icon={TeamOutlined} />, label: '用户与权限' },
      { key: '/diagnostics/requests', icon: <UiIcon icon={SafetyCertificateOutlined} />, label: '审计与诊断' },
    ]
  },
];

export function ManagementLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const auth = useAuth();
  const features = useFeatures();
  const visibleNavigation = features?.learning_assessment
    ? [...navigationItems.slice(0, 3), { key: '/learning', label: '学习成效检测' }, ...navigationItems.slice(3)]
    : navigationItems;
  const topSelectedKeys = useMemo(() => [resolveSelectedKey(location.pathname)], [location.pathname]);
  const selected = useMemo(() => {
    const match = ['/admin/jobs', '/admin/reviews', '/admin/knowledge', '/admin/relations', '/admin/processes', '/admin/users'].find((item) => location.pathname.startsWith(item));
    return [match ?? location.pathname];
  }, [location.pathname]);

  return (
    <Layout className="management-shell">
      <Header className="management-header">
        <button className="brand-home-button management-brand" type="button" onClick={() => navigate('/')}>
          <span className="brand-mark"><UiIcon icon={FileProtectOutlined} /></span>
          <Typography.Title level={4} className="brand-title">制度知识智能服务平台</Typography.Title>
        </button>
        <Menu
          className="desktop-nav management-top-nav"
          mode="horizontal"
          disabledOverflow
          selectedKeys={topSelectedKeys}
          items={visibleNavigation}
          onClick={({ key }) => navigate(key)}
        />
        <Dropdown menu={{ items: [{ key: 'logout', icon: <UiIcon icon={LogoutOutlined} />, label: '退出登录', onClick: () => void auth.logout().then(() => navigate('/login')) }] }}>
          <button className="management-user" type="button">
            <Avatar size={30}>{auth.user?.display_name.slice(0, 1)}</Avatar>
            <span><strong>{auth.user?.display_name}</strong><small>{auth.user?.roles.join(' / ')}</small></span>
          </button>
        </Dropdown>
      </Header>
      <Layout>
        <Sider className="management-sider" width={216} collapsedWidth={72} collapsed={collapsed} theme="light">
          <Menu mode="inline" selectedKeys={selected} items={sideItems} onClick={({ key }) => navigate(key)} />
          <Button className="sider-collapse" type="text" icon={<UiIcon icon={collapsed ? MenuUnfoldOutlined : MenuFoldOutlined} />} onClick={() => setCollapsed(!collapsed)}>{collapsed ? null : '收起导航'}</Button>
        </Sider>
        <Content className="management-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
