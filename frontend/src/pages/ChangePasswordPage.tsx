/**
 * 文件说明：为本地账号提供首次登录强制修改初始密码的最小安全页面。
 */
import { FileProtectOutlined, LockOutlined } from '@ant-design/icons';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { changePassword } from '../api/auth';
import { useAuth } from '../auth/AuthContext';
import { UiIcon } from '../components/UiIcon';

export function ChangePasswordPage() {
  const [loading, setLoading] = useState(false);
  const auth = useAuth();
  const navigate = useNavigate();
  const submit = async (values: { current: string; next: string; confirm: string }) => {
    if (values.next !== values.confirm) { message.error('两次新密码不一致'); return; }
    setLoading(true);
    try { await changePassword(values.current, values.next); await auth.refresh(); message.success('密码已更新'); navigate('/admin/jobs', { replace: true }); }
    catch (error) { message.error(error instanceof Error ? error.message : '密码修改失败'); }
    finally { setLoading(false); }
  };
  return <main className="password-page"><Card className="password-card" bordered={false}><span className="password-logo"><UiIcon icon={FileProtectOutlined} /></span><Typography.Title level={2}>首次登录，请修改初始密码</Typography.Title><Typography.Paragraph type="secondary">新密码至少10个字符，修改完成后继续进入平台。</Typography.Paragraph><Form layout="vertical" onFinish={submit} requiredMark={false}><Form.Item label="当前密码" name="current" rules={[{ required: true }]}><Input.Password prefix={<UiIcon icon={LockOutlined} />} /></Form.Item><Form.Item label="新密码" name="next" rules={[{ required: true }, { min: 10, message: '至少10个字符' }]}><Input.Password /></Form.Item><Form.Item label="确认新密码" name="confirm" rules={[{ required: true }]}><Input.Password /></Form.Item><Button type="primary" htmlType="submit" block loading={loading}>确认修改</Button></Form></Card></main>;
}
