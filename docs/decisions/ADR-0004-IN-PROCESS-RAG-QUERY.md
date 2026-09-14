# ADR-0004：Platform进程内RAG问答

> 文件说明：冻结知识模块迁移完成后的单工程运行边界。

- 状态：已接受并实施
- 日期：2026-09-14
- 取代：ADR-0003 的独立8010 HTTP问答边界

## 背景

Parser、Chunker、Indexer、Retrieval、RAG、Citation和质量门禁代码已迁入
`policy-platform/backend/knowledge`。继续启动原 `D:\2-code\rag` 的8010服务会引入
重复工程、额外进程和配置分叉，不符合已完成的统一知识模块迁移。

## 决策

1. Platform Web问答只通过 `backend/knowledge/service.py` 中的 `KnowledgeService`
   调用进程内 `RagRuntime`，不再使用 `RagApiClient` 或8010。
2. `RagRuntime` 在首次问答时惰性初始化，因此 Qdrant或模型服务不可用不影响
   Platform启动、登录、制度管理和目录浏览。
3. Runtime、SQLite连接及内部HTTP客户端在同一专用单线程中创建、查询和关闭；
   并发容量与超时阈值仍等暖态测试后确定。
4. `QueryScopeResolver` 继续先计算“用户可访问 ∩ 用户选择 ∩ CURRENT/HISTORICAL
   ∩ active IndexRun”，再转换为 `SearchFilters.document_ids` 和
   `SearchFilters.document_statuses`。
5. `CURRENT` 只查询 `effective`；`HISTORICAL` 只查询 `repealed|expired`。指定制度
   不可查时返回错误，不扩大到全库。
6. 进程内查询继续输出 `rag_api_v1_1` 结果语义，Platform保存
   `ANSWER|INSUFFICIENT_EVIDENCE|CONFLICT`、版本化Citation、质量门禁和耗时快照。
7. Platform仍对Citation的 `document_id`、制度状态和 `index_run_id` 做响应后复核。
8. `platform.db` 仅保存用户、会话、反馈、审计和配置；
   `policy_parser.db` 继续保存知识内容与运行版本。

## 运行依赖

不再需要原RAG工程或8010。真实问答仍需要当前工程配置的：

- Qdrant；
- Embedding服务；
- Reranker服务；
- Generator服务。

上述外部依赖由进程内Runtime直接调用，不经过额外8010中转层。
