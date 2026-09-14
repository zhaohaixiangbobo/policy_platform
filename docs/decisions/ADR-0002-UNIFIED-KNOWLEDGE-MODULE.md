# ADR-0002：知识引擎作为 Platform 平级模块

> 文件说明：冻结知识能力迁入 `policy-platform` 后的部署、调用和数据边界。

- 状态：已接受并完整实施；问答边界由 ADR-0004 补充
- 日期：2026-08-29
- 取代：ADR-0001 的独立知识引擎部署方案

## 背景

本项目用于本机测试，独立维护 8010 服务、制度投影和重复 PDF 会增加启动步骤与数据同步成本。项目还需要继续开发文档上传、解析、审核、分块和索引发布能力，因此知识流水线应成为完整应用的一部分。

## 决策

1. 将 Parser、Chunk、Index、Retrieval 和 RAG 的关键实现迁入 `backend/knowledge`。
2. `backend/app` 与 `backend/knowledge` 平级；产品应用通过 `KnowledgeService` 和 `KnowledgeCatalogService` 调用知识能力。
3. 问答通过 `KnowledgeService` 进程内调用 `RagRuntime`，对应用层保持稳定公开结果契约。
4. 取消制度投影。制度目录、节点和 PDF 从知识数据库的 active 版本读取。
5. 保留 `platform.db` 与 `policy_parser.db` 两个数据库：前者拥有平台业务数据，后者拥有文档流水线数据。
6. 保留 ParseRun、ChunkRun、IndexRun、审核记录、latest/active 指针和版本化 Citation 语义。
7. 仅迁移 active 链路所需的原始 DOCX、accepted DOCX 和 PDF；可重复生成的 MD、报告和测试产物不迁移。
8. 不迁移 Qdrant storage、模型权重、大型评测体系、独立 API 工作池和熔断器。

## 依赖方向

```text
browser -> app.api -> app.application -> knowledge.service/catalog
                                      -> platform.db
knowledge.service -> retrieval/rag -> Qdrant and model services
knowledge.catalog/parser/chunking/indexing -> policy_parser.db
```

`app.api` 不得直接导入知识数据库、Qdrant 适配器或模型客户端。

## 后果

- 本机只需启动前端与一个后端进程；
- 制度目录不再需要 JSON 投影和同步脚本；
- 两类数据仍可独立重建和审计；
- Platform 后端直接配置 Qdrant 和模型服务，但应用业务层不越过 `KnowledgeService` 访问底层客户端；
- 未来文档管理应使用后台任务，不能在普通 HTTP 请求内同步完成整条流水线。
