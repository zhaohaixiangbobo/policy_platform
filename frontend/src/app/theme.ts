/**
 * 文件说明：集中维护平台颜色、容器、圆角、字号和表单高度等全局主题令牌。
 */
import type { ThemeConfig } from 'antd';

// 与制度库 .document-status-current 保持一致，统一成功状态与预设绿色标签。
const successPalette = {
  text: '#237804',
  background: '#f1faee',
  border: '#b7dfaa',
};

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#245bdb',
    colorInfo: '#245bdb',
    colorSuccess: successPalette.text,
    colorSuccessText: successPalette.text,
    colorSuccessBg: successPalette.background,
    colorSuccessBorder: successPalette.border,
    // Tag 的 green 预设独立于 success，需同步其浅底、边框和文字令牌。
    green1: successPalette.background,
    green3: successPalette.border,
    green7: successPalette.text,
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
