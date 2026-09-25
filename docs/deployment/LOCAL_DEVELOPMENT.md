# Windows 本机开发运行说明

> 文件说明：说明统一知识模块迁移后的本机启动、配置和最小验证方法。

## 服务地址

| 服务 | 地址 | 说明 |
|---|---|---|
| React 开发服务器 | `http://127.0.0.1:5173` | 浏览器入口 |
| React 生产预览 | `http://127.0.0.1:4173` | 构建产物冒烟 |
| Platform API | `http://127.0.0.1:8020` | Platform 业务与管理 API |

问答由 Platform 8020 进程内的 `KnowledgeService` 执行，不需要独立 8010。Platform 启动时不连接外部知识依赖，首次问答才按 `POLICY_QDRANT_URL`、`POLICY_EMBEDDING_URL`、`POLICY_RERANK_URL` 和 `POLICY_GENERATOR_URL` 惰性初始化。

质量门禁由 `POLICY_QUALITY_GATE_ENABLED` 控制，默认 `false`。设为 `true` 并重启后端后，才会执行回答覆盖和额外语义支撑校验。

DOCX PDF渲染默认 `POLICY_DOCX_RENDER_ENGINE=auto_headless`，优先发现并调用LibreOffice Headless；未安装时Windows回退到隐藏Word。服务器固定无界面渲染时设置：

```dotenv
POLICY_DOCX_RENDER_ENGINE=libreoffice
POLICY_LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
```

## 启动

### 学习成效检测（可选）

当前Platform head为 `0011_learning_assessment`，本机已应用。该模块默认关闭，先按
[功能文档](../LEARNING_ASSESSMENT.md#5-worker和开关)配置 `.env` 并重启API，再另开终端运行
`scripts/dev-learning-worker.ps1`。它与入库Worker分离；不启动时页面任务显示等待领取。
可使用 `scripts/dev-workers.ps1` 统一启动：学习开关开启时启动两个独立进程，关闭时仅启动入库Worker。
`worker_spawned` 表示创建进程；`worker_ready` 表示该角色获得运行锁，不代表数据库或外部服务已就绪。
Ctrl+C停止领取新任务，等待当前阶段完成；每10秒报告等待中的PID，不自动强杀正在处理的业务。
单独/联合入口共用 `var/worker-locks` 下的操作系统文件锁，可用 `PLATFORM_WORKER_LOCK_DIR` 改目录。
锁文件可保留，进程退出后操作系统释放锁；此锁只保证本机同目录角色互斥，不替代跨主机租约。
更新后先停止旧Worker再启动新入口。强制关闭终端不属于优雅退出，可能使任务等待既有恢复机制。
真实模型出题及浏览器仍需按[验收记录](../testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md)复测。

PS1已转调跨平台run-service入口；配置统一从项目根.env读取，外部环境变量优先。
容器准备与Linux依赖见[Docker-ready说明](DOCKER_READY_AND_INDEX_RETIREMENT.md)。

```powershell
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-worker.ps1'
```

首次运行前创建 Platform 数据库：

2026-09-24已冻结0001/0002/0003/0005历史结构，修复空库重复列；当前head仍为0011。
现有head数据库无需清空、降级或stamp。已失败的旧空库不能靠重跑自动修复；先确认是无数据的测试库，
再显式选择新的空库路径初始化。本次未删除旧失败测试库。详见[修复记录](../testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md)。

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic upgrade head
```

空库中创建首个本地管理员：

```powershell
Set-Location 'D:\2-code\policy-platform'
& 'D:\3-anaconda\envs\py312\python.exe' scripts\bootstrap-admin.py --username <工号> --display-name <姓名>
```

## 最小检查

### S2升级（2026-09-19）

加载新代码前执行迁移，再重启后端：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic upgrade head
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic current
```

S3对应head为0010_conversation_context，本机已应用；2026-09-24学习检测将当前head更新至0011_learning_assessment。无需新依赖、重新Embedding或发布索引。新回答应报告rag_api_v1_2，Prompt v4、Schema v3、Generator配置v3、Pipeline v2、Quality Gate v3；旧记录保持原版本和空的新字段。S3新增Platform补全策略clarification_rewrite_v1，重启后端加载；前端生产环境需要重新构建。
语义门禁沿用POLICY_QUALITY_GATE_ENABLED，默认false；S2不增加默认LLM调用。前端如为生产构建，需按原流程重新构建发布。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8020/api/v1/health/ready'

Set-Location 'D:\2-code\policy-platform'
pnpm typecheck

Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests -q -p no:cacheprovider -p no:tmpdir
```

Chrome 89 由用户在其他机器按 [冒烟清单](../testing/CHROME_89_SMOKE.md)验证；当前开发机使用现代浏览器即可。
