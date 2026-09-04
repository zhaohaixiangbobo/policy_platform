/**
 * 文件说明：集中维护平台颜色、容器、圆角、字号和表单高度等全局主题令牌。
 */
import type { ThemeConfig } from 'antd';

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#245bdb',
    colorInfo: '#245bdb',
    colorSuccess: '#218739',
    colorWarning: '#ad6800',
    colorError: '#c53030',
    colorText: '#1f2937',
    colorTextSecondary: '#667085',
    borderRadius: 12,
    fontSize: 14,
    controlHeight: 38,
    colorBgLayout: '#f6f7f9',
    colorBgContainer: '#ffffff',
    colorBorderSecondary: '#eaecf0',
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      bodyBg: '#f4f7fb',
    },
    Menu: {
      itemBg: 'transparent',
      horizontalItemSelectedColor: '#245bdb',
    },
  },
};
