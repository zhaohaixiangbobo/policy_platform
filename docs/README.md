# 项目文档总台账

**P5交付包核验（2026-10-12）：** 四ARM64归档已本地核验通过，当前操作入口为[UOS部署清单](deployment/P5_UOS_DEPLOYMENT_CHECKLIST.md)；先核验→用户上传→服务器只读检查，未部署。

**P5构建隔离修订（2026-10-12）：** 专用policy-p5-arm64、BuildKit v0.21.0、镜像站manifest参数及四镜像直接tar导出；两个小探针待用户执行，不改变P4镜像存储。最新命令见[交付说明第3节](deployment/P5_ARM64_DELIVERY.md#3-专用构建器与手动执行本轮只做静态检查)。

**P5交付准备（2026-10-12）：** [ARM64交付说明](deployment/P5_ARM64_DELIVERY.md)登记独立生产Compose、固定摘要候选清单及用户手动构建/导出命令；本轮不执行镜像构建或服务器部署。

**P5 服务器基线（2026-10-12）：** 用户核实 /data 挂载、Docker/containerd 存储与启动保护完成；Compose v5.0.0-rc.2 暂保留。以[UOS 环境基线](deployment/UOS_P5_ENVIRONMENT_BASELINE.md)为准，不重复配置存储；尚未部署项目。

**当前P4结论（2026-10-12）：本地最小验收通过，可进入P5，非生产放行。** 新api/web已启用，池采样/资源/门户配置/入口巡检通过；权威记录为[收口验收](testing/P4_CLOSEOUT_2026-10-12.md)（CURRENT）。下方“待构建”为此前过程。

2026-10-12 门户入口版本 `portal_runtime_config_v1`：宿主JSON运行时外链配置已实现，待用户构建api/web后启用；使用说明及配置路径见[门户文档](PLATFORM_PORTAL.md)。无数据库迁移，原认证与制度入口不变。

P4当前状态统一见 [2026-10-12收口验收](testing/P4_CLOSEOUT_2026-10-12.md)：用户业务闭环通过，存储及应用重建持久化一致；连接池采样代码和隔离验证完成，待用户重建镜像及最终巡检。该记录为IN_PROGRESS，优先于旧P4文档的阶段快照。

2026-10-12 部署更新：P4 已应用 Knowledge `k0004_render_metadata`，启用正式 LO26.8.1.1 镜像及字体覆盖。
API 8088 代理就绪、Worker 和字体检查通过；历史 PDF/索引保持不变。真实新上传闭环待验收。

2026-10-12 转换更新：`lo-uno-compress-v1` 已接入代码；LibreOffice 26.8.1.1 + 外置授权字体门禁。
Knowledge 代码 head 为 `k0004_render_metadata`（本轮未应用），Platform 仍 `0013_worker_leases`。
运行环境未升级；启用、最小测试与验收边界见[字体部署说明](deployment/LIBREOFFICE_FONTS.md)。

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
| [`deployment/P5_UOS_DEPLOYMENT_CHECKLIST.md`](deployment/P5_UOS_DEPLOYMENT_CHECKLIST.md) | CURRENT | P5部署必读 | 20261012-224157-ab528108交付核验、上传白名单、只读环境检查与后续放行边界 |
| [`deployment/P5_ARM64_DELIVERY.md`](deployment/P5_ARM64_DELIVERY.md) | IN_PROGRESS | P5交付必读 | ARM64候选锁、生产配置、离线交付命令及未执行验收边界 |
| [`deployment/UOS_P5_ENVIRONMENT_BASELINE.md`](deployment/UOS_P5_ENVIRONMENT_BASELINE.md) | CURRENT | P5部署必读 | 用户实测服务器基线、已完成存储保护、版本保留和未部署边界 |
| [`PLATFORM_PORTAL.md`](PLATFORM_PORTAL.md) | CURRENT | 门户/认证任务必读 | platform_portal_v1；双登录入口、共用认证、六模块门户、构建开关；完整实屏验收待完成 |
| [`LEARNING_MATERIALS.md`](LEARNING_MATERIALS.md) | CURRENT | 学习资料推荐必读 | learning_materials_v1；提交后并列入口、本人/期限/权限校验、每类1条；实屏待验收 |
| [`testing/SUPPORTING_MATERIALS_M4_VERIFICATION_2026-09-26.md`](testing/SUPPORTING_MATERIALS_M4_VERIFICATION_2026-09-26.md) | CURRENT | M4验收时 | 23项后端、14项前端测试及typecheck/build通过；真实模型和浏览器手工验收待完成 |
| [`SUPPORTING_MATERIALS_M4.md`](SUPPORTING_MATERIALS_M4.md) | REFERENCE | 资料推荐演进 | 旧评分已由material_search_v3替代；ALL问答及学习提交后辅助资料 |
| [`SUPPORTING_MATERIALS_V2.md`](SUPPORTING_MATERIALS_V2.md) | CURRENT | 资料字段契约 | supporting_materials_v2；十列案例、三字段图片、手动发布 |
| [`SUPPORTING_MATERIALS_V3.md`](SUPPORTING_MATERIALS_V3.md) | CURRENT | 检索与聊天任务首先阅读 | material_search_v3；主题匹配、原文片段、纯案例/流程图分流 |
| [`SUPPORTING_MATERIALS.md`](SUPPORTING_MATERIALS.md) | REFERENCE | 历史机制参考 | v1七列字段已由v2替代；权限和版本机制保留 |
| [`testing/SUPPORTING_MATERIALS_V2_2026-10-09.md`](testing/SUPPORTING_MATERIALS_V2_2026-10-09.md) | CURRENT | v2验收与清理记录 | 最小测试、真实样本校验、旧资料清空范围 |
| [`testing/SUPPORTING_MATERIALS_VERIFICATION_2026-09-25.md`](testing/SUPPORTING_MATERIALS_VERIFICATION_2026-09-25.md) | CURRENT | 配套资料验收时 | 隔离最小测试、迁移与前端构建；实屏验收待完成 |
| [`LEARNING_ASSESSMENT.md`](LEARNING_ASSESSMENT.md) | CURRENT | 自测任务必读 | 生成learning_assessment_v2；UI learning_assessment_ui_v2；最多15题、24小时；已有模型验证记录，浏览器验收待完成 |
| [`testing/LEARNING_UI_VERIFICATION_2026-09-24.md`](testing/LEARNING_UI_VERIFICATION_2026-09-24.md) | CURRENT | 自测UI验收时 | UI v2.1轻量视觉、等高双栏、进度面板；三种桌面宽度实屏验收待完成；后端保持不变 |
| [`testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md`](testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md) | CURRENT | 自测验收时 | 17项最小测试、类型检查、本机0011迁移；真实模型超时待验收，空库问题已由后续记录关闭 |
| [`testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md`](testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md) | CURRENT | Worker/迁移必读 | worker_supervision_v1；固定历史迁移、隔离SQLite重放；head保留0011 |
| [`deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md`](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md) | CURRENT / IN_PROGRESS | 数据库迁移/部署必读 | postgres_compose_plan_v1.3：P0—P3本地最小验收通过；P4构建配置已准备，待用户构建，P5待实施，旧存储保留 |
| [`decisions/ADR-0006-POSTGRES-DATABASE-BOUNDARY.md`](decisions/ADR-0006-POSTGRES-DATABASE-BOUNDARY.md) | CURRENT | 数据库任务必读 | PG17双database、双迁移和权限边界 |
| [`testing/POSTGRES_P0_P1_VERIFICATION_2026-10-10.md`](testing/POSTGRES_P0_P1_VERIFICATION_2026-10-10.md) | HISTORICAL | P0/P1追溯 | 当时环境及19项验证；当前运行见P2 |
| [`testing/POSTGRES_P2_VERIFICATION_2026-10-10.md`](testing/POSTGRES_P2_VERIFICATION_2026-10-10.md) | CURRENT | PG开发启动必读 | P1收口、P2 Core仓储与迁移、12项测试、初始化/启动及P3边界 |
| [`testing/POSTGRES_P3_PROGRESS_2026-10-10.md`](testing/POSTGRES_P3_PROGRESS_2026-10-10.md) | HISTORICAL | P3首批追溯 | 初始互斥及README更新记录 |
| [`testing/POSTGRES_P3_VERIFICATION_2026-10-11.md`](testing/POSTGRES_P3_VERIFICATION_2026-10-11.md) | CURRENT | P3开发/运维必读 | 0013/k0003；本地最小验收及用户登录态联合验收通过，有条件进入P4；专项边界保留 |
| [`testing/DOCKER_P4_PROGRESS_2026-10-11.md`](testing/DOCKER_P4_PROGRESS_2026-10-11.md) | CURRENT / IN_PROGRESS | P4运行验收必读 | 镜像/空库/管理员/六服务就绪；6项最小测试，巡检及Web DNS修复；待业务闭环和持久化验收 |
| [`deployment/COMPOSE_LOCAL.md`](deployment/COMPOSE_LOCAL.md) | CURRENT / IN_PROGRESS | P4本地操作必读 | 固定摘要、手动构建、独立卷、迁移指纹、初始化及更新边界 |
| [`deployment/LIBREOFFICE_FONTS.md`](deployment/LIBREOFFICE_FONTS.md) | CURRENT / IN_PROGRESS | PDF字体部署必读 | 只读授权字体挂载与9项匹配通过；两份试转字体嵌入正确，Word分页对照未通过 |
| [`deployment/archived-sqlite-tools/README.md`](deployment/archived-sqlite-tools/README.md) | ARCHIVED | 历史工具追溯 | 登记目录内六份源码快照；原执行入口已阻断，不能用于PG运维 |
| [`deployment/container.env.example`](deployment/container.env.example) | REFERENCE | 容器准备时 | 已切换PG URL及生产命名空间占位；完整Compose验收待P4 |
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
| [`decisions/ADR-0005-SUPPORTING-MATERIALS.md`](decisions/ADR-0005-SUPPORTING-MATERIALS.md) | CURRENT | 配套资料归Platform独立资源，不进入制度流水线 |
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
| [`testing/CASE_EXTRACTION_EVALUATION_2026-09-25.md`](testing/CASE_EXTRACTION_EVALUATION_2026-09-25.md) | REFERENCE | 配套资料前置评估；两轮各6条真实模型调用，七列样本供用户审核，尚未批准自动入库 |
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
| 部署准备与数据库迁移 | postgres_compose_plan_v1.3；P0—P3本地最小验收通过 | [部署方案](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md) | 当前代码PG-only，旧存储保留；有条件进入P4，非生产放行，专项边界继续验收 |
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
| Platform迁移最新头 | 0013_worker_leases；历史迁移保留 | [PG验证](testing/POSTGRES_P3_VERIFICATION_2026-10-11.md) | 三类任务租约字段；版本表app只读 |
| Knowledge迁移最新头 | k0003_worker_operation | [PG验证](testing/POSTGRES_P3_VERIFICATION_2026-10-11.md) | 操作代次/回执；API/Worker不执行DDL |
| 配套资料库（2026-10-11） | supporting_materials_v2 / material_search_v3；字段不变，主题匹配及纯资料聊天分流 | [当前字段](SUPPORTING_MATERIALS_V2.md) / [检索分流](SUPPORTING_MATERIALS_V3.md) | 问答/学习推荐已接入；BM25未实施；视觉模型忽略 |
| Worker启动与停止 | worker_supervision_v1；真实PID、本机角色锁、功能开关、阶段边界停止 | [本机运行](deployment/LOCAL_DEVELOPMENT.md) | 实际业务长任务Ctrl+C由用户手动验收 |
| 学习成效检测 | learning_assessment_v2；单题一批、生成3路并发/串行审校，最多15题，24小时槽位；UI learning_assessment_ui_v2双分区 | [功能说明](LEARNING_ASSESSMENT.md) | 已有真实模型10题验证记录；浏览器人工验收及模型稳定性复测待完成，无长期考试管理 |
| 前端包 | @policy-platform/frontend 0.1.0 | [package.json](../frontend/package.json) | 包版本不代表RAG契约版本 |
| 回答展示S1 | 三状态共用公开正文和引用；空白正文兜底；类型检查通过 | [ChatPage.tsx](../frontend/src/pages/ChatPage.tsx) | 浏览器交互待验收；RAG/Citation版本保持原值 |
| 引用/澄清展示 | 引用快照状态；补充卡片填写短回复，补全后可展开查询条件 | [EvidencePanel.tsx](../frontend/src/components/EvidencePanel.tsx)、[ChatPage.tsx](../frontend/src/pages/ChatPage.tsx) | S3已接入，浏览器交互待验收 |
| 查询耗时追踪 | query_timing_v1；阶段、HTTP尝试、异常及校验次数写日志 | [telemetry.py](../backend/knowledge/telemetry.py) | 不改变RAG/Context/Citation契约版本 |

模型名和服务修订可由环境覆盖，不能把配置中的deployment-unreported或默认模型名写成已核验部署版本。IndexRun、ParseRun、ChunkRun是数据运行编号，不是上述算法/契约版本。

2026-09-27 学习检测更新：Prompt 保持 learning_assessment_v2；模型生成/审校加入单调用最多三次有限重试、脱敏失败日志及分类错误提示。最小学习回归23项通过；需重启学习Worker加载，真实15题待人工复测。详见 [学习检测说明](LEARNING_ASSESSMENT.md)。
