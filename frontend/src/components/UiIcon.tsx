/**
 * 文件说明：隔离冻结版Ant Design图标与React 18.3类型声明差异，统一输出平台界面图标。
 */
import type { ComponentType, HTMLAttributes } from 'react';

interface UiIconProps extends HTMLAttributes<HTMLSpanElement> {
  icon: unknown;
}

export function UiIcon({ icon, ...props }: UiIconProps) {
  const Icon = icon as ComponentType<Record<string, never>>;
  return (
    <span {...props}>
      <Icon />
    </span>
  );
}
