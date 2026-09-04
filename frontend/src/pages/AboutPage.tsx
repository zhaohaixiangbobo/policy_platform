/** 文件说明：展示可公开的平台版本、知识数据更新时间、运行边界和浏览器基线。 */
import { Alert, Badge, Card, Descriptions, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { listDocuments } from '../api/documents';
import { getPlatformReadiness } from '../api/health';

export function AboutPage() {
  const [version, setVersion] = useState('读取中');
  const [ready, setReady] = useState<boolean | null>(null);
  const [knowledgeUpdatedAt, setKnowledgeUpdatedAt] = useState<string | null>(null);

  useEffect(() => {
    void Promise.allSettled([
      getPlatformReadiness().then((result) => { setVersion(result.version); setReady(result.status === 'ok'); }),
      listDocuments({ page: 1, page_size: 1, sort_by: 'updated_at', sort_order: 'desc' }).then((result) => setKnowledgeUpdatedAt(result.items[0]?.updated_at ?? null)),
    ]).then((results) => { if (results[0].status === 'rejected') setReady(false); });
  }, []);

  return (
    <Space direction="vertical" size={20} className="full-width">
      <div><Typography.Title level={2} className="page-heading">服务说明</Typography.Title><Typography.Text type="secondary">仅展示对用户公开的版本和服务边界。</Typography.Text></div>
      <Card bordered={false}>
        <Descriptions column={1} bordered>
          <Descriptions.Item label="平台版本">{version}</Descriptions.Item>
          <Descriptions.Item label="Platform状态"><Badge status={ready === null ? 'processing' : ready ? 'success' : 'error'} text={ready === null ? '检查中' : ready ? '正常' : '不可用'} /></Descriptions.Item>
          <Descriptions.Item label="知识数据最后更新时间">{knowledgeUpdatedAt ? new Date(knowledgeUpdatedAt).toLocaleString('zh-CN') : '暂无制度数据'}</Descriptions.Item>
          <Descriptions.Item label="active IndexRun">在每次公开问答的Citation与诊断快照中记录</Descriptions.Item>
          <Descriptions.Item label="运行方式"><Tag color="blue">Windows本机试运行</Tag></Descriptions.Item>
          <Descriptions.Item label="浏览器基线">Chrome 89及以上；主要验收尺寸1440 × 900</Descriptions.Item>
          <Descriptions.Item label="知识服务边界">浏览器仅访问Platform API；知识能力由后端进程内模块提供</Descriptions.Item>
        </Descriptions>
      </Card>
      <Alert type="warning" showIcon message="一期无登录，仅限127.0.0.1本机使用" />
    </Space>
  );
}
