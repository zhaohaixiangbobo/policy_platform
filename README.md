# 制度知识智能服务平台

**2026-10-12：P4本地最小验收通过，可进入P5。** 新api/web、运行时门户配置、字体及运行巡检已启用；入口`http://127.0.0.1:8088`。不是生产放行，详见[P4收口记录](docs/testing/P4_CLOSEOUT_2026-10-12.md)。下述待构建/待验收为各阶段历史记录。

2026-10-12 最新：P4 正式镜像已启用 UNO 与外置字体，Knowledge 已迁移到 `k0004_render_metadata`。
API/Worker 和 8088 代理健康检查通过，旧 PDF 与 active 索引保留；真实新上传闭环待验收。
后续启动请使用[字体覆盖配置](docs/deployment/LIBREOFFICE_FONTS.md)，下面“未应用”为此前阶段记录。

2026-10-12：UNO 转换业务代码已接入，配置 `lo-uno-compress-v1`；Knowledge 代码 head 更新为 `k0004_render_metadata`，尚未应用到运行库。先由用户构建正式镜像、预检并执行迁移，再启用字体挂载；现有容器和历史 PDF 未变。见[转换部署说明](docs/deployment/LIBREOFFICE_FONTS.md)。

2026-10-11 P4：用户镜像构建、独立空库迁移及六服务启动通过，入口`http://127.0.0.1:8088`；5项最小回归通过。待创建新管理员并验收容器业务闭环及持久化，尚未P4整体放行。见[P4本地构建与迁移说明](docs/deployment/COMPOSE_LOCAL.md)。原本机开发方式保持可用，旧数据不变。

2026-10-11：P3本地最小验收通过，有条件进入P4，非生产放行。用户已完成5173代理登录态联合验收及浏览器6份制度上传发布，不再重复登录测试；专项边界验证继续保留。当前Platform head为`0013_worker_leases`，Knowledge head为`k0003_worker_operation`，详见[P3验证与恢复说明](docs/testing/POSTGRES_P3_VERIFICATION_2026-10-11.md)。以下P2记录保留当时的版本；当前启动命令继续适用。

2026-10-10：P2 PostgreSQL适配及本地最小验收完成，当前代码只支持PG双database。Platform head：0012_supporting_materials；Knowledge head：k0002_document_series_index。新环境启动、独立管理员初始化及12项测试结果见[P2运行记录](docs/testing/POSTGRES_P2_VERIFICATION_2026-10-10.md)。旧数据保留，完整外部服务与故障恢复验收留在P3，完整Compose留在P4。

统一工作平台门户已接入：`/login` 为平台登录，`/portal/login` 保留原制度登录界面，`/portal` 为六模块工作台，`/` 仍为制度首页。认证及业务数据保持原体系。开关、兼容和验收说明见 [门户文档](docs/PLATFORM_PORTAL.md)。

本仓库负责制度平台前端、Platform API、平台业务数据和完整知识流水线。制度问答由 `backend/knowledge` 中的进程内 RAG Runtime 执行，新回答使用 `rag_api_v1_2`（兼容旧v1_1快照），不再启动或调用 `D:\2-code\rag` 的 8010 服务。

## 工程结构

配套资料字段使用 supporting_materials_v2，检索使用 material_search_v3：图片三个字段、案例十列Excel，主题匹配与原文片段，纯案例/流程图聊天请求直接查资料、不调用RAG。见[字段契约](docs/SUPPORTING_MATERIALS_V2.md)与[检索分流](docs/SUPPORTING_MATERIALS_V3.md)。

```text
frontend/                   React + TypeScript 前端
backend/app/                Platform API、聊天、反馈和平台业务数据
backend/knowledge/          解析、审核、分块、索引、检索和 RAG
backend/migrations/         Platform 数据库基线
backend/tests/              后端最小测试
scripts/                    启动、OpenAPI 和数据迁移工具
docs/                       架构、接口、运行和后续开发文档
backend/knowledge_migrations/ Knowledge独立Alembic迁移
var/materials/              配套资料原始图片（独立持久化目录）
var/knowledge/              历史知识文件；新环境文件路径由独立配置指定
```

数据所有权保持分开：会话、回答、Citation快照、反馈、用户及配套资料写入PostgreSQL platform库；正式制度文档、ParseRun、ChunkRun、IndexRun及元数据版本写入knowledge库。进程内RAG只读active IndexRun和Qdrant active alias，当前不检索配套资料。

## 固定工具链

- Node.js：`22.23.2`
- pnpm：`11.22.0`
- Python：`D:\3-anaconda\envs\py312\python.exe`
- Chrome 89：仅保留兼容基线设计，当前机器使用现代浏览器验证

依赖由用户手动安装。前端使用根目录的 `pnpm install`；后端依赖清单位于 `backend/requirements-dev.txt`。

## 初始化与启动

当前使用PostgreSQL 17双database；配置文件为`var/postgres-dev/platform.env`。先检查迁移计划，确认目标数据库和指纹后执行，不在服务启动时迁移，不重建已有数据库：

```powershell
Set-Location 'D:\2-code\policy-platform'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-platform-pg.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-knowledge-pg.py
# 审核各自预览后，向对应脚本传 --execute-plan '<当次指纹>'
```

空库首次使用时，交互式创建首个管理员（密码不会出现在命令行或日志中）：

```powershell
Set-Location 'D:\2-code\policy-platform'
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-knowledge-pg.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py --username '<工号>' --display-name '<姓名>'
```

分别启动后端和前端：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-postgres.ps1' api
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
```

需要处理入库任务时另开一个终端启动唯一Worker：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-postgres.ps1' worker
```

启用学习成效检测时，在另一个终端启动独立学习Worker：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-postgres.ps1' learning-worker
```

各服务独立进程、独立终端；学习Worker按配置开关运行。本机角色锁防止同目录重复启动。
更新代码前停止旧Worker；等待当前阶段完成，不强杀正在发布的进程。

Worker 默认把任务领取、阶段完成/失败、知识处理进度、IndexRun 构建和 Alias 切换事件写入
`logs/worker.log`，并按 10 MB、5 个历史文件滚动。路径和滚动参数可通过 `.env.example`
中的 `PLATFORM_WORKER_LOG_*` 变量调整。

访问地址：

- 前端：`http://127.0.0.1:5173/`
- Platform API：`http://127.0.0.1:8020`
- OpenAPI：`http://127.0.0.1:8020/api/docs`
- 就绪检查：`http://127.0.0.1:8020/api/v1/health/ready`

问答不需要8010。Platform后端首次问答时惰性初始化进程内RAG Runtime，使用所选PG环境文件中的Qdrant、Embedding、Reranker和Generator配置。普通问答默认`query_scope=CURRENT`，历史查询显式使用`HISTORICAL`。

回答质量门禁默认关闭。如需启用确定性回答覆盖与额外语义支撑校验，在所选环境文件中设置：

```dotenv
POLICY_QUALITY_GATE_ENABLED=true
```

修改后需要重启后端。关闭门禁不会关闭 Answer Parser 的严格 JSON、状态和 Citation 合法性校验。

## 知识流水线 CLI

统一入口：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m knowledge.cli --help
```

CLI 提供导入、解析、审核、分块、索引、激活和查询命令。管理后台与单Worker已贯通“上传 → ParseRun审核 → ChunkRun审核 → IndexRun核验 → 管理员确认发布”；新运行失败时继续使用上一版active数据。

DOCX渲染默认使用 `POLICY_DOCX_RENDER_ENGINE=auto_headless`，优先LibreOffice Headless，Windows未安装LibreOffice时回退到隐藏Word。服务器可固定为 `libreoffice` 并通过 `POLICY_LIBREOFFICE_PATH` 指定 `soffice`。

## 最小验证

```powershell
Set-Location 'D:\2-code\policy-platform'
pnpm typecheck

Set-Location 'D:\2-code\policy-platform\backend'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_pg_p1.py tests/test_pg_p2.py tests/test_pg_p3.py -q --tb=short -p no:cacheprovider -p no:tmpdir
```

本轮不自动执行模型联调、Qdrant 重建、负载测试、全量评测或 Chrome 89 实机测试。

## 事实源

- [配套资料库v2](docs/SUPPORTING_MATERIALS_V2.md)：十列案例Excel、三字段图片、手动发布；入口 `/materials`。Platform head仍为0012_supporting_materials，本次无需新迁移。图片目录var/materials需独立持久化。

- [学习成效检测功能与启用说明](docs/LEARNING_ASSESSMENT.md)：最多15题，最近一次24小时；默认关闭，使用独立学习Worker。代码及最小测试完成，真实模型/浏览器验收待完成。

- [项目文档总台账](docs/README.md)
- [当前各模块版本与配置](docs/README.md#7-当前实现版本台账)
- [问答质量与混合检索开发方案（S1—S3代码完成，后续分阶段实施）](docs/RAG_QUALITY_EVOLUTION_PLAN.md)
- [当前项目交接说明](docs/PROJECT_HANDOFF.md)
- [统一知识模块架构决策](docs/decisions/ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md)
- [进程内RAG问答边界](docs/decisions/ADR-0004-IN-PROCESS-RAG-QUERY.md)
- [文档处理模块规划](docs/DOCUMENT_PROCESSING_MODULE_PLAN.md)
- [本机运行说明](docs/deployment/LOCAL_DEVELOPMENT.md)
- [Platform API](docs/api/PLATFORM_API_V1.md)
- [第二期实施与首次发布状态](docs/PHASE2_IMPLEMENTATION_STATUS_2026-08-30.md)
