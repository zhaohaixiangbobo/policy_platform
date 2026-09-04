/**
 * 文件说明：说明当前本地身份和未来4A映射边界，用户管理写接口在后续小里程碑接入。
 */
import { Alert, Card, Descriptions, Tag, Typography } from 'antd';
import { useAuth } from '../../auth/AuthContext';

export function UserAccessPage() {
  const { user } = useAuth();
  return <div className="admin-page"><div className="admin-page-title"><div><Typography.Title level={2}>用户与权限</Typography.Title><Typography.Text type="secondary">4A只替换身份认证方式，内部用户、角色、会话和审计保持稳定</Typography.Text></div></div><Card bordered={false}><Descriptions column={1} bordered><Descriptions.Item label="当前用户">{user?.display_name}（{user?.username}）</Descriptions.Item><Descriptions.Item label="认证来源"><Tag color="blue">{user?.auth_provider}</Tag></Descriptions.Item><Descriptions.Item label="角色">{user?.roles.map((role) => <Tag key={role}>{role}</Tag>)}</Descriptions.Item><Descriptions.Item label="服务端会话">HttpOnly Cookie + CSRF</Descriptions.Item><Descriptions.Item label="4A状态">Provider 与 identity_link 数据模型已预留，协议参数待单位4A规范确认</Descriptions.Item></Descriptions><Alert style={{ marginTop: 20 }} type="info" showIcon message="首个管理员通过交互式脚本创建；不提供公开注册、找回密码、短信验证码或复杂资料中心。" /></Card></div>;
}
