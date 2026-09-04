# M2 至 M4 现代浏览器冒烟记录（2026-08-23）

> 历史记录：本文描述迁移前的制度投影与独立 8010 架构，仅用于追溯当时的页面验收。
> 当前验证结果见 `KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md`。

文件说明：记录本轮在当前 Codex 应用内 Chromium 上执行的最小页面验证；Chrome 89 由用户在其他机器另行验证。

## 环境

- 前端：Vite production build + preview，`http://127.0.0.1:4173`
- 后端：Platform API，`http://127.0.0.1:8020`
- 数据库：独立 `policy-platform/backend/platform.db`，迁移版本 `0002_m2_m4_platform_models`
- Knowledge Engine：未发送真实查询，未执行 8010 暖态测试

## 已验证

1. 首页可见 M0 至 M4 导航、Platform API 边界说明和业务入口。
2. 制度库通过 Platform API 返回空投影状态，检索控件和表头正常。
3. 智能问答可显示会话区与“新建/选择会话”空态。
4. 公开响应诊断在默认配置下返回关闭状态，页面明确说明不读取受控 debug 数据。
5. 页面切换后浏览器控制台无 error 日志。

## 本轮未执行

- 未向 `POST /v1/rag/query` 发送真实问题；客户端路径与公开响应处理由后端确定性测试验证。
- 未执行 Chrome 89 实机验证。
- 未执行 PDF 视觉渲染核对。
- 未执行 8010 暖态响应时间、超时阈值、并发或压力测试。
