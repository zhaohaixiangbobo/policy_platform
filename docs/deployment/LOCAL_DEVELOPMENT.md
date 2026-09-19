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

```powershell
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-worker.ps1'
```

首次运行前创建 Platform 数据库：

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

最新head为0010_conversation_context，本机S3已应用。无需新依赖、重新Embedding或发布索引。新回答应报告rag_api_v1_2，Prompt v4、Schema v3、Generator配置v3、Pipeline v2、Quality Gate v3；旧记录保持原版本和空的新字段。S3新增Platform补全策略clarification_rewrite_v1，重启后端加载；前端生产环境需要重新构建。
语义门禁沿用POLICY_QUALITY_GATE_ENABLED，默认false；S2不增加默认LLM调用。前端如为生产构建，需按原流程重新构建发布。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8020/api/v1/health/ready'

Set-Location 'D:\2-code\policy-platform'
pnpm typecheck

Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests -q -p no:cacheprovider -p no:tmpdir
```

Chrome 89 由用户在其他机器按 [冒烟清单](../testing/CHROME_89_SMOKE.md)验证；当前开发机使用现代浏览器即可。
