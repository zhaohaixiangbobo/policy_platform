# 制度知识智能服务平台项目交接文档

**2026-10-13 Web兼容性修复：** UOS64KiB页下Nginx upstream zone至少512KiB，deploy/nginx.conf改为1m；用户服务器待nginx -t及仅Web重建验收。已有只读配置挂载支持修复，无需重构建镜像。调用三份Compose需设置POLICY_FONT_DIR；单文件sed原子替换后用force-recreate确保新挂载生效。

**P5最新进度：** 交付轮次20261012-224157-ab528108四个tar本地SHA256、linux/arm64、标签和元数据核验通过；迁移/初始化四入口与镜像字节一致。本轮创建本地白名单配置上传包，不含密码/字体/业务数据；未SSH、上传、加载镜像或部署。按[UOS部署清单](deployment/P5_UOS_DEPLOYMENT_CHECKLIST.md)分步继续。

**P5构建隔离修订：** 使用独立docker-container builder policy-p5-arm64（BuildKit v0.21.0），预检支持镜像站、PG/Qdrant也直接导出tar，不再本地pull/tag/save。缓存保留；两个小验证仅准备未运行；用户手动创建builder与后续构建，见P5交付说明第3节。

**P5 ARM64交付准备：** 独立compose.p5.yaml复用现有字体/运行覆盖，80端口及/data持久化；候选摘要锁与手动构建导出脚本已准备。ARM64 manifest只读核对因Docker Hub超时未完成，未构建或部署；后续先读[交付说明](deployment/P5_ARM64_DELIVERY.md)。服务器Compose保持v5.0.0-rc.2，HTTP及异机备份边界以服务器基线为准。

**2026-10-12 P5环境基线：** 用户确认 UOS ARM64 的 /data 数据盘、/data/docker 及其管理的 containerd 存储、systemd 挂载保护完成；不重复调整。Compose v5.0.0-rc.2 暂时保留，正式部署前验证兼容性；安装来源待确认，项目镜像/容器/数据库尚未部署。本轮仅记录，见[服务器基线](deployment/UOS_P5_ENVIRONMENT_BASELINE.md)。

**2026-10-12 P4已收口：** 用户完成新文档业务检查，新api/web及运行覆盖配置已启用，最终巡检无告警。本地最小验收通过，可进入P5；生产ARM64、安全配置和恢复演练未放行。见[P4最终记录](testing/P4_CLOSEOUT_2026-10-12.md)。以下待构建描述为历史。

最新P4状态见 [收口验收](testing/P4_CLOSEOUT_2026-10-12.md)：55表/22文件/两个集合的重建持久化核验通过，用户业务检查通过；待采样代码镜像重建及最终巡检，无新数据库迁移。

2026-10-12 更新：下述 UNO 待部署工作已在 P4 启用。Knowledge head 为 k0004_render_metadata；
新镜像及只读字体挂载、API/Worker/代理就绪核验通过。历史 6 份制度及 active IndexRun 1 保留。
后续所有 Compose 启动继续带 `-f compose.yaml -f deploy/compose.fonts.yaml` 和 POLICY_FONT_DIR。
新上传至 Citation 闭环及 ARM64 验收待完成，见字体部署说明顶部。

## 2026-10-12 UNO 转换接入（待部署）

正式 Dockerfile 固定 LO 26.8.1.1；独立子进程、超时清理、字体检查及转换环境 JSON 已实现。
Knowledge 代码 head 为 k0004_render_metadata，本轮未迁移、未重建业务容器或发布索引。
新 PDF 按 ParseRun 保存且不覆盖旧文件。启用顺序见[字体说明](deployment/LIBREOFFICE_FONTS.md)。

## 2026-10-11 资料检索与聊天分流

阶段一、二已实施，见[资料v3](SUPPORTING_MATERIALS_V3.md)。字段仍v2；查询命中理由/原文句段、纯资料请求无模型分流；无PG迁移、无业务数据修改。BM25暂未实施。

## 2026-10-11 P4构建准备

三个基础镜像已由用户拉取并核验amd64版本；Dockerfile已锁定摘要。独立Compose、Nginx、配置生成脚本及迁移部署标识校验已准备，5项最小测试和配置检查通过。等待用户按[Compose本地说明](deployment/COMPOSE_LOCAL.md)手动构建，未创建新业务容器/卷，未操作旧数据；P4尚未验收通过。后续先空卷迁移及初始化，再容器闭环/持久化和运行巡检，不重复原环境登录验收。

## 2026-10-11 P3可靠性改造

当前Platform head为0013_worker_leases，Knowledge head为k0003_worker_operation。三类任务原子领取、心跳/代次保护、知识回执及受控发布恢复已实现。用户报告5173代理登录态联合验收及浏览器6份制度上传发布通过，不再重复登录测试。结合此前最小测试和active IndexRun 1只读核验，P3本地最小验收通过，有条件进入P4，非生产放行；故障及权限等专项边界继续保留。保留所有现有数据，不重置账号。新任务先读[P3验证与恢复记录](testing/POSTGRES_P3_VERIFICATION_2026-10-11.md)，下文P2版本和空库统计为历史事实。

## 2026-10-10 统一门户 v1

新增六模块门户及平台登录，复用原 Cookie 认证；原制度界面和业务路径保留。`/login` 为平台入口，`/portal/login` 为制度入口，`VITE_PORTAL_ENABLED=false` 可关闭门户。类型检查、构建和 4 项核心测试通过，完整登录态及三种桌面实屏验收待完成。见 [门户说明](PLATFORM_PORTAL.md)。

## 2026-10-09 配套资料v2

图片三字段、案例十列Excel、类型分离校验、原文摘要preview_text及推荐v2已更新。仍手动发布，隐私原样，数据库head不变。新任务先读[当前契约](SUPPORTING_MATERIALS_V2.md)及[验证记录](testing/SUPPORTING_MATERIALS_V2_2026-10-09.md)，旧七列评测仅供历史参考。

> 文件说明：记录 2026-09-14 进程内RAG、制度选择范围和权限预留后的当前工程边界。

## 1. 当前状态

**P2当前状态（2026-10-10，优先于下文历史记录）：** Platform PostgreSQL head为0012_supporting_materials，Knowledge为k0002_document_series_index；Core Repository、独立迁移及API/Worker启动只读检查已完成。12项PG最小测试及两类Worker空队列启动通过。使用scripts/dev-postgres.ps1选择新配置；当前代码只支持PG，旧.env不能启动新代码。新库用户/制度均为0，旧存储保持不变。真实外部服务闭环、原子领取和发布恢复留在P3。见[P2运行与验证](testing/POSTGRES_P2_VERIFICATION_2026-10-10.md)。以下P0/P1及较早运行描述保留为历史。

2026-10-10 P0/P1实施：本机隔离PostgreSQL 17.11容器已启动（127.0.0.1:55432），
platform空库0001—0012完整重放及19项最小测试通过；knowledge空库待P2。
Qdrant命名空间已配置化，旧Alias/collections及旧.env、SQLite、业务文件保留。
采用双database、独立owner/app、独立迁移预检及管理员初始化；没有新建默认管理员。
默认旧环境仍可使用，新环境尚不能启动完整API/Worker业务链路；Knowledge Core+Repository、
取消运行时DDL等在P2完成，完整可靠性及业务验收在P3。先数据库后Compose顺序不变。
见[当前迁移方案](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md)、
[P0/P1操作与验证](testing/POSTGRES_P0_P1_VERIFICATION_2026-10-10.md)和
[数据库边界ADR](decisions/ADR-0006-POSTGRES-DATABASE-BOUNDARY.md)。

2026-09-27：learning_materials_v1已接入提交后“查看制度依据”旁的案例/流程图入口；复用资料检索，题目生成评分不变，详见[学习辅助资料](LEARNING_MATERIALS.md)。

2026-09-26：material_search_v1统一资料检索与ALL问答辅助推荐已实现；资料不进入RAG答案，SELECTED暂不展示推荐，无数据库迁移。详见[配套资料M4](SUPPORTING_MATERIALS_M4.md)。

2026-09-25新增配套资料库supporting_materials_v1（M1—M3）：标准七列案例Excel预览确认、图片上传、草稿/修订/批量发布下架、独立关键词检索和详情。Platform迁移head为0012_supporting_materials，本机已应用；资料表归Platform，图片默认var/materials。需重启后端加载material.read/material.manage权限，刷新前端。未导入用户真实资料，不改问答、学习、知识库或Qdrant。M5案例辅助整理仅样本评估通过，正式导入不自动调用模型。见[功能文档](SUPPORTING_MATERIALS.md)与[验证记录](testing/SUPPORTING_MATERIALS_VERIFICATION_2026-09-25.md)。

2026-09-24学习自测现行生成版本为learning_assessment_v2（用户已完成单题分批、3路并发、串行审校及错误分类，模型验证记录见功能文档）。
本轮仅新增前端learning_assessment_ui_v2：配置/答题双分区、完成后自动切换一次、单题导航和结果复习侧栏。
第二轮已精修为learning_assessment_ui_v2.1：弱边框与轻提示、桌面等高双栏、最近检测进度面板；typecheck、build及6项前端测试通过，三种桌面宽度实屏验收因浏览器连接失败待完成。
接口、生成、评分、权限与数据库保持不变；6项前端状态测试及类型检查通过，浏览器连接不可用，视觉和真实交互验收待完成。
详见[UI验证记录](testing/LEARNING_UI_VERIFICATION_2026-09-24.md)。以下保留此前实施记录。

2026-09-24新增学习成效检测：最多15题、单制度全文/章节取材、独立生成与审校、后端评分、原文快照和本次弱项分析。
默认开关关闭，需独立learning-worker；本机0011迁移完成，17项最小测试和前端类型检查通过。
真实模型单题生成90秒超时、浏览器人工验收待完成。
空库历史迁移重复列已通过冻结0001/0002/0003/0005修复；联合Worker入口改为真实PID监督、
按开关启动和协作式停止。本次不变更业务数据与迁移head，见[修复记录](testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md)。
使用、启用和数据生命周期见[功能文档](LEARNING_ASSESSMENT.md)，本轮不安装依赖、不改知识索引。

2026-09-24：完成Docker-ready入口、配置、Linux依赖标记与旧索引清理保护。
IndexRun 1—7仅向量存储已退役，关系库历史保留；8保留，9仍为当前Alias目标。
该日实施详情见[部署与索引退役说明](deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md)；其中原MySQL建议已于2026-10-10替换为第5节PostgreSQL方案。
该次未创建镜像、Compose或切换数据库。

`D:\2-code\policy-platform` 已成为完整的本机测试工程：

- `frontend` 提供制度库、问答、反馈和诊断页面；
- `backend/app` 提供 Platform API 和平台业务服务；
- `backend/knowledge` 提供 Platform 管理流水线和进程内问答能力；
- PostgreSQL `platform` database保存平台业务数据；
- PostgreSQL `knowledge` database保存知识流水线和运行版本；旧SQLite仅保留不运行；
- `D:\2-code\rag` 不参与当前 Platform 运行，仅作为历史源工程保留。

当前问答边界事实源是 [ADR-0004](decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md)；ADR-0003 已废止，ADR-0002 的统一知识模块决策恢复为完整现行方案。

## 2. 强制边界

1. 浏览器只访问 Platform API，不直接访问数据库、Qdrant 或模型服务。
2. Platform 问答只能通过 `KnowledgeService` 调用进程内 `RagRuntime`，应用层不得越过该服务直接访问知识存储、Qdrant或模型客户端。
3. Platform数据与知识数据使用同一PostgreSQL实例的两个database，独立账号、仓储和Alembic版本记录。
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
