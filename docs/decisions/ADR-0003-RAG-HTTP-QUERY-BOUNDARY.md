# ADR-0003：问答通过独立 RAG HTTP 契约

> 历史决策记录：独立 RAG HTTP 边界已由 ADR-0004 取代，不再是当前运行依据。

- 状态：已废止（由 ADR-0004 取代）
- 日期：2026-09-03
- 取代：ADR-0002 中“问答进程内调用”的部分

## 决策

1. 浏览器只访问 Platform API。
2. Platform 问答只调用 `POST /v1/rag/query`，不访问 RAG 的 SQLite、Qdrant 或模型服务。
3. 状态范围为 `query_scope=CURRENT|HISTORICAL`，省略时强制采用 `CURRENT`；制度范围使用显式
   `document_scope=ALL|SELECTED`，不使用 `null` 或空数组推断业务语义。
4. `CURRENT` 只允许现行有效制度；`HISTORICAL` 只允许已废止或已失效制度。
5. Platform 按 `rag_api_v1_1` 校验并保存三种回答状态和公开 Citation 快照，不依赖 debug 诊断字段。
6. Platform 不叠加 HTTP 重试，不在暖态测试前冻结响应 SLA、读取超时提示阈值或并发容量。
7. Platform 自有会话、消息、反馈、用户和配置仍写入 `platform.db`。
8. Platform 的 `QueryScopeResolver` 先计算用户可访问制度、用户主动选择、状态范围和 active
   IndexRun 的交集，再把结果传给 RAG；RAG 不处理用户身份或 4A 权限。
9. 用户指定制度无法命中安全范围时返回错误，不回退到全库；Platform 对 Citation 的
   `document_id`、状态和 `index_run_id` 执行响应后复核；查询期间 Alias 发生切换时拒绝混合快照。

## 发布状态

索引构建不代表正式发布。只有 RAG 侧 Alias 切换成功，新的 IndexRun 才成为查询事实源；切换失败时旧 Alias 继续生效。
