/**
 * 文件说明：实现参考图视觉方向的本地登录页，并明确展示尚未启用的4A接入状态。
 */
import { AuditOutlined, FileProtectOutlined, LockOutlined, SafetyCertificateOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Badge, Button, Card, Form, Input, Space, Typography, message } from 'antd';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';

const capabilities = [
  { icon: SafetyCertificateOutlined, title: '权威规范', text: '制度原文权威准确' },
  { icon: AuditOutlined, title: '有据可查', text: '答案附带原文依据与引用' },
  { icon: TeamOutlined, title: '高效协同', text: '制度管理全流程数字化' },
];

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setSubmitting(true);
    try {
      const user = await auth.login(values.username, values.password);
      message.success(`欢迎，${user.display_name}`);
      const target = user.must_change_password ? '/change-password' : ((location.state as { from?: string } | null)?.from ?? '/admin/jobs');
      navigate(target, { replace: true });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <header className="login-header">
        <div className="login-brand"><span className="brand-mark"><UiIcon icon={FileProtectOutlined} /></span><strong>制度知识智能服务平台</strong></div>
        <Space size={8}><Badge status="success" /><Typography.Text>平台服务正常</Typography.Text></Space>
      </header>
      <section className="login-content">
        <div className="login-intro">
          <Typography.Title level={1}>制度知识智能服务平台</Typography.Title>
          <Typography.Paragraph className="login-subtitle">查制度 · 问条款 · 找依据</Typography.Paragraph>
          <div className="login-capabilities">
            {capabilities.map((item) => (
              <div className="login-capability" key={item.title}>
                <span><UiIcon icon={item.icon} /></span>
                <div><strong>{item.title}</strong><small>{item.text}</small></div>
              </div>
            ))}
          </div>
          <div className="login-illustration" aria-hidden="true">
            <span className="illustration-sheet sheet-back" />
            <span className="illustration-sheet sheet-middle" />
            <span className="illustration-sheet sheet-front"><UiIcon icon={FileProtectOutlined} /></span>
          </div>
        </div>
        <Card className="login-card" bordered={false}>
          <Typography.Title level={2}>用户登录</Typography.Title>
          <div className="login-method-tabs"><button className="active" type="button">账号密码登录</button><button type="button" disabled>单点登录（4A）</button></div>
          <Form layout="vertical" size="large" onFinish={submit} requiredMark={false}>
            <Form.Item label="用户名 / 工号" name="username" rules={[{ required: true, message: '请输入用户名或工号' }]}>
              <Input prefix={<UiIcon icon={UserOutlined} />} placeholder="请输入用户名或工号" autoComplete="username" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<UiIcon icon={LockOutlined} />} placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>登录</Button>
          </Form>
          <Alert className="four-a-notice" type="info" showIcon message="4A/SSO 接口已预留，当前由本地账号完成身份认证。" />
        </Card>
      </section>
      <footer className="login-footer">© 2026 制度知识智能服务平台</footer>
    </main>
  );
}
