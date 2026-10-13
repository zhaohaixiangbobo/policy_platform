# P4本地Compose操作说明

2026-10-12最终状态：api/web构建及三份Compose配置启用完成，P4本地最小验收通过；[最终记录](../testing/P4_CLOSEOUT_2026-10-12.md)优先于下文旧进度。以后启动继续叠加字体和operations配置，不要仅用主Compose重建。

当前待构建命令为 `docker compose --progress plain build api web`（P4池采样＋门户运行时入口）。
web新增只读挂载 `deploy/portal`，修改模块地址不再重建；详见[门户运行配置](../PLATFORM_PORTAL.md)。

2026-10-12：真实新文档业务检查由用户完成，存储/应用重建持久化及最小故障检查通过。连接池采样与运行资源覆盖已准备，待后端镜像重建；当前操作入口及剩余一步见[P4收口](../testing/P4_CLOSEOUT_2026-10-12.md)。

文件说明：2026-10-11。镜像构建、独立空库迁移及六服务启动已完成，待用户创建新管理员及容器业务/持久化验收。下面首次部署命令保留为复现步骤，当前环境不要重复生成配置。Windows原开发方式继续保留；生产ARM64在P5单独验收。

## 1. 已核验基础镜像与构建授权

本地已核验Linux amd64：Node 22.23.2、Python 3.12.15、Nginx 1.28.0；PostgreSQL和Qdrant沿用已下载镜像的摘要。所有FROM/Compose基础镜像已固定摘要，不用滚动标签执行升级。摘要不等于ARM64已验证，P5还需检查manifest并实际运行。

镜像构建会联网安装以下内容，用户手动执行构建即安装到镜像，不影响本机Python/Node环境：

- 后端Linux包：固定 LibreOffice 26.8.1.1 官方 deb（按架构校验 SHA-256）、`fonts-noto-cjk`、`fontconfig`及系统依赖；授权字体不入镜像。2026-10-12 起启用前需执行 `k0004_render_metadata` 迁移并加载字体覆盖配置，详见[字体部署说明](LIBREOFFICE_FONTS.md)。
- 后端Python包：`backend/requirements.txt`中现有版本；Windows专用依赖由平台条件跳过。
- 前端：`pnpm@11.22.0`，再按`pnpm-lock.yaml`冻结安装现有依赖；不升级业务依赖。

首次构建预计10—30分钟，主要取决于APT/PyPI/npm网络、字体下载及镜像缓存；慢网可能更久。BuildKit的plain输出显示各构建步骤。暂不自动执行这些安装。

```powershell
Set-Location 'D:\2-code\policy-platform'
docker compose --progress plain build api web
```

如果任何依赖没有Linux/架构兼容包，保留错误输出，不自行取消版本固定。本次不执行全量测试或压力测试。

## 2. 配置与首次空环境

以下为构建完成后的步骤。配置脚本只读取原配置中模型及学习开关白名单，不复制账户、业务库、索引或文件。不覆盖已有`var/compose-p4`；目录已存在时停止核查，不能删目录“重试”已有部署。

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts/prepare-compose.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/prepare-compose.py --execute
docker compose config --quiet
docker compose up -d postgres qdrant
```

生成的`runtime.env`仅含应用账号；`migration.env`仅供迁移，包含owner和部署身份；`init.sql`和`postgres-password`仅供空PostgreSQL卷首次建库。不输出密码，不提交这些文件；限制`var/compose-p4`宿主目录仅管理员可读。Linux文件目录权限及Windows ACL需部署时核对。应用进程以UID/GID 10001运行，命名卷首次挂载继承镜像中目录的属主；不要用777替代权限修复。

Compose项目名固定`policy-platform-p4`，卷前缀独立，不发布5432/6333端口。旧`policy-platform-pg17-dev`、旧`qdrant`及其卷不在本Compose管理范围。应用日志卷与知识文件/资料卷独立；卷不进入镜像。生产不使用本地测试卷。

## 3. 双库显式迁移

先查看两个计划，核对database、owner、marker、host、port、current/head/pending和sha256；这里host应为Compose内部`postgres`。数据库标识由首次配置生成，不能从目标库读取后自动接受。

```powershell
docker compose --profile tools run --rm migrate
docker compose --profile tools run --rm migrate python scripts/migrate-knowledge-pg.py --env-file /run/config/migration.env
```

确认后分别填入刚显示的sha256，不用示例替代真实指纹：

```powershell
docker compose --profile tools run --rm migrate python scripts/migrate-platform-pg.py --env-file /run/config/migration.env --execute-plan '<Platform指纹>'
docker compose --profile tools run --rm migrate python scripts/migrate-knowledge-pg.py --env-file /run/config/migration.env --execute-plan '<Knowledge指纹>'
```

任何命令非零退出均停止，不执行后续启动。迁移再次获取互斥锁并校验身份/指纹；版本表运行账号只读。API/Worker不执行DDL，也不自动初始化角色。

## 4. 业务初始化与启动

```powershell
# 角色/认证配置；重复执行保持已有账户
docker compose --profile tools run --rm initialize
# 知识目录/profile；须在双库迁移及角色初始化后执行
docker compose --profile tools run --rm initialize python scripts/initialize-knowledge-pg.py --env-file /run/config/runtime.env
# 新空环境管理员，密码交互输入，不写命令行
docker compose --profile tools run --rm initialize python scripts/initialize-platform-pg.py --env-file /run/config/runtime.env --username '<新账号>' --display-name '<显示名>'
docker compose up -d api ingestion-worker learning-worker web
docker compose ps
docker compose logs --tail 80 api ingestion-worker learning-worker
```

访问`http://127.0.0.1:8088`。已有管理员不会重置密码。若源配置关闭学习检测，learning-worker退出符合当前代码行为，需先核对是否启用再启动。

API/Worker首次验收使用`restart: no`，版本/目录错误直接退出，便于发现，不靠重启循环掩盖迁移失败；上线前确认通过后再审核运行重启策略。数据库、Qdrant、web使用unless-stopped。停止宽限期120秒不是完成模型调用的承诺，超时退出按P3恢复规则处理。API仅内网访问，Nginx不信任客户端传来的代理头；本地HTTP Cookie Secure=false，生产HTTPS和代理信任配置留P5核验。

当前`/api/v1/health/live`只证明API存活，`/api/v1/health/ready`检查Platform库；API启动另检查双库revision及目录。不能把ready=200视为模型或Qdrant就绪，必须在独立容器闭环分别验证。Worker锁文件位于共享日志卷`/logs/worker-locks`。所有配置文件挂载禁止自动创建源目录；缺失时先修复配置再启动。

## 5. 可选复用旧Qdrant服务

默认独立卷最适合空系统验收。仅本地需要复用服务时，从首次启动起统一使用：

```powershell
docker compose -f compose.yaml -f deploy/compose.external-qdrant.yaml config --quiet
# 此模式只启动postgres，不启动内部qdrant
docker compose -f compose.yaml -f deploy/compose.external-qdrant.yaml up -d postgres
```

后续迁移/初始化/启动也必须带相同两个`-f`。覆盖文件将Qdrant服务移入未启用profile，运行配置改用`runtime-external.env`和`host.docker.internal:6333`；仍使用新命名空间。不要追加`--profile internal-qdrant`。已经发布后不可直接在两种模式之间换URL，否则数据库指针与物理索引不匹配。

## 6. 升级与尚待验收

运行巡检（宿主执行，不需要重建镜像）：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts/inspect-compose.py
```

退出码0表示本轮指标无告警，1表示告警，2表示采集失败。默认磁盘剩余15%、PG连接占用80%为告警阈值，可用`--min-free-percent`和`--max-connection-percent`调整。这是手动巡检，不自动通知；PG连接数不是各进程连接池借出数。目录du可能随数据增长变慢，当前仅适合小库最小核查。

Web挂载`deploy/nginx.conf`只读配置；文件随部署清单交付。上游使用Docker DNS动态解析，API暂不可用时前端仍可服务，API请求可能返回502；不使用重启循环等待API。当前管理员已创建，首次登录按系统提示修改密码，不再次初始化已有账号。

升级保留原配置、卷及Compose项目名，不再执行prepare。先按P5方案备份并暂停写入/Worker；重新构建应用、预览和审核双库迁移，通过后执行初始化就绪检查并重建应用容器。禁止`down -v`、volume prune、重建数据库或自动重置索引。镜像回滚仅在数据库结构兼容时允许；不默认Alembic downgrade，不覆盖升级后新数据。

待构建后验证：空卷迁移、无界面转换、上传审核索引发布、共享目录权限、文件中断补偿、重建后数据保留、迁移失败阻断、基础巡检及容器重启。此文档不是这些测试的通过记录。P3已完成的原环境登录测试不重复，新容器闭环单独记录；全量/稳定性/容量测试未执行。
