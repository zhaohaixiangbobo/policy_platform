# 制度知识智能服务平台

本仓库负责制度平台前端、Platform API、平台业务数据和完整知识流水线。制度问答由 `backend/knowledge` 中的进程内 RAG Runtime 执行，新回答使用 `rag_api_v1_2`（兼容旧v1_1快照），不再启动或调用 `D:\2-code\rag` 的 8010 服务。

## 工程结构

```text
frontend/                   React + TypeScript 前端
backend/app/                Platform API、聊天、反馈和平台业务数据
backend/knowledge/          解析、审核、分块、索引、检索和 RAG
backend/migrations/         Platform 数据库基线
backend/tests/              后端最小测试
scripts/                    启动、OpenAPI 和数据迁移工具
docs/                       架构、接口、运行和后续开发文档
var/platform.db             平台业务数据库
var/knowledge/              知识数据库及当前有效 DOCX/PDF
```

数据所有权保持分开：会话、回答、Citation 快照、反馈、用户和配置写入 `platform.db`；文档、ParseRun、ChunkRun、IndexRun 及元数据版本写入 `var/knowledge/policy_parser.db`。进程内 RAG 只读 active IndexRun 和 Qdrant active alias。

## 固定工具链

- Node.js：`22.23.2`
- pnpm：`11.22.0`
- Python：`D:\3-anaconda\envs\py312\python.exe`
- Chrome 89：仅保留兼容基线设计，当前机器使用现代浏览器验证

依赖由用户手动安装。前端使用根目录的 `pnpm install`；后端依赖清单位于 `backend/requirements-dev.txt`。

## 初始化与启动

2026-09-24已补充跨平台 `scripts/run-service.py api|worker|migrate` 入口；
Docker-ready改动、旧索引清理记录及未来MySQL顺序见[部署准备说明](docs/deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md)。
当前仍使用双SQLite，尚未正式构建Docker镜像。

首次创建或重建 Platform 数据库：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic upgrade head
```

空库首次使用时，交互式创建首个管理员（密码不会出现在命令行或日志中）：

```powershell
Set-Location 'D:\2-code\policy-platform'
& 'D:\3-anaconda\envs\py312\python.exe' scripts\bootstrap-admin.py --username <工号> --display-name <姓名>
```

分别启动后端和前端：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
```

需要处理入库任务时另开一个终端启动唯一Worker：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-worker.ps1'
```

同时启用学习成效检测时，可用一个命令启动两个相互独立的Worker：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-workers.ps1'
```

该命令保留独立业务进程，按学习功能开关决定是否启动学习Worker。Windows入口保持真实PID；
单独/联合启动共用本机角色锁，重复启动会报错。Ctrl+C或任一Worker退出时，监督器通知其他Worker
停止领取新任务，等待当前阶段完成，每10秒显示等待进度，不自动强杀。请保留终端直到退出。
更新本版本后请先停止旧Worker，再运行此入口；旧进程尚未加载角色锁。

Worker 默认把任务领取、阶段完成/失败、知识处理进度、IndexRun 构建和 Alias 切换事件写入
`logs/worker.log`，并按 10 MB、5 个历史文件滚动。路径和滚动参数可通过 `.env.example`
中的 `PLATFORM_WORKER_LOG_*` 变量调整。

访问地址：

- 前端：`http://127.0.0.1:5173/`
- Platform API：`http://127.0.0.1:8020`
- OpenAPI：`http://127.0.0.1:8020/api/docs`
- 就绪检查：`http://127.0.0.1:8020/api/v1/health/ready`

问答不需要 8010。Platform 后端在首次问答时惰性初始化进程内 RAG Runtime，直接使用 `.env` 中的 Qdrant、Embedding、Reranker 和 Generator 配置。普通问答默认 `query_scope=CURRENT`，历史查询显式使用 `HISTORICAL`。

回答质量门禁默认关闭。如需启用确定性回答覆盖与额外语义支撑校验，在 `.env` 中设置：

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
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests -q -p no:cacheprovider -p no:tmpdir
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic current
```

本轮不自动执行模型联调、Qdrant 重建、负载测试、全量评测或 Chrome 89 实机测试。

## 事实源

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
