/**
 * 文件说明：集中覆盖Chrome 89基线所需的路由、表格、抽屉、表单、弹窗、聊天气泡、Sender和PDF入口。
 */
import { Bubble, Sender } from '@ant-design/x';
import {
  Alert,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { useState } from 'react';

import { documentPdfUrl } from '../utils/pdf';

interface SmokeRow {
  key: string;
  component: string;
  expected: string;
  status: string;
}

const smokeRows: SmokeRow[] = [
  { key: 'route', component: 'React Router', expected: '路由切换和刷新可恢复', status: '待实机' },
  { key: 'table', component: 'AntD Table', expected: '表头、边框和横向滚动正常', status: '待实机' },
  { key: 'drawer', component: 'AntD Drawer', expected: '打开、遮罩和关闭正常', status: '待实机' },
  { key: 'chat', component: 'Ant Design X', expected: 'Bubble与Sender可显示和输入', status: '待实机' },
];

export function BrowserBaselinePage() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [senderValue, setSenderValue] = useState('');
  const [lastMessage, setLastMessage] = useState('尚未提交冒烟消息');
  const [messageApi, contextHolder] = message.useMessage();

  const submitSender = (value: string) => {
    const normalizedValue = value.trim();
    if (!normalizedValue) return;
    setLastMessage(normalizedValue);
    setSenderValue('');
    messageApi.success('Sender提交事件正常');
  };

  return (
    <div className="page-stack">
      {contextHolder}
      <div>
        <Typography.Title level={2} className="page-heading">
          Chrome 89浏览器基线冒烟
        </Typography.Title>
        <Typography.Text type="secondary">
          必须使用生产构建产物，在1440×900的Chrome 89和现代Chrome/Edge各执行一次。
        </Typography.Text>
      </div>

      <Alert
        type="warning"
        showIcon
        message="本页只验证组件兼容与基本交互，不代表M2/M3业务功能完成"
      />

      <div className="smoke-grid">
        <Card className="smoke-card-full" title="组件与路由检查表" bordered={false}>
          <Table<SmokeRow>
            rowKey="key"
            pagination={false}
            scroll={{ x: 680 }}
            dataSource={smokeRows}
            columns={[
              { title: '检查项', dataIndex: 'component', width: 180 },
              { title: '预期结果', dataIndex: 'expected' },
              {
                title: '状态',
                dataIndex: 'status',
                width: 120,
                render: (status: string) => <Tag color="gold">{status}</Tag>,
              },
            ]}
          />
        </Card>

        <Card title="抽屉、表单与弹窗" bordered={false}>
          <Space wrap>
            <Button onClick={() => setDrawerOpen(true)}>
              打开抽屉
            </Button>
            <Button type="primary" onClick={() => setModalOpen(true)}>
              打开表单弹窗
            </Button>
            <Tooltip title="只传document_id和page">
              <Button
                href={documentPdfUrl('smoke-document', 1)}
                target="_blank"
                rel="noreferrer"
              >
                PDF入口
              </Button>
            </Tooltip>
          </Space>
        </Card>

        <Card title="三状态文字与颜色协同" bordered={false}>
          <Space wrap>
            <Tag color="green">已回答 ANSWER</Tag>
            <Tag color="gold">资料不足 INSUFFICIENT_EVIDENCE</Tag>
            <Tag color="red">规定冲突 CONFLICT</Tag>
          </Space>
        </Card>

        <Card className="smoke-card-full" title="Ant Design X聊天交互" bordered={false}>
          <div className="chat-smoke-panel">
            <div className="chat-bubbles">
              <Bubble.List
                items={[
                  {
                    key: 'assistant',
                    role: 'assistant',
                    placement: 'start',
                    content: '这是浏览器基线气泡，引用示例为[E1]。',
                  },
                  {
                    key: 'user',
                    role: 'user',
                    placement: 'end',
                    content: lastMessage,
                  },
                ]}
              />
            </div>
            <Sender
              value={senderValue}
              placeholder="输入一段文字并提交……"
              onChange={setSenderValue}
              onSubmit={submitSender}
            />
          </div>
        </Card>
      </div>

      <Drawer
        title="抽屉冒烟"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Typography.Paragraph>
          检查遮罩、焦点、滚动和关闭按钮；宽度低于1200px时主导航也使用Drawer。
        </Typography.Paragraph>
      </Drawer>

      <Modal
        title="表单与弹窗冒烟"
        open={modalOpen}
        okText="确认"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        onOk={() => setModalOpen(false)}
      >
        <Form layout="vertical">
          <Form.Item label="制度关键词" required>
            <Input placeholder="输入制度名称或文号" />
          </Form.Item>
          <Form.Item label="状态">
            <Select
              defaultValue="active"
              options={[
                { value: 'active', label: '现行有效' },
                { value: 'all', label: '全部' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
