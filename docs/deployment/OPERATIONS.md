# 本机部署与操作手册

> 文件说明：记录统一项目的数据初始化、备份、恢复和常见故障处理。

## 1. 数据边界

S3最新迁移为0010_conversation_context，本机已应用。其他环境按 `alembic upgrade head` 升级后重启后端。新增列记录检索问题、补全策略和用户确认来源，历史保持NULL。诊断先检查范围/权限/IndexRun是否变化及短回复是否明确。失败轮次不保存确认；纠正已确认条件使用“改为二类”等新回复，不直接修改历史JSON。

### 问答耗时定位（query_timing_v1）

代码加载后，API的logs/api.log新增query_stage_started、query_stage、query_timing_summary，按request_id关联。汇总包含排队、初始化、检索子阶段、Context和生成调用；父级total包含子级，不能重复相加。HTTP事件次数用于确认重试，answer_validation_failed用于确认格式校验重生成。日志只保留耗时、计数、状态码和错误类型，不输出问题/Prompt/草稿。旧请求无分段数据，不能回填。
最小复测入口为backend/tests/manual_query_timing.py，顺序执行三个批准问题，产物写outputs独立目录；真实服务可用时才手动运行。详见[2026-09-19验证记录](../testing/QUERY_TIMING_VERIFICATION_2026-09-19.md)。

S2（2026-09-19）新增0009_chat_answerability迁移，只向chat_message增加四个可空字段，历史不回填。本机已应用；其他环境先执行 `alembic upgrade head` 再加载代码。若出现no such column: chat_message.answerability，检查迁移目标和head，按正常迁移修复。
回退应用需选择能兼容新旧回答契约的版本；正常回退保留新增列及数据。不要通过迁移downgrade删除新回答快照字段。模型输出校验失败会有限重试，仍失败公开返回ANSWER_VALIDATION_FAILED；语义校验失败返回SUPPORT_CHECK_FAILED，二者均无内部草稿正文。

- `var/platform.db`：会话、消息、Citation 快照、反馈、用户、配置和诊断记录。
- `var/knowledge/policy_parser.db`：Document、ParseRun、Node、ChunkRun、Chunk 和 IndexRun。
- `var/knowledge/source_documents`、`accepted`、`pdf`：当前知识数据需要的文件。

## 2. 初始化

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic upgrade head
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic current
```

当前 Platform 基线为 `0001_unified_platform_baseline`。制度数据不使用 Alembic；解析模块维护自己的知识数据库结构。

## 3. 启动与停止

```powershell
& 'D:\2-code\policy-platform\scripts\dev-backend.ps1'
& 'D:\2-code\policy-platform\scripts\dev-frontend.ps1'
```

问答 Runtime 由 Platform 后端在首次查询时惰性初始化，不需要独立 8010 进程。各开发进程按 `Ctrl+C` 停止。

## 4. 备份与恢复

停止后端及任何解析、分块或索引任务后，备份整个 `var` 目录即可同时保留数据库和 active 文件。恢复时原路径覆盖前应先另存当前 `var`；数据库和对应文件必须作为同一版本恢复。

Qdrant 数据不在本工程中。若 IndexRun 与 Qdrant alias 不一致，应重新运行对应索引或显式激活已验证的 IndexRun，不应手工修改数据库指针来伪造发布成功。

## 5. 文档处理

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m knowledge.cli --help
```

新运行默认只更新 latest。ParseRun、ChunkRun 和 IndexRun 都必须审核或验证后再激活；失败不会替换现有 active 版本。后续管理页面和 Worker 的设计见 [文档处理模块规划](../DOCUMENT_PROCESSING_MODULE_PLAN.md)。

## 6. 故障定位

- 制度列表为空：检查知识数据库是否存在 active Document 和 active ParseRun。
- PDF 404：检查 active ParseRun 的相对路径及 `var/knowledge/pdf` 文件。
- 问答失败：检查 `logs/api.log` 中的 `knowledge_query_failed` 事件，再核对 Qdrant、Embedding、Reranker 和 Generator 配置及可用性。
- Platform 数据库异常：执行 `alembic current` 并检查 `var/platform.db` 权限。
- 新文档失败：保留失败运行记录，修复输入或服务后创建新运行，不修改旧 active 指针。
