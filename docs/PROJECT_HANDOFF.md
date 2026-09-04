# 制度知识智能服务平台项目交接文档

> 文件说明：记录 2026-09-03 问答重新切回独立 RAG HTTP 契约后的当前工程边界。

## 1. 当前状态

`D:\2-code\policy-platform` 已成为完整的本机测试工程：

- `frontend` 提供制度库、问答、反馈和诊断页面；
- `backend/app` 提供 Platform API 和平台业务服务；
- `backend/knowledge` 提供 Platform 管理流水线能力；
- `var/platform.db` 保存平台业务数据；
- `var/knowledge/policy_parser.db` 保存知识流水线和运行版本；
- `D:\2-code\rag` 是独立问答引擎，通过 8010 提供公开 API。

问答边界事实源是 [ADR-0003](decisions/ADR-0003-RAG-HTTP-QUERY-BOUNDARY.md)；ADR-0002 的管理流水线决策继续有效，其中“问答进程内调用”已被取代。

## 2. 强制边界

1. 浏览器只访问 Platform API，不直接访问数据库、Qdrant 或模型服务。
2. Platform 问答只能通过 `RagApiClient` 调用 `POST /v1/rag/query`，不得访问 RAG 内部 SQLite、Qdrant 或模型服务。
3. Platform 数据与知识数据继续使用两个 SQLite，不合并表和迁移历史。
4. 问答保持 `rag_api_v1_1` 的公开语义，正确处理 `ANSWER`、`INSUFFICIENT_EVIDENCE` 和 `CONFLICT`。
5. Citation 保留 `document_id`、`primary_node_id`、各类 run ID、证据快照及公开版本字段。
6. `quality_gate.version` 按响应保存，不写死版本，也不依赖受控 debug 草稿哈希、Claim 绑定或 Verifier 判定。
7. 响应 SLA、提示阈值和并发容量仍未冻结。
8. 原始文档不可覆盖；latest 与 active 分离；只有审核通过后才能切换 active。
9. Qdrant active alias 仅在 IndexRun 验证通过后切换。

## 3. 数据与文件

```text
var/
├─ platform.db
└─ knowledge/
   ├─ policy_parser.db
   ├─ source_documents/       原始 DOCX
   ├─ accepted/               当前有效解析版本 DOCX
   ├─ pdf/                    当前有效 PDF
   └─ migration_manifest.json
```

历史 ParseRun、ChunkRun 和 IndexRun 记录保留在数据库中。只迁移 active 链路需要的原始 DOCX、accepted DOCX 和 PDF；Markdown、临时 JSON、重复报告、测试产物、模型权重和 Qdrant storage 均不纳入工程。

## 4. 启动与验证

问答联调需分别启动 RAG 8010 与 Platform 8020：

```powershell
Set-Location 'D:\2-code\rag'
& 'D:\3-anaconda\envs\py312\python.exe' run_rag_api.py
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
```

最小测试和数据校验见 [迁移验证记录](testing/KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md)。真实问答仍要求本机 Qdrant 与三个模型服务可用。

## 5. 后续开发顺序

文档处理管理功能按 [文档处理模块规划](DOCUMENT_PROCESSING_MODULE_PLAN.md) 开发：先增加任务表和单进程 Worker，再实现上传、ParseRun 审核、ChunkRun 审核与 IndexRun 发布页面。不要在 FastAPI 请求线程或 `BackgroundTasks` 中执行完整解析和索引。
