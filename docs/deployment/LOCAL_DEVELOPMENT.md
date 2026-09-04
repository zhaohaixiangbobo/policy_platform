# Windows 本机开发运行说明

> 文件说明：说明统一知识模块迁移后的本机启动、配置和最小验证方法。

## 服务地址

| 服务 | 地址 | 说明 |
|---|---|---|
| React 开发服务器 | `http://127.0.0.1:5173` | 浏览器入口 |
| React 生产预览 | `http://127.0.0.1:4173` | 构建产物冒烟 |
| RAG API | `http://127.0.0.1:8010` | 独立问答引擎公开契约 |
| Platform API | `http://127.0.0.1:8020` | Platform 业务与管理 API |

问答联调必须启动独立 8010。Platform 只配置 `PLATFORM_RAG_API_URL`，不配置或调用 RAG 内部的 Qdrant、Embedding、Reranker 和 Generator。

质量门禁由 `POLICY_QUALITY_GATE_ENABLED` 控制，默认 `false`。设为 `true` 并重启后端后，才会执行回答覆盖和额外语义支撑校验。

DOCX PDF渲染默认 `POLICY_DOCX_RENDER_ENGINE=auto_headless`，优先发现并调用LibreOffice Headless；未安装时Windows回退到隐藏Word。服务器固定无界面渲染时设置：

```dotenv
POLICY_DOCX_RENDER_ENGINE=libreoffice
POLICY_LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
```

## 启动

```powershell
Set-Location 'D:\2-code\rag'
& 'D:\3-anaconda\envs\py312\python.exe' run_rag_api.py
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

```powershell
Invoke-RestMethod 'http://127.0.0.1:8020/api/v1/health/ready'

Set-Location 'D:\2-code\policy-platform'
pnpm typecheck

Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests -q -p no:cacheprovider -p no:tmpdir
```

Chrome 89 由用户在其他机器按 [冒烟清单](../testing/CHROME_89_SMOKE.md)验证；当前开发机使用现代浏览器即可。
