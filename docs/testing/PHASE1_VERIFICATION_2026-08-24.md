# 第一期完成验证记录（2026-08-24）

> 历史记录：本文验证的是迁移前架构。当前统一知识模块结果见
> `KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md`。

文件说明：记录一期M5实际执行结果，区分已通过项目、未执行的耗时测试和未授权的视觉核对。

## 已通过

- 数据库迁移：`0003_phase1_completion (head)`。
- 后端最小测试：9项通过。
- 前端TypeScript类型检查和Vite生产构建通过。
- active制度：20份。
- active ParseRun正文：20/20份，共1439个Node。
- 受控PDF：20/20份，共232页；单份2至28页，结构解析全部成功。
- PDF接口：`GET /api/v1/documents/20/pdf`返回200、`application/pdf`和inline文件名，不泄露服务器路径。
- 真实制度检索：“信息公开”可从标题、机构或正文筛选出4份制度；URL刷新后条件恢复。
- 制度详情：目录、正文、条款路径、页码和Node锚点正常。
- Citation定位：历史`[E1]`可选中证据，并定位到`document_id=1`、`node_id=2507`、`page=1`；URL保留证据和run信息。
- 历史会话：刷新后答案、`answer_quality_gate_v2`和Citation运行快照恢复。
- 现代Chromium：1440×900三栏问答可见；1100px时会话和证据侧栏转为Drawer入口；控制台无error。
- PDF页面：制度名、文号、目标页、新窗口入口和iframe正常出现。

## 已遵守的边界

- Platform运行时代码只调用`POST /v1/rag/query`。
- 没有读取或修改RAG SQLite、Qdrant或模型服务。
- PDF从批准的源DOCX只读派生到Platform目录，RAG源文件未修改。
- 会话、消息、Citation、反馈、候选评测和配置均归Platform数据库。
- `quality_gate.version`按动态字符串保存。
- 普通页面和诊断页面不依赖受控debug草稿、Claim绑定或Verifier判定。

## 本轮未执行

- Chrome 89其他机器实机验证。
- 8010暖态响应时间、并发容量和压力测试。
- 120题开发集全量Citation定位。
- 20份制度PDF逐页视觉版式核对。

这些项目按用户要求保留为人工或后续专项测试；本轮没有冻结SLA、超时提示阈值或并发容量。
