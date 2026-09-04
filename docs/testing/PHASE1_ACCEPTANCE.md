# 第一期验收清单

> 历史清单：其中制度投影和独立 8010 步骤已由 ADR-0002 取代，不应作为当前运行命令。
> 当前最小验收见 `KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md`。

文件说明：区分自动最小测试、现代浏览器冒烟和需要用户手动执行的耗时或外部环境验收。

## 自动最小验证

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic current

Set-Location 'D:\2-code\policy-platform'
pnpm typecheck
pnpm build
& 'D:\3-anaconda\envs\py312\python.exe' scripts\verify-phase1-projection.py
```

## 浏览器业务验收

1. 首页分别验证“搜索制度”和“询问制度”。
2. 制度库组合筛选后刷新页面，确认URL条件和结果恢复。
3. 打开制度详情，点击目录Node并检查正文、路径和页码。
4. 完成一次`ANSWER`问答，点击Citation定位证据、Node和PDF页。
5. 使用准备好的问题分别验证`INSUFFICIENT_EVIDENCE`和`CONFLICT`。
6. 刷新会话页，确认消息和Citation快照恢复。
7. 验证会话新建、重命名、软删除、失败重试和本地取消等待。
8. 点赞、点踩并提交一个候选评测案例。
9. 本机显式开启诊断后，按request_id和状态查询公开响应快照。
10. 关闭8010后发起问答，确认Platform返回稳定错误且制度浏览仍可用。

## 用户手动执行

- 在Chrome 89机器上使用`pnpm build`产物执行`docs/testing/CHROME_89_SMOKE.md`。
- 在8010完成预热后执行真实问答、120题Citation定位和并发测试。
- 根据暖态结果再冻结SLA、查询超时、慢请求提示和并发容量。
- 对20份制度逐份人工核对目录结构、正文、PDF内容和页码定位。

上述耗时验收本轮不自动执行。
