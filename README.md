# 制度知识智能服务平台

本仓库负责制度平台前端、Platform API、平台业务数据和管理流水线。制度问答通过 `rag_api_v1_1` HTTP 契约调用独立的 `D:\2-code\rag`，Platform 不访问 RAG 内部 SQLite、Qdrant 或模型服务。

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

数据所有权保持分开：会话、回答、Citation 快照、反馈、用户和配置写入 `platform.db`；管理流水线的文档及运行版本写入 Platform 自有知识库。问答事实源由独立 RAG 服务管理。

## 固定工具链

- Node.js：`22.23.2`
- pnpm：`11.22.0`
- Python：`D:\3-anaconda\envs\py312\python.exe`
- Chrome 89：仅保留兼容基线设计，当前机器使用现代浏览器验证

依赖由用户手动安装。前端使用根目录的 `pnpm install`；后端依赖清单位于 `backend/requirements-dev.txt`。

## 初始化与启动

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

Worker 默认把任务领取、阶段完成/失败、知识处理进度、IndexRun 构建和 Alias 切换事件写入
`logs/worker.log`，并按 10 MB、5 个历史文件滚动。路径和滚动参数可通过 `.env.example`
中的 `PLATFORM_WORKER_LOG_*` 变量调整。

访问地址：

- 前端：`http://127.0.0.1:5173/`
- Platform API：`http://127.0.0.1:8020`
- OpenAPI：`http://127.0.0.1:8020/api/docs`
- 就绪检查：`http://127.0.0.1:8020/api/v1/health/ready`

问答前需在 `D:\2-code\rag` 启动 8010：

```powershell
Set-Location 'D:\2-code\rag'
& 'D:\3-anaconda\envs\py312\python.exe' run_rag_api.py
```

Platform 仅调用 `POST /v1/rag/query`。普通问答默认发送 `query_scope=CURRENT`，历史查询显式发送 `HISTORICAL`。

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

- [当前项目交接说明](docs/PROJECT_HANDOFF.md)
- [统一知识模块架构决策](docs/decisions/ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md)
- [RAG HTTP 问答边界](docs/decisions/ADR-0003-RAG-HTTP-QUERY-BOUNDARY.md)
- [文档处理模块规划](docs/DOCUMENT_PROCESSING_MODULE_PLAN.md)
- [本机运行说明](docs/deployment/LOCAL_DEVELOPMENT.md)
- [Platform API](docs/api/PLATFORM_API_V1.md)
- [第二期实施与首次发布状态](docs/PHASE2_IMPLEMENTATION_STATUS_2026-08-30.md)
