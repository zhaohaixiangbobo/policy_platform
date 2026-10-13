# P5 UOS 部署操作清单

**2026-10-13 Web修复：** API及两Worker已启动，Web因`zone platform_api 64k`在64KiB页宿主上低于Nginx的8页下限而反复退出。本地deploy/nginx.conf已改为1m。服务器用户已将宿主配置改成1m，但此前restart缺少POLICY_FONT_DIR且sed -i替换单文件inode，需显式设置字体变量、nginx -t预检后仅force-recreate web。尚待服务器修复结果；原交付tar及CONFIG_SHA256SUMS保留为原始版本证据，不覆盖旧校验清单。

**最新进度（2026-10-13）：** 依据用户服务器执行回执，配置上传/权限与Compose解析通过，PG17.11双库身份正确，Qdrant1.19.0接口正常且集合为空；双库迁移到0013_worker_leases/k0004_render_metadata。已按Platform基础角色→Knowledge目录/profile顺序初始化，profile为policy_platform_p5_92e8d13d；管理员admin（显示名称管理员）创建成功，首次登录要求改密。当前准备启动API、两Worker及Web；业务闭环、ARM64字体转换、重启和恢复验收尚未完成。凭据不记录在文档中。

> 文件说明：初版2026-10-12，进度更新2026-10-13。正式交付轮次20261012-224157-ab528108；服务器10.9.14.171。本清单延续现有P5方案，不新建架构。第1—3步保留为最初操作记录；后续步骤按已确认的服务器回执逐步推进。

## 与此前方案的关系

- 使用现有compose.p5.yaml + deploy/compose.fonts.yaml + deploy/compose.operations.yaml；不使用P4主compose，不切换Docker存储，不修改/data挂载，不升级Compose。
- HTTP 80内网验收、独立PG双database、两Worker、外部模型、只读授权字体均保持原决定。HTTPS和异机备份不是本轮上传准备前置条件，正式上线前评估；独立恢复演练仍未完成。
- 迁移与初始化脚本已在backend镜像内，实际比对四个入口与工作区字节一致；不额外上传并覆盖镜像内脚本。
- 上传需要创建新的交付目录、写入文件，这是用户手动执行的文件操作；其余检查只读。不将“上传准备”误写成服务器完全无变化。
- 随机数据库密码由已有生成器后续显式生成并由用户确认；本轮不运行生成器，不猜模型地址、不创建管理员。原报告中的“构建完成”不等于目标机64KB页与业务验收通过。

## 1. Windows：交付包核验（已执行，可只读重验）

交付目录：D:\2-code\policy-platform\var\p5-delivery\20261012-224157-ab528108。

| 文件 | 字节数 | 实际归档平台 | 交付标签 |
|---|---:|---|---|
| backend.tar | 571027968 | linux/arm64 | policy-platform/backend:p5-20261012-arm64 |
| web.tar | 74517504 | linux/arm64 | policy-platform/web:p5-20261012-arm64 |
| postgres.tar | 160000000 | linux/arm64 | policy-platform/postgres:17.11-p5-arm64 |
| qdrant.tar | 69912064 | linux/arm64 | policy-platform/qdrant:p5-20261012-arm64 |

四个SHA256均与checksums.json匹配；各tar内config摘要与*-metadata.json一致，completed.json正式build=true。复用backend/manifest证据目录及JSON存在。总计875457536字节，约835MiB。Python配置版本3.12.15、Nginx1.28.0、PG17.11；Qdrant实际二进制版本仍待加载后的无业务探测，不凭标签猜测。

```powershell
cd D:\2-code\policy-platform
& 'D:\3-anaconda\envs\py312\python.exe' scripts/p5-verify-delivery.py --source var/p5-delivery/20261012-224157-ab528108
if ($LASTEXITCODE -ne 0) { throw '核验失败，停止上传' }
Get-FileHash var/p5-upload/20261012-224157-ab528108/SHA256SUMS -Algorithm SHA256
```

作用：只读取本地tar与元数据；预期四项PASS，不调用Docker、不加载镜像。失败保留现场，禁止改checksums来掩盖不一致。

本轮已额外生成var/p5-upload/20261012-224157-ab528108，未修改原交付目录：

- deployment-config.tar：八项白名单部署配置及内部CONFIG_SHA256SUMS，统一UTF-8/LF，避免Windows换行破坏Linux entrypoint。
- delivery-verification.json：四镜像完整SHA256、实际标签/架构、预期镜像ID及核验时间。
- SHA256SUMS：服务器对上传的九个文件进行校验。此文件自身SHA256为 `3de9e4a8f565a9a55b95372cbed895e3daa35797ee0597562253fcedfeb09e14`。

配置包只含compose.p5.yaml、deploy/{compose.fonts.yaml,compose.operations.yaml,nginx.conf,p5-images.json,fonts/entrypoint.sh,fonts/99-policy-fonts.conf,portal/portal-config.json}。不包含runtime.env、migration.env、数据库、账号、模型密钥、字体或原文。不要将整个var目录上传。

原始构建日志、reused-backend/reused-manifest、缓存、失败轮次仅本地保留；完整证据不要删除。生成器scripts/prepare-compose.py后续在Windows使用；数据库迁移/初始化随backend镜像交付，无需服务器安装Python。

## 2. 用户手动上传（先创建全新接收目录）

### 2.1 UOS SSH终端：仅准备接收目录

以下沿用用户已经使用的root账号，不提供或保存密码。先确认SSH主机身份；如果改用其他账号，先明确账号及写入权限，不照抄root。

```bash
(
  set -euo pipefail
  mountpoint -q /data
  test "$(docker info --format '{{.DockerRootDir}}')" = /data/docker
  df -hT /data
  umask 077
  target=/data/policy-platform/releases/20261012-224157-ab528108
  if test -e "$target"; then
    echo "接收目录已存在，停止，先核对是否此前已上传" >&2
    exit 1
  fi
  mkdir -p /data/policy-platform/releases
  mkdir "$target"
  ls -ld "$target"
)
```

作用：验证数据盘后创建新目录，**会写服务器文件系统**，不启动服务、不覆盖旧目录。预期目录root所有、权限700。任何失败停止；目录已存在时不删除、不自动重试覆盖，返回结果先核对。上传约835MiB，若链路慢可能超过10分钟，SCP显示传输进度；预留至少数GB空闲，当前497GB仅为此前基线，按实时df判断。

### 2.2 Windows PowerShell：传输明确白名单

```powershell
cd D:\2-code\policy-platform
$delivery = 'D:\2-code\policy-platform\var\p5-delivery\20261012-224157-ab528108'
$auxiliary = 'D:\2-code\policy-platform\var\p5-upload\20261012-224157-ab528108'
$uploadFiles = @('backend.tar','web.tar','postgres.tar','qdrant.tar','completed.json','checksums.json','source-lock.json') | ForEach-Object { Join-Path $delivery $_ }
$uploadFiles += @('deployment-config.tar','delivery-verification.json','SHA256SUMS') | ForEach-Object { Join-Path $auxiliary $_ }
foreach ($file in $uploadFiles) { if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "缺少文件：$file" } }
scp @uploadFiles root@10.9.14.171:/data/policy-platform/releases/20261012-224157-ab528108/
if ($LASTEXITCODE -ne 0) { throw '传输失败，停止。保留远端部分文件，先核对再决定补传，不盲目重跑覆盖。' }
```

作用：上传十个明确文件；预期SCP正常退出、每个文件100%。会写新接收目录；不会docker load或解包。没有scp时使用已有SSH客户端的SFTP，保持相同十个文件名，关闭自动覆盖；无需为本任务自动安装软件。

## 3. UOS：上传校验与环境只读检查

### 3.1 校验上传文件（不解包、不加载）

```bash
(
  set -euo pipefail
  cd /data/policy-platform/releases/20261012-224157-ab528108
  printf '%s\n' '3de9e4a8f565a9a55b95372cbed895e3daa35797ee0597562253fcedfeb09e14  SHA256SUMS' | sha256sum -c -
  sha256sum -c SHA256SUMS
  tar -tf deployment-config.tar
)
```

预期校验清单自身OK，另外九项全部OK，tar只列出上述白名单和CONFIG_SHA256SUMS。失败立即停止，不改校验清单；仅对失败文件核对传输。此处不会创建容器或写业务目录。

### 3.2 核对环境和现有资源（只读）

```bash
(
  set -euo pipefail
  cat /etc/os-release
  uname -m
  getconf PAGESIZE
  free -h
  findmnt /data
  df -hT /data /
  docker version
  docker compose version
  docker info
  systemctl is-active docker
  systemctl cat docker
  docker ps -a
  docker image ls
  docker volume ls
  docker network ls
  ss -ltnp 'sport = :80'
  listeners=$(ss -H -ltn 'sport = :80')
  if test -n "$listeners"; then
    echo '80端口已占用，停止；不要关闭未知服务' >&2
    exit 1
  fi
  if test -e /opt/policy-platform; then ls -ld /opt/policy-platform; fi
  if test -e /data/policy-platform/config; then ls -ld /data/policy-platform/config; fi
  if test -e /data/policy-platform/fonts; then ls -ld /data/policy-platform/fonts; fi
)
```

预期：UOS20/1070e、aarch64、65536、Docker29.0.4、Compose5.0.0-rc.2、data-root=/data/docker及挂载保护保持原样；内存和磁盘有余量；80无监听。Docker资源不必机械为空：发现已有资源时先记录归属，尤其policy-platform-p5同名卷/标签必须核实，不自动删除或接管。目录已存在同样先报告，不覆盖。任何意外差异先反馈，不自行升级、改端口或修改存储。

**在这里停止。请回传校验OK输出、环境版本、磁盘/内存、80端口及资源列表。不要执行docker load、tar解包、compose up、配置生成或数据库命令。**

## 后续步骤路线（本轮不执行，确认前不提供一键串联命令）

### 当前Web修复命令（用户在UOS执行）

```bash
(
  set -euo pipefail
  cd /opt/policy-platform
  export POLICY_FONT_DIR=/data/policy-platform/fonts
  backup_dir=$(mktemp -d /opt/policy-platform/nginx-fix-20261013.XXXXXX)
  cp -p deploy/nginx.conf "$backup_dir/nginx.conf.before"
  sed -i 's/zone platform_api 64k;/zone platform_api 1m;/' deploy/nginx.conf
  grep -nE '^[[:space:]]*zone platform_api 1m;' deploy/nginx.conf
  sha256sum deploy/nginx.conf > "$backup_dir/nginx.conf.after.sha256"

  dc() {
    docker compose -f compose.p5.yaml -f deploy/compose.fonts.yaml -f deploy/compose.operations.yaml "$@"
  }
  dc config --quiet
  dc run --rm --no-deps --pull never -T --entrypoint nginx web -t
  dc up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 60 web
  dc ps -a
  dc exec -T web nginx -t
  curl --fail --show-error --max-time 15 http://10.9.14.171/healthz
  echo
  curl --fail --show-error --max-time 15 http://10.9.14.171/api/v1/health/ready
  echo
  dc logs --no-color --since 2m --tail 30 web
)
```

只替换Web容器，保留其他服务/卷。语法预检失败即停，保留备份。此配置通过只读宿主挂载生效，无需重新构建现有镜像；后续镜像构建自动COPY本地修正文件。localhost:80不是当前绑定入口，应检查10.9.14.171。read-only default.conf的entrypoint提示不是本次退出根因。本地Docker Desktop当时未运行，nginx -t无法执行；配置尺寸静态校验完成，实际64KiB页验收以服务器预检和恢复结果为准。

| 步骤 | 依据现有项目的操作 | 放行条件/风险 |
|---|---|---|
| 4 加载镜像 | 逐个docker load；核对四标签、linux/arm64、报告中image_id | 会增加镜像；同名标签存在先比较，不覆盖未知镜像；实际二进制与64KB页另测 |
| 5 环境配置 | 确认模型配置来源；现有prepare-compose.py --stage p5；单独字体上传；检查UID10001及PG可读权限 | 新密码只在用户批准生成后创建；管理员名/显示名由用户给出，密码终端输入；不带P4数据 |
| 6 配置预览 | 在/opt/policy-platform保持相对目录；三文件Compose、tools profile执行config --quiet | 不启动；检查80、五业务卷、只读字体、资源上限；不回退P4 compose |
| 7 PG/Qdrant | 按现有Compose单独启动；确认空卷init.sql与双库身份 | 会创建新卷/新库；已有卷不能当空库，失败保留现场，不清卷重试 |
| 8 双库迁移/初始化 | 两库各自预览并执行迁移；先initialize-platform-pg.py初始化基础角色/LOCAL认证，再initialize-knowledge-pg.py初始化目录/profile，最后创建管理员 | Knowledge就绪检查依赖LOCAL认证；不stamp、不复用另一库指纹；API/Worker不DDL；检查实际镜像head |
| 9 应用启动 | API、ingestion-worker、learning-worker、web复用既有Compose | 迁移就绪、字体、权限通过后再启动；先确认后续命令 |
| 10 业务验收 | health/ready、模型连通、上传/审核/发布/问答/Citation、UNO与授权字体 | 不宣称构建等同验收；视觉核对需另次确认样本与范围 |
| 11 运维验收 | 重启与持久化测试、一致备份及独立恢复演练 | 需另行维护窗口与目标确认；当前on-failure:3不保证主机重启后自动拉起；不自动downgrade或覆盖新数据 |

HTTPS/异机备份当前不建设；正式上线前评估合规与恢复目标。后续检查不能把普通容器重启等同完整灾难恢复。本阶段推进没有自动清理旧资源的授权。
