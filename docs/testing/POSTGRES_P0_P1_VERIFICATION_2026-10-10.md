# P0/P1 PostgreSQL 本地实施与验证

文件说明：2026-10-10执行记录；仅代表P0/P1最小验收，不代表P2—P5或完整业务验收。

## 当前资源

| 项目 | 结果 |
|---|---|
| PostgreSQL | 17.11，linux/amd64；驱动psycopg[binary] 3.3.6由用户安装 |
| 镜像 | postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3 |
| 容器 / 卷 | policy-platform-pg17-dev / policy-platform-pg17-dev-data |
| 端口 | 127.0.0.1:55432；restart unless-stopped |
| Platform | 0001—0012完整重放，head=0012_supporting_materials，与ORM结构比对一致 |
| Knowledge | database已创建，业务表和Alembic基线待P2 |
| 账号 | 两库分别owner/app，app不能在public建表；未创建真实管理员 |
| 初始化 | 角色/provider初始化执行两次；无默认账号或密码重置 |
| 新Qdrant命名 | policy_platform_pg17_dev / policy_platform_pg17_dev_active / policy_platform_pg17_dev |

本轮没有修改旧.env、迁移旧业务数据、清理旧SQLite/文件或写入Qdrant。结束时旧collections仍为`policy_platform_dense_253687aa1917_4ffad605`和`policy_platform_dense_acd380ffb89f_4ffad605`；旧Alias指向后者。

## 入口盘点与边界

| 入口 | P0/P1处理 | 后续边界 |
|---|---|---|
| app/config、Session | 显式PLATFORM_ENV_FILE选择新配置；缺文件/缺PG URL拒绝；PG连接池和超时 | 默认旧.env仍保留旧运行方式，P2再统一正式入口 |
| run-service、Knowledge CLI | 统一选择配置文件；CLI隔离data_root | Knowledge目前仍使用SQLite，不能启动新环境完整业务链路 |
| 管理/索引/RAG/检索/阅读 | 从IndexConfig统一读取profile、alias、prefix | P2改数据访问，不改变检索算法 |
| publication | 发布请求写入配置alias；激活拒绝跨namespace | P3发布恢复和租约 |
| retire-index-storage | 选择配置文件、清理拒绝跨namespace；PG环境明确拒绝旧双SQLite维护脚本 | P3改维护锁，禁止拿新脚本清旧库 |
| Alembic / 管理员 | 独立PG预览执行和幂等初始化命令 | API启动DDL/seed及Knowledge后台脚本在P2完整消除 |

这不是SQLite兼容承诺，而是分阶段迁移期间保留旧环境。`KNOWLEDGE_DATABASE_URL`目前仅为P2预留，不能视为现有Knowledge业务已使用PG。

## 使用命令

工程根目录执行。当前容器已经创建，**不要重跑创建命令**。脚本`setup-postgres-dev.py`默认预览，`--execute`才创建；发现已有同名容器/卷/状态目录即拒绝，不覆盖。无需下载镜像或安装Windows版PostgreSQL。

```powershell
Set-Location 'D:\2-code\policy-platform'
# 只读预览：目标身份、数据库标记、当前revision、待迁移、迁移文件hash及计划指纹
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-platform-pg.py
# 阅读预览后填写当次sha256；已有head时为无新增迁移
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-platform-pg.py --execute-plan '<当次预览sha256>'
# 必要角色/provider初始化；可重复执行
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py
# 需要管理员时手动执行，密码交互输入；已有用户不会被覆盖
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py --username '<管理员名>' --display-name '<显示名>'
```

配置与随机凭据位于已被Git忽略的`var/postgres-dev/platform.env`及`credentials.json`；不要提交、粘贴或打入镜像，应限制本机访问权限。迁移使用owner，应用使用app，不把owner密码放进正式应用配置。生产身份校验在P4适配，当前迁移入口只允许指定P1数据库标记。

PG池每进程上限为5+2，pool_timeout=10s、recycle=1800s、connect_timeout=5s，SQL statement_timeout=60s、lock_timeout=5s、idle事务60s，UTC会话。连接数预算需按实际API/Worker进程数累加；长模型调用事务边界在P2/P3检查。

## 最小验证

19项通过：完整/不完整命名空间、跨namespace激活和删除拒绝、迁移身份保护、PG表结构比对、账号权限、管理员重复创建保留密码且测试写入回滚、Knowledge空库、索引复用/清理与Alias失败保留旧快照。

此外实际执行：空库12份迁移完整重放、head再次执行、seed重复执行、错误执行指纹拒绝，容器状态和旧Qdrant只读核验。迁移文件内容参与计划指纹，执行连接再次校验并持有PG advisory锁。

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:POLICY_TEST_RUNTIME_ROOT='D:\2-code\policy-platform\var\tests\pg-p1'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_pg_p1.py tests/test_index_storage_lifecycle.py tests/test_v2_governance.py::test_alias_failure_keeps_old_metadata_and_old_index_active -q -p no:cacheprovider -p no:tmpdir
```

未执行：全量测试、强制数据库断连/重启故障注入、真实Embedding重建、完整API/Worker上传发布闭环、压力测试、完整Compose、ARM64和DOCX视觉验收。完整闭环必须等P2/P3；上述耗时验收另行按阶段准备命令，不要求用户现在运行。
