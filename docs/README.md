# 项目文档总台账

> 文件说明：这是 `policy-platform` 文档体系的统一入口。登记每份项目文档的用途、状态、
> 权威范围和阅读时机；新增、替代、归档项目文档时必须同步维护本台账。

## 1. 项目开始时的阅读顺序

任何新开发任务先阅读以下六份材料，再按任务类型补充阅读专题文档：

1. [工程 README](../README.md)：工程结构、固定工具链和启动入口。
2. [项目交接文档](PROJECT_HANDOFF.md)：当前实现状态、数据边界和近期约束。
3. [ADR-0002：统一知识模块](decisions/ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md)：单工程、双数据库边界。
4. [ADR-0004：进程内 RAG 查询](decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md)：当前问答运行边界。
5. [本机开发运行说明](deployment/LOCAL_DEVELOPMENT.md)：本机配置和启动命令。
6. 与本次任务对应的 API、入库流程、UI、测试或运维专题文档。

## 2. 状态定义

| 状态 | 含义 | 维护方式 |
|---|---|---|
| `CURRENT` | 当前事实源或当前操作指南 | 行为变化时必须同步更新 |
| `REFERENCE` | 仍有参考价值，但不单独决定当前业务行为 | 与当前事实冲突时服从对应CURRENT文档或现行ADR |
| `HISTORICAL` | 已完成阶段的计划、状态或验证记录 | 保留原始结论，只补充历史说明和替代链接 |
| `SUPERSEDED` | 已被后续决策明确取代 | 不再作为实施依据，正文保留用于审计追溯 |
| `PLANNED` | 开发方案，功能尚未实施 | 按阶段更新状态，通过实现和验收后再登记为当前能力 |
| `IN_PROGRESS` | 分阶段实施中 | 分别记录已实现、已验证和待实施范围 |

## 3. 权威范围规则

- 当前部署与模块边界：`PROJECT_HANDOFF.md` 和状态为 `CURRENT` 的ADR。
- 对外接口字段：`api/openapi.json`；人工说明由 `api/PLATFORM_API_V1.md` 同步解释。
- 本机启动和故障处理：`deployment/LOCAL_DEVELOPMENT.md`、`deployment/OPERATIONS.md`。
- 入库、审核、分块、索引和问答数据流：`INGESTION_TO_QA_WALKTHROUGH.md`。
- 尚未实施事项：`代办.md`。完成事项必须移出，并链接实现记录或当前设计。
- UI参考图只决定视觉方向；功能、权限和数据状态以当前业务契约为准。
- 代码与文档不一致时先判断是实现缺陷还是文档漂移，不以现状自动覆盖业务决策。

## 4. 文档登记表

### 4.1 当前入口、设计与操作文档

| 文档 | 状态 | 启动必读 | 权威范围 |
|---|---|---:|---|
| `docs/README.md` | CURRENT | 是 | 文档分类、阅读顺序和维护规则 |
| [`LEARNING_ASSESSMENT.md`](LEARNING_ASSESSMENT.md) | CURRENT | 自测任务必读 | 生成learning_assessment_v2；UI learning_assessment_ui_v2；最多15题、24小时；已有模型验证记录，浏览器验收待完成 |
| [`testing/LEARNING_UI_VERIFICATION_2026-09-24.md`](testing/LEARNING_UI_VERIFICATION_2026-09-24.md) | CURRENT | 自测UI验收时 | UI v2.1轻量视觉、等高双栏、进度面板；三种桌面宽度实屏验收待完成；后端保持不变 |
| [`testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md`](testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md) | CURRENT | 自测验收时 | 17项最小测试、类型检查、本机0011迁移；真实模型超时待验收，空库问题已由后续记录关闭 |
| [`testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md`](testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md) | CURRENT | Worker/迁移必读 | worker_supervision_v1；固定历史迁移、隔离SQLite重放；head保留0011 |
| [`deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md`](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md) | CURRENT | 部署/索引维护必读 | docker_ready_v1、index_storage_retirement_v1；1—7存储已退役，保留8、9；双MySQL与Compose为下一阶段建议 |
| [`deployment/container.env.example`](deployment/container.env.example) | REFERENCE | 容器准备时 | Linux环境模板；实际Compose尚未打包 |
| [`RAG_QUALITY_EVOLUTION_PLAN.md`](RAG_QUALITY_EVOLUTION_PLAN.md) | IN_PROGRESS | 问答增强任务必读 | 方案1.3；S1—S3代码完成；S3相关34项测试及类型检查通过；真实模型/浏览器待验收；S4/S5未开始 |
| [`../README.md`](../README.md) | CURRENT | 是 | 工程结构、工具链和快速启动 |
| [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md) | CURRENT | 是 | 当前工程状态、边界和交接约束 |
| [`DOCUMENT_PROCESSING_MODULE_PLAN.md`](DOCUMENT_PROCESSING_MODULE_PLAN.md) | CURRENT | 按需 | 文档处理与制度入库模块设计 |
| [`INGESTION_TO_QA_WALKTHROUGH.md`](INGESTION_TO_QA_WALKTHROUGH.md) | CURRENT | 入库/问答任务必读 | 端到端状态、数据和调用链 |
| [`api/PLATFORM_API_V1.md`](api/PLATFORM_API_V1.md) | CURRENT | API任务必读 | Platform API人工说明 |
| [`api/openapi.json`](api/openapi.json) | CURRENT | API任务必读 | 对外HTTP接口机器契约 |
| [`deployment/LOCAL_DEVELOPMENT.md`](deployment/LOCAL_DEVELOPMENT.md) | CURRENT | 是 | 本机配置、启动和最小验证 |
| [`deployment/OPERATIONS.md`](deployment/OPERATIONS.md) | CURRENT | 运维任务必读 | 数据操作、备份恢复和故障排查 |
| [`UI_DESIGN_SPEC.md`](UI_DESIGN_SPEC.md) | REFERENCE | 前端任务必读 | 一期视觉基线，不决定新增业务功能 |
| [`代办.md`](代办.md) | CURRENT | 规划任务必读 | 已确认但尚未实施的事项 |
| [`testing/RAG_MANUAL_TESTSET_GUIDE.md`](testing/RAG_MANUAL_TESTSET_GUIDE.md) | CURRENT | 测试任务按需 | RAG人工测试集组织与验收方法 |
| [`testing/CHROME_89_SMOKE.md`](testing/CHROME_89_SMOKE.md) | REFERENCE | 兼容性任务按需 | Chrome 89异机手工验证清单 |

### 4.2 架构决策

| 文档 | 状态 | 替代关系或用途 |
|---|---|---|
| [`decisions/ADR-0001-SEPARATE-PLATFORM-AND-KNOWLEDGE-ENGINE.md`](decisions/ADR-0001-SEPARATE-PLATFORM-AND-KNOWLEDGE-ENGINE.md) | SUPERSEDED | 已被ADR-0002取代 |
| [`decisions/ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md`](decisions/ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md) | CURRENT | 统一知识模块、双数据库和数据所有权 |
| [`decisions/ADR-0003-RAG-HTTP-QUERY-BOUNDARY.md`](decisions/ADR-0003-RAG-HTTP-QUERY-BOUNDARY.md) | SUPERSEDED | 已被ADR-0004取代 |
| [`decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md`](decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md) | CURRENT | Platform进程内RAG问答边界 |
| [`decisions/KNOWLEDGE_MODULE_MIGRATION_PLAN.md`](decisions/KNOWLEDGE_MODULE_MIGRATION_PLAN.md) | HISTORICAL | 知识模块迁移执行计划和验收依据 |

### 4.3 历史规划与实施记录

| 文档 | 状态 | 保留原因 |
|---|---|---|
| [`制度知识智能服务平台开发设计文档_V2.md`](制度知识智能服务平台开发设计文档_V2.md) | REFERENCE | 第一期产品基线和历史需求背景；技术边界以当前ADR为准 |
| [`PHASE2_CLEAN_REBUILD_IMPLEMENTATION_PLAN.md`](PHASE2_CLEAN_REBUILD_IMPLEMENTATION_PLAN.md) | HISTORICAL | 第二期清空重建的已执行方案 |
| [`PHASE2_IMPLEMENTATION_STATUS_2026-08-30.md`](PHASE2_IMPLEMENTATION_STATUS_2026-08-30.md) | HISTORICAL | 2026-08-30阶段状态快照 |
| [`PHASE2_PUBLICATION_CONSISTENCY_2026-09-04.md`](PHASE2_PUBLICATION_CONSISTENCY_2026-09-04.md) | HISTORICAL | 发布一致性改造记录；现行规则已纳入当前代码和流程文档 |

### 4.4 历史测试与验收记录

| 文档 | 状态 | 保留原因 |
|---|---|---|
| [`testing/QUERY_TIMING_VERIFICATION_2026-09-19.md`](testing/QUERY_TIMING_VERIFICATION_2026-09-19.md) | HISTORICAL | 引用状态、补充卡片和三个慢问题分段复测；捕获Reranker连接重试 |
| [`testing/KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md`](testing/KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md) | HISTORICAL | 知识模块迁移当日验证证据 |
| [`testing/M2_M4_MODERN_BROWSER_SMOKE_2026-08-23.md`](testing/M2_M4_MODERN_BROWSER_SMOKE_2026-08-23.md) | HISTORICAL | 迁移前M2-M4浏览器冒烟记录 |
| [`testing/MODERN_BROWSER_SMOKE_2026-08-23.md`](testing/MODERN_BROWSER_SMOKE_2026-08-23.md) | HISTORICAL | 一期现代浏览器构建与布局记录 |
| [`testing/PHASE1_ACCEPTANCE.md`](testing/PHASE1_ACCEPTANCE.md) | HISTORICAL | 第一期验收清单，部分运行步骤已过时 |
| [`testing/PHASE1_VERIFICATION_2026-08-24.md`](testing/PHASE1_VERIFICATION_2026-08-24.md) | HISTORICAL | 第一期完成验证记录 |

### 4.5 UI参考资产

| 文件 | 状态 | 用途 |
|---|---|---|
| [`ui-reference/对话.png`](ui-reference/对话.png) | REFERENCE | 当前对话输入区视觉参考 |
| [`ui-reference/chat-reference.png`](ui-reference/chat-reference.png) | REFERENCE | 一期对话页面视觉参考 |
| [`ui-reference/parse_v2.png`](ui-reference/parse_v2.png) | REFERENCE | 解析与分块审核页面视觉参考 |

## 5. 后续文档维护流程

1. 新建项目文档时，同时登记路径、状态、权威范围和阅读时机。
2. 当前设计变化时更新对应CURRENT文档；涉及架构取舍时新增ADR。
3. ADR被替代时只更新状态和替代链接，不删除或重写历史决策正文。
4. 阶段计划完成后改为HISTORICAL，并把仍有效的规则提炼到CURRENT文档。
5. 测试结果使用日期文件名；测试方法保存在不带日期或明确标为CURRENT的指南中。
6. 删除或移动文件前检查本台账、Markdown链接、工程README和代码注释中的引用。
7. 每个里程碑结束时核对文件是否存在、状态是否准确、CURRENT内容是否冲突。
8. 问答功能按 [分阶段方案第6节](RAG_QUALITY_EVOLUTION_PLAN.md#6-文档同步与完成定义)同步文档；实现、测试及版本登记同时完成后才能关闭阶段。
9. 本台账第7节记录当前代码实际装配版本，目标版本只放在计划列。上线后核验响应provenance及实际开关；旧记录与数据Run ID不能据此批量改写。

## 6. 本次核验

- 首次登记日期：2026-09-14。
- 登记范围：`docs` 下全部24份既有Markdown、1份OpenAPI JSON、3份UI参考资产，
  以及本次新增的总台账和工程根README入口。
- 当前明确生效的架构决策：ADR-0002、ADR-0004。

## 7. 当前实现版本台账

核验日期：2026-09-19。以下为当前仓库代码和Web Runtime装配结果，不代表正在运行的进程已经重启至同一版本。模型部署版本以服务和实际响应为准；历史回答使用各自保存的版本。

| 部分 | 当前代码使用版本/行为 | 事实源 | 计划变化（尚未实施） |
|---|---|---|---|
| 应用架构 | ADR-0002 + ADR-0004；进程内KnowledgeService，无8010依赖 | [ADR-0004](decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md) | 保持边界 |
| 部署准备（2026-09-24） | docker_ready_v1；跨平台入口、外部配置、Linux依赖标记 | [部署准备](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md) | 双MySQL、知识库SQLAlchemy/Alembic和Compose尚未实施 |
| 索引存储生命周期（2026-09-24） | index_storage_retirement_v1；已退役1—7，保留8、9；复用检查物理存储 | [存储维护](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md#3-旧索引复用和退役契约) | 受控恢复、孤儿清理和自动定期清理未实现 |
| Platform HTTP接口 | /api/v1 | [API说明](api/PLATFORM_API_V1.md)、[OpenAPI](api/openapi.json) | S2增加公开回答字段 |
| 知识结果契约 | rag_api_v1_2；兼容读取v1_1 | [contracts.py](../backend/knowledge/contracts.py) | S2已实现 |
| 解析 | parser 0.1.4；article_title_v2 | [pipeline.py](../backend/knowledge/parser/pipeline.py) | 本方案不改解析 |
| 分块 | 1.0.2；retrieval_template_v1 | [chunker.py](../backend/knowledge/chunking/chunker.py) | 复用现有父子分块 |
| 索引 | indexer 1.0.0；policy_point_v1 | [indexing/config.py](../backend/knowledge/indexing/config.py) | S4增加版本化词法派生索引 |
| Embedding契约 | embedding_contract_v1 | [indexing/config.py](../backend/knowledge/indexing/config.py) | 保持 |
| 重排契约 | reranker_contract_v2 | [indexing/config.py](../backend/knowledge/indexing/config.py) | 扩展候选池配置 |
| Web检索装配 | dense20_rerank8_v3；Dense20→Rerank8 | [runtime.py](../backend/knowledge/rag/runtime.py) | S4增加Hybrid试验；默认类的dense20_rerank5_v2不是Web配置 |
| Context | context_builder_v1；最多8条、8000 token估算预算，父块扩展关闭 | [rag/config.py](../backend/knowledge/rag/config.py) | S4补位；S5拟context_builder_v2_1 |
| 生成契约/配置 | generator_contract_v1 / generator_runtime_v3；thinking关闭 | [rag/config.py](../backend/knowledge/rag/config.py) | S2已实现 |
| 答案严格Schema | policy_rag_answer_schema_v3 | [models.py](../backend/knowledge/rag/models.py)、[rag/config.py](../backend/knowledge/rag/config.py) | S2已实现 |
| Prompt | policy_rag_prompt_v4 | [prompt.py](../backend/knowledge/rag/prompt.py) | S2已实现 |
| Pipeline | rag_pipeline_v2 | [rag/config.py](../backend/knowledge/rag/config.py) | 单次生成同时输出判断字段 |
| Answerability / 多轮补全 | S2字段贯通；S3 clarification_rewrite_v1，Platform记录真实rewrite_used | [conversation_context.py](../backend/app/application/conversation_context.py) | 无额外模型调用；复杂自由改写关闭 |
| Quality Gate | answer_quality_gate_v3；默认关闭，可配置 | [quality_gate.py](../backend/knowledge/rag/quality_gate.py)、[runtime.py](../backend/knowledge/rag/runtime.py) | 启用时包含部分答案事实校验 |
| 语义验证Schema | support_verifier_schema_v2 / support_verifier_input_v2 | [quality_gate.py](../backend/knowledge/rag/quality_gate.py) | 不新增默认模型调用 |
| Citation / Evidence UID | citation_v1 / evidence_uid_v1 | [models.py](../backend/knowledge/rag/models.py) | 保持；父块使用自己的证据身份 |
| Platform迁移最新头 | 0011_learning_assessment；历史结构已冻结，SQLite空库及增量重放通过 | [修复记录](testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md) | 未切换MySQL，需另做MySQL环境验证 |
| Worker启动与停止 | worker_supervision_v1；真实PID、本机角色锁、功能开关、阶段边界停止 | [本机运行](deployment/LOCAL_DEVELOPMENT.md) | 实际业务长任务Ctrl+C由用户手动验收 |
| 学习成效检测 | learning_assessment_v2；单题一批、生成3路并发/串行审校，最多15题，24小时槽位；UI learning_assessment_ui_v2双分区 | [功能说明](LEARNING_ASSESSMENT.md) | 已有真实模型10题验证记录；浏览器人工验收及模型稳定性复测待完成，无长期考试管理 |
| 前端包 | @policy-platform/frontend 0.1.0 | [package.json](../frontend/package.json) | 包版本不代表RAG契约版本 |
| 回答展示S1 | 三状态共用公开正文和引用；空白正文兜底；类型检查通过 | [ChatPage.tsx](../frontend/src/pages/ChatPage.tsx) | 浏览器交互待验收；RAG/Citation版本保持原值 |
| 引用/澄清展示 | 引用快照状态；补充卡片填写短回复，补全后可展开查询条件 | [EvidencePanel.tsx](../frontend/src/components/EvidencePanel.tsx)、[ChatPage.tsx](../frontend/src/pages/ChatPage.tsx) | S3已接入，浏览器交互待验收 |
| 查询耗时追踪 | query_timing_v1；阶段、HTTP尝试、异常及校验次数写日志 | [telemetry.py](../backend/knowledge/telemetry.py) | 不改变RAG/Context/Citation契约版本 |

模型名和服务修订可由环境覆盖，不能把配置中的deployment-unreported或默认模型名写成已核验部署版本。IndexRun、ParseRun、ChunkRun是数据运行编号，不是上述算法/契约版本。
