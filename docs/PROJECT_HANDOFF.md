# 制度知识智能服务平台项目交接文档

> 文件说明：记录 2026-09-14 进程内RAG、制度选择范围和权限预留后的当前工程边界。

## 1. 当前状态

2026-09-24：完成Docker-ready入口、配置、Linux依赖标记与旧索引清理保护。
IndexRun 1—7仅向量存储已退役，关系库历史保留；8保留，9仍为当前Alias目标。
详情及下一阶段双MySQL/Alembic建议见[部署与索引退役说明](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md)。
本轮未创建镜像、Compose或迁移MySQL。

`D:\2-code\policy-platform` 已成为完整的本机测试工程：

- `frontend` 提供制度库、问答、反馈和诊断页面；
- `backend/app` 提供 Platform API 和平台业务服务；
- `backend/knowledge` 提供 Platform 管理流水线和进程内问答能力；
- `var/platform.db` 保存平台业务数据；
- `var/knowledge/policy_parser.db` 保存知识流水线和运行版本；
- `D:\2-code\rag` 不参与当前 Platform 运行，仅作为历史源工程保留。

当前问答边界事实源是 [ADR-0004](decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md)；ADR-0003 已废止，ADR-0002 的统一知识模块决策恢复为完整现行方案。

## 2. 强制边界

1. 浏览器只访问 Platform API，不直接访问数据库、Qdrant 或模型服务。
2. Platform 问答只能通过 `KnowledgeService` 调用进程内 `RagRuntime`，应用层不得越过该服务直接调用 SQLite、Qdrant 或模型客户端。
3. Platform 数据与知识数据继续使用两个 SQLite，不合并表和迁移历史。
4. 新问答使用 `rag_api_v1_2`（兼容旧v1_1快照），保留三状态，增加Answerability、原因码和结构化澄清。
5. Citation 保留 `document_id`、`primary_node_id`、各类 run ID、证据快照及公开版本字段。
6. `quality_gate.version` 按响应保存，不写死版本，也不依赖受控 debug 草稿哈希、Claim 绑定或 Verifier 判定。
7. 响应 SLA、提示阈值和并发容量仍未冻结。
8. 原始文档不可覆盖；latest 与 active 分离；只有审核通过后才能切换 active。
9. Qdrant active alias 仅在 IndexRun 验证通过后切换。
10. 问答状态范围明确为 `CURRENT|HISTORICAL`，制度选择明确为 `ALL|SELECTED`；不使用
    `null` 或空数组推断用户意图。
11. `QueryScopeResolver` 统一计算“用户可访问 ∩ 用户选择 ∩ 状态范围 ∩ active IndexRun”，
    指定制度不可查询时绝不自动扩大到全库。
12. 当前 `DocumentAccessResolver` 允许有读取权限的用户访问全部正式制度；未来接入 4A 时只替换
    身份确认与本地制度授权解析，`RagRuntime` 只接收 Platform 计算后的制度范围。
13. Platform 在接收 RAG 响应后再次校验 Citation 的制度状态和 `document_id`，并在
    `platform.db` 中保存本轮用户选择及最终授权范围快照。
14. 制度废止和失效采用独立元数据修订流程：`REPEAL` 固定为 `repealed`，`EXPIRY` 固定为
    `expired`；普通修订不能改变效力状态，索引冻结拒绝流程类型与状态不一致的历史错误修订。

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

问答联调只需启动 Platform 8020 与前端：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
```

最小测试和数据校验见 [迁移验证记录](testing/KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md)。真实问答仍要求本机 Qdrant 与三个模型服务可用。

当前 active IndexRun 中暂无已废止或已失效制度，前端会禁用历史制度查询。首份历史制度进入
正式索引后的端到端验收步骤见 [代办事项](代办.md#3-首份历史制度检索验收)。

## 5. 后续开发顺序

2026-09-19追加：引用详情显示回答快照的制度状态；固定追问改为有条件的补充卡片。
新增query_timing_v1阶段日志。三个慢问题复测捕获一次Reranker连接重试导致的49.25秒查询，见[测试记录](testing/QUERY_TIMING_VERIFICATION_2026-09-19.md)；未调整检索策略和服务超时。

2026-09-19新增的问答增强工作按 [问答质量与混合检索分阶段方案](RAG_QUALITY_EVOLUTION_PLAN.md)执行。
S1代码完成并通过类型检查：依据不足也展示公开正文和引用，空白正文才兜底；浏览器交互待验收。
S2代码和0009迁移已完成，23项最小后端测试及类型检查通过；真实模型和浏览器验收待执行。
S3补全策略clarification_rewrite_v1和0010迁移已完成，34项相关测试及类型检查通过，真实模型/浏览器待验收。
S4/S5尚未实施，S6延后；当前版本见 [总台账第7节](README.md#7-当前实现版本台账)。
每阶段交付同时更新接口、运行说明、测试指南和版本台账，具体清单见方案第6节。

文档处理管理功能按 [文档处理模块规划](DOCUMENT_PROCESSING_MODULE_PLAN.md) 开发：先增加任务表和单进程 Worker，再实现上传、ParseRun 审核、ChunkRun 审核与 IndexRun 发布页面。不要在 FastAPI 请求线程或 `BackgroundTasks` 中执行完整解析和索引。
