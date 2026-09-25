# Worker联合入口与历史迁移修复记录

> 文件说明：记录本轮根因修复、最小验证、数据边界和操作方式。

## 1. Worker监督：worker_supervision_v1

- `dev-workers.ps1` 前台调用 `run-service.py workers`，监督器启动独立入库/学习进程。
- Windows使用runpy在当前PID运行服务；Linux使用exec，容器仍保持PID和停止信号语义。
- 学习开关关闭时只启动入库Worker。关闭模块不会使入库Worker因学习进程正常退出而被终止。
- `worker_spawned` 记录实际PID；`worker_ready` 表示取得角色锁，并非外部服务健康检查。
- 单独和联合入口共用本机角色锁；同一锁目录的同角色重复启动直接失败。已有旧进程需先停止再重启。
- Ctrl+C或任一子进程退出后，通过本次会话独有的停止文件通知其余Worker，在阶段边界停止。
- 停止期间每10秒显示等待进度，不自动强杀。长模型请求/索引阶段需要等待；应保留终端。
- 操作系统锁在进程结束时自动释放，残留lock文件不代表角色仍被占用。不提供跨主机互斥保证。
- 未增加依赖，未创建新消息队列或任务系统。

## 2. 历史迁移冻结

根因：0001使用当前Base.metadata，0002/0003/0005使用当前ORM表对象，提前创建后续列。
0006再次添加snapshot_contract_version等字段导致空库重复列失败。

修复上述四个历史版本为固定op.create_table/索引/约束，后续列保留在所属迁移。
0003为批次、返工来源建立明确外键；各版本downgrade仅删除所属对象，0001不再drop_all。
env.py继续使用当前metadata用于结构比较，这是正确的职责边界。

迁移编号和依赖链不变，head仍是0011_learning_assessment。当前业务库只读核验为head，未执行升级、降级、stamp或数据修改。
错误旧迁移已经执行了一部分的库不能通过修改文件自动复原；无数据的失败测试库可另选新路径初始化，含数据的中间库必须先逐项核对结构并制定受控修复。
旧失败测试库var/tests/learning-migration本轮保留，不自动删除。

## 3. 已执行的必要验证

20项测试通过（16.47秒）：

- 启动命令和环境优先级；Windows同PID入口、Linux exec分支。
- 真实空Worker进程PID一致及停止文件退出，不连接任何业务服务。
- 本机角色锁互斥及释放；学习开关；模拟Ctrl+C、异常子进程退出和其余进程排空。
- 两种Worker在停止信号已存在时不领取任务；既有解析/Worker运行失败守卫回归。
- 隔离空库按0001→0005→0010→0011升级；head重复升级无变化。
- head结构与当前ORM比较无差异（表、列、类型、可空性、外键、索引、唯一约束；不比较Python端默认值与数据库server_default）。
- 隔离库完整downgrade保留无关测试表，再从空结构upgrade head成功。
- 历史迁移独立于应用ORM；PowerShell入口语法检查通过。

初次测试遇到系统临时目录权限限制，测试产物已统一改到var/tests；已有回归测试要求POLICY_TEST_RUNTIME_ROOT，补齐隔离目录后全部通过。
仅生成隔离测试产物，没有修改platform.db、知识库、Qdrant或真实任务。

复测命令：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$testRoot = Join-Path 'D:\2-code\policy-platform\var\tests' ('worker-migration-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$env:POLICY_TEST_RUNTIME_ROOT = $testRoot
$env:PYTHONIOENCODING = 'utf-8'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_portable_startup.py tests/test_worker_lifecycle.py tests/test_migration_replay.py tests/test_parser_and_worker_guards.py -o addopts='' -q -p no:cacheprovider -p no:tmpdir
```

## 4. 未执行及手工验收

未执行全量测试、模型调用、索引构建/发布、压力测试、MySQL实库或Docker部署。
实际控制台Ctrl+C及长业务阶段等待由用户选择空闲时手动验证：先停止旧Worker，再运行
`& 'D:\2-code\policy-platform\scripts\dev-workers.ps1'`，核对启用角色、PID及日志，按Ctrl+C观察退出。
修改学习开关后重新启动入口，关闭时应只看到入库Worker。当前head业务库无需再跑迁移。
