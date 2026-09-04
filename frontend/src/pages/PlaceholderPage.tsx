/**
 * 文件说明：为尚未进入当前里程碑的业务路由提供明确占位反馈。
 */
import { Button, Result } from 'antd';
import { useNavigate } from 'react-router-dom';

interface PlaceholderPageProps {
  title: string;
  milestone: string;
}

export function PlaceholderPage({ title, milestone }: PlaceholderPageProps) {
  const navigate = useNavigate();

  return (
    <Result
      status="info"
      title={`${title}将在${milestone}建设`}
      subTitle="当前路由、基础布局和Platform API边界已经建立。"
      extra={
        <Button type="primary" onClick={() => navigate('/smoke/browser-baseline')}>
          查看M0浏览器冒烟
        </Button>
      }
    />
  );
}
