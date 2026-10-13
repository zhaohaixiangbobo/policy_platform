# 配套资料v2验证与清理记录

> 文件说明：2026-10-09本次任务的最小验证与授权数据清理。

## 已验证

- backend/tests/test_materials.py：14项通过，含类型字段隔离、十列解析、全角表头、数字年龄、合并区域拒绝、空处理结果、120字预览、原文不能独立触发推荐及原有权限/发布/导入测试。
- 前端 material-upload-http.test.mjs 与 material-recommendation-ui.test.mjs：20项通过。沙箱子进程限制后在授权环境运行。
- frontend typecheck 和 build 通过；保留既有大包体积警告。
- 学习检测定点回归3项通过：learning_material_access、program_scoring、answer_projection，资料访问边界与评分保持不变。
- OpenAPI重新导出，无新增依赖或数据库迁移。
- 真实Excel存在A26:H26合并区域；仅在内存移除第26行后24条全部通过。未修改用户原文件，请删除该行后重传。

## 授权清理

停止本项目API进程及其重载子进程后，事务删除 material_revision 7条、supporting_material 7条、material_import_batch 3条；三表剩余均0，外键检查通过。删除 var/materials/dff313f788264628a7ee33115f4e700d.png，资料目录为空。

用户明确要求无备份。未删除制度、用户、聊天、学习检测、审计或Qdrant，未删除用户原始Excel/图片。API未自动重新启动，需运行 scripts/dev-backend.ps1。导入后仍需手动发布。

## 验收范围

未执行全量、压力、长时间测试或真实模型调用；未进行浏览器视觉验收。人工复核：重启后端刷新页面，上传三字段图片；十列Excel预览→确认→手动发布，查看空处理结果“未公布”，检验问答/学习推荐卡片和详情。

最小复测（无需全量）：backend目录使用固定Python执行 `-m pytest tests/test_materials.py -q`；frontend目录执行 `node --test tests/material-upload-http.test.mjs tests/material-recommendation-ui.test.mjs`、`pnpm typecheck`、`pnpm build`。
