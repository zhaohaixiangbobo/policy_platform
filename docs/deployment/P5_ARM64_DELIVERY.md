# P5 ARM64 交付准备

**2026-10-13配置修订：** deploy/nginx.conf的upstream zone改为1m，满足UOS64KiB页宿主的8页最低要求。当前交付镜像保持原包，服务器通过已有只读配置挂载修复并重建Web容器；原始配置包校验记录保留，后续新打包使用修正文件。操作见UOS部署清单“当前Web修复命令”。

**最新状态（2026-10-12）：** 用户完成交付轮次20261012-224157-ab528108；本地再次核验四tar SHA256、linux/arm64、标签和metadata一致，backend四个迁移/初始化入口与工作区一致。当前转入[UOS部署清单](P5_UOS_DEPLOYMENT_CHECKLIST.md)，本轮仅指导核验、上传及服务器只读检查，尚未加载或部署。下方“未构建/manifest超时”为此前阶段记录。

> 文件说明：2026-10-12，状态 IN_PROGRESS。本轮仅配置准备与静态验证；未构建、下载、导出镜像或部署服务器。服务器事实以 UOS_P5_ENVIRONMENT_BASELINE.md 为准。下列构建/部署命令供后续用户手动执行，不表示已运行。

## 1. 镜像锁与兼容性边界

| 用途       | 固定内容                                                                                     | ARM64 状态                                                              |
| ---------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| backend    | Python 3.12（当前摘要本地记录为3.12.15）、LibreOffice 26.8.1.1、requirements.txt固定直接依赖 | Dockerfile有aarch64包及SHA256；基础manifest和原生Python依赖尚待构建验证 |
| web        | Node22.23.2/pnpm11.22.0构建；Nginx当前固定摘要本地记录为1.28.0                               | 两个基础manifest待确认                                                  |
| PostgreSQL | 17系列固定摘要，本地已核实17.11                                                              | ARM64 manifest与实机待验证                                              |
| Qdrant     | 沿用P4精确sha256，见deploy/p5-images.json；不猜测语义版本                                    | ARM64 manifest及二进制版本待核验，版本未核实前不宣称完成版本清单        |

所有基础镜像完整摘要登记在 `deploy/p5-images.json`。标签不是唯一锁定依据；预检必须在该摘要中找到linux/arm64，否则停止，人工选择相同版本的多架构摘要后再更新锁文件。不得默默升级软件或改为latest。所有源摘要当前仍是候选值，没有在线manifest验证通过记录。2026-10-12只读查询Python固定摘要时Docker Hub连接超时，未下载镜像层；其余摘要未继续联网重试。

API、ingestion-worker、learning-worker、migrate、initialize复用一个backend镜像。应用交付标签固定 `p5-20261012-arm64`，正式打包后记录镜像ID、实际软件版本和包SHA256；交付包冻结后改代码需新标签，不覆盖旧包。

## 2. 配置与文件交付清单

生产单独使用 `compose.p5.yaml`，不与根目录P4 compose.yaml叠加。组合：

```bash
export POLICY_FONT_DIR=/data/policy-platform/fonts
docker compose -f compose.p5.yaml -f deploy/compose.fonts.yaml -f deploy/compose.operations.yaml config --quiet
```

发布目录建议 `/opt/policy-platform`，保持以下相对结构：

- compose.p5.yaml
- deploy/compose.fonts.yaml、deploy/compose.operations.yaml、deploy/nginx.conf
- deploy/fonts/entrypoint.sh、deploy/fonts/99-policy-fonts.conf
- deploy/portal/portal-config.json、deploy/p5-images.json
- 本文、服务器基线、镜像tar及checksums.json（tar可放/data/policy-platform/releases）

API/Worker源码与迁移脚本已在backend镜像中；服务器无需安装Python、Node或现场构建。禁止打包整个本地var目录；只按白名单交付上述文件。授权字体单独受控传输，镜像构建上下文排除字体。配置凭据单独传输，不进入Git、镜像或公开验收日志。

### 存储与端口

- 项目名policy-platform-p5；postgres_data、qdrant_data、knowledge_files、material_files、app_logs是独立命名卷，默认名带项目前缀。底层由/data/docker管理，不改Docker/containerd路径。
- 挂载目的：PG `/var/lib/postgresql/data`，Qdrant `/qdrant/storage`，原文/PDF `/data/knowledge`，资料 `/data/materials`，日志 `/logs`。
- 配置文件在 `/data/policy-platform/config`；字体 `/data/policy-platform/fonts` 只读；fontconfig继续使用已验收映射。
- 唯一宿主端口 `10.9.14.171:80:8080`，Nginx容器仍监听8080，复用同源 `/api` 代理；PG/Qdrant/API不发布宿主端口。
- HTTP阶段Cookie Secure=false，权限/CSRF保持原实现；此阶段不能表述为HTTPS安全上线通过。
- 运行覆盖复用P4资源限制和采样。on-failure:3不是主机重启后的自动业务拉起承诺，重启恢复仍须P5实测和明确操作流程。

## 3. 专用构建器与手动执行（本轮只做静态检查）

固定构建器名 `policy-p5-arm64`，BuildKit `moby/buildkit:v0.21.0`，与已核实本机BuildKit版本一致；这是本地构建工具，不是生产运行镜像。上游来源 https://github.com/moby/buildkit/releases/tag/v0.21.0 及Docker Hub moby/buildkit。下载后记录完整RepoDigest并用该摘要创建builder，不使用latest。不宣称该旧版本为最新安全版本。

用户按顺序手动执行；每步失败即停。以下创建与下载命令本轮未执行。

### A. 下载并创建专用构建器

```powershell
cd D:\2-code\policy-platform
docker pull moby/buildkit:v0.21.0
if ($LASTEXITCODE -ne 0) { throw 'BuildKit下载失败' }
$buildkitInfo = docker image inspect moby/buildkit:v0.21.0 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'BuildKit检查失败' }
$buildkitRef = $buildkitInfo[0].RepoDigests | Where-Object { $_ -like 'moby/buildkit@sha256:*' } | Select-Object -First 1
if (-not $buildkitRef) { throw '未取得BuildKit完整摘要' }
$buildkitRef
docker buildx create --name policy-p5-arm64 --driver docker-container --driver-opt "image=$buildkitRef" --driver-opt default-load=false --driver-opt memory=6g --buildkitd-config deploy/buildkit-p5.toml
if ($LASTEXITCODE -ne 0) { throw '构建器创建失败；同名存在时先核对，不自动删除' }
docker buildx --builder policy-p5-arm64 inspect policy-p5-arm64 --bootstrap
if ($LASTEXITCODE -ne 0) { throw '构建器启动失败' }
```

不加--use，默认构建器不变；构建器运行本机架构的BuildKit，通过现有模拟能力执行ARM64。不要在此拉取ARM64的BuildKit工具镜像。只有新BuildKit镜像、专用builder元数据/容器/缓存卷产生；P4镜像及业务卷不变。资源上限6GiB，max-parallelism=2；gc=false保留缓存，需要关注Docker Desktop磁盘占用。

BuildKit内部按deploy/buildkit-p5.toml的`mirrors`顺序请求docker.io镜像站（当前：华为云SWR加速器 → docker.m.daocloud.io → 最后回落docker.io）。BuildKit v0.21.0内置containerd v2.0.2解析器：前一个镜像站连接失败或返回4xx/5xx（如502）时自动尝试下一个；全部失败时只报告优先级最高的那条错误，所以日志可能只出现某一个镜像站的502。镜像站只是下载通道，基础镜像仍按p5-images.json完整SHA256寻址并按内容校验，始终使用https。该配置不改变Docker Desktop。pip/npm/apt/LibreOffice各自下载网络不由该镜像配置解决。

**修改TOML不会自动生效。** buildx在`create --buildkitd-config`时把TOML解析后嵌入构建器元数据（`buildx ls --format json`的Nodes[].Files），之后读取的始终是嵌入副本。构建脚本每次运行会解码嵌入配置写入`buildkitd-effective.toml`并与TOML比对，不一致即停止。修改镜像站后按以下步骤重建（保留缓存卷`buildx_buildkit_policy-p5-arm640_state`）：

```powershell
cd D:\2-code\policy-platform
# 1. 先核验候选镜像站能否提供五个锁定摘要及ARM64子清单（只查元数据，HEAD层，不下载层内容）
& 'D:\3-anaconda\envs\py312\python.exe' scripts\p5-mirror-check.py --mirror 2a6bf1988cb6428c877f723ec7530dbc.mirror.swr.myhuaweicloud.com --mirror docker.m.daocloud.io --evidence var\p5-delivery\20261012-202655-0843c292\manifest-evidence.json
# 2. 只删构建器元数据和容器，保留状态卷（缓存）
docker buildx rm --keep-state policy-p5-arm64
# 3. 用同名、同一BuildKit摘要重新创建；节点名仍为policy-p5-arm640，复用原状态卷
docker buildx create --name policy-p5-arm64 --driver docker-container --driver-opt "image=moby/buildkit@sha256:fc06fa7d79ada15bbcbf8fce2b8f937dc6b7841ce76ba0bf2f071ec29e8f5ff6" --driver-opt default-load=false --driver-opt memory=6g --buildkitd-config deploy/buildkit-p5.toml
docker buildx --builder policy-p5-arm64 inspect policy-p5-arm64 --bootstrap
# 4. 核对状态卷仍在、默认构建器未变
docker volume ls --filter name=buildx_buildkit_policy-p5-arm640_state
docker buildx ls
```

华为云加速器地址与账号绑定，更换账号时替换为自己的地址并重新核验；docker.1ms.run同日核验通过但较慢，可作为第三备选追加到列表末尾。

### B. 镜像站预检

```powershell
& .\scripts\build-p5-arm64.ps1 -ManifestRegistry docker.m.daocloud.io
```

只查元数据。脚本保持原始完整sha256，将查询地址变为镜像站的library/python、library/node等对应路径；不传参数保持Docker Hub查询。每轮自动新建var/p5-delivery/时间戳-随机值，保存source-lock.json、builder.json、BuildKit配置、各manifest、完整ARM64子摘要、查询来源与UTC时间。用户之前报告5镜像均有ARM64；旧直连超时不代表架构不支持。本轮不联网复测这些结果。

### C. 两个独立的小验证

```powershell
# scratch+小文件，无基础镜像下载；生成并读取Docker tar验证格式及架构，不docker load。
& .\scripts\build-p5-arm64.ps1 -Probe Export
# 拉取固定Python基础镜像到专用BuildKit缓存，实际执行ARM64 Python；不安装新包。
& .\scripts\build-p5-arm64.ps1 -Probe Arm64 -ManifestRegistry docker.m.daocloud.io
```

Export产生export-probe.tar和日志；需要Windows已有tar命令。Arm64产生arm64-result/probe.txt，要求aarch64 64及PASS记录。后者用--no-cache只强制探针RUN执行，不清理已有缓存；这证明模拟执行可用，不证明UOS的64KB页兼容。若失败，不自动安装binfmt/QEMU，先询问用户。首次基础镜像下载耗时取决于网络，若预计超过10分钟先安排执行窗口。

### D. 四镜像构建导出

两项验证通过后用户择时执行，预计20—60分钟或更久，主要取决于网络、约200MB LibreOffice下载和CPU模拟；plain日志实时输出。

```powershell
& .\scripts\build-p5-arm64.ps1 -BuildAndExport -ManifestRegistry docker.m.daocloud.io
```

所有Buildx命令显式指定专用builder。backend/web构建，PG/Qdrant通过deploy/Dockerfile.image-export仅FROM固定源导出；不执行本地pull/tag/save/load，不改变P4的镜像引用。四个tar使用交付标签，记录metadata、构建日志和checksums.json，完成时才写completed.json。失败留下部分产物，重新执行新目录并复用同一builder缓存，不必手动移走旧目录。没有completed.json的目录不能当完整交付包。

#### 复用已导出的backend.tar

后端构建成功但web等后续步骤失败时，可用 `-ReuseBackendFrom <轮次>` 复用该轮backend.tar，不重建、不重新导出后端：

```powershell
# 先只读校验（不写交付目录）
& 'D:\3-anaconda\envs\py312\python.exe' scripts\p5-verify-backend-tar.py --source 20261012-213647-69609d73 --verify-only --output var\p5-mirror-check\backend-reuse-verify.json
& .\scripts\build-p5-arm64.ps1 -BuildAndExport -ReuseVerifiedManifest 20261012-202655-0843c292 -ReuseBackendFrom 20261012-213647-69609d73
```

失败轮次本身不是交付包。scripts/p5-verify-backend-tar.py逐项校验后才复制：来源轮次日志含`exporting manifest … done`与`sending tarball`且无ERROR、构建器为v0.21.0；source-lock、Dockerfile、apt-sources.sh、LibreOffice版本与SHA256与当前一致；metadata构建参数与build-sources.json一致；tar内每层摘要、config与manifest摘要、架构arm64/linux；镜像history的步骤与ARG值与当前Dockerfile一致；镜像内/app/backend、/app/scripts与工作区（按.dockerignore）逐文件比对，debian源已恢复官方。只允许P5宿主机构建工具（build-p5-arm64.ps1、scripts/p5-*、test_compose_p5.py）不同，且逐个记录在backend-reuse.json；新增P5测试须写入test_compose_p5.py。复制先写.partial，SHA256一致后才改名；任何一项不符即停止，不构建其余镜像。复用时不能同时指定下载源参数，实际下载源取自来源轮次。completed.json记录`backend_mode=reused`与`backend_source`。若需要镜像内工具与工作区完全一致，改用相同下载源参数重新构建后端（依赖层命中缓存，只重做COPY层，但需重新导出约570MB）。

镜像归档格式转换可能改变输出manifest摘要，来源摘要、子摘要、输出metadata及tar校验分别记录，不把它们当作同一个值。Qdrant语义版本仍需后续镜像二进制核验。构建结束不等于UOS验收通过。

### E. 后续可删除资源

- 导出探针tar、小验证文本和失败轮次文件：确认无需排错后可按精确目录删除；保留最终交付包、checksum、manifest、日志。
- 专用BuildKit容器可先用 `docker buildx --builder policy-p5-arm64 stop policy-p5-arm64` 停止，保留缓存便于重跑。
- 不再构建时才单独批准删除专用builder；需要保留缓存用 `docker buildx --builder policy-p5-arm64 rm --keep-state policy-p5-arm64`。要删除缓存时核对它所属的精确卷，另行处理。
- BuildKit镜像仅在没有其他builder引用时可以删除。以上操作不自动执行。
- 不执行全局system prune、volume prune；不删除P4容器、数据库卷或当前运行镜像。

## 4. 新配置、迁移与初始化设计

生成器支持 `--stage p5`，默认P4行为不变。后续执行（不是本轮执行）：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts/prepare-compose.py --stage p5 --source-env '<经核对的模型配置文件>' --execute
```

仅继承模型接入参数及已有学习开关；生成全新双库账号、随机密码、数据库身份标记和索引命名空间。无旧账号/索引/数据库/上传文件复制，不生成host.docker.internal旧Qdrant配置。输出 `var/compose-p5` 的runtime.env、migration.env、postgres-password、init.sql单独受控交付到服务器config目录。升级复用原配置，生成器拒绝覆盖。

服务UID/GID10001须能读取runtime.env/migration.env，建议文件root:10001且0640；宿主config目录root管理0700。PG首次init.sql及password文件须对容器内postgres身份可读（可用0644文件配合宿主0700父目录和单文件只读bind），不可机械将所有文件600导致容器不可读。实际权限在启动前检查，禁止777。正式字体文件同样需可读。

首次启动顺序是：PG/Qdrant → 双库分别预览迁移身份/当前revision/待执行链 → 用各自sha256执行迁移 → Platform基础角色与LOCAL认证配置初始化 → Knowledge目录及profile初始化 → Platform管理员创建 → API/Worker/web。Knowledge初始化调用check_readiness(check_files=False)，需要Platform的LOCAL认证配置已经存在。复用现有scripts/migrate-platform-pg.py、migrate-knowledge-pg.py和initialize入口，API/Worker不自动DDL。migrate服务默认只预览Platform；Knowledge通过覆盖命令执行，不能只跑一次就当双库完成。

示例（后续部署授权后）：

```bash
# 省略别名，所有操作统一用这三个-f；先预览，不带--execute-plan。
docker compose -f compose.p5.yaml -f deploy/compose.fonts.yaml -f deploy/compose.operations.yaml --profile tools run --rm migrate
docker compose -f compose.p5.yaml -f deploy/compose.fonts.yaml -f deploy/compose.operations.yaml --profile tools run --rm migrate python scripts/migrate-knowledge-pg.py --env-file /run/config/migration.env
```

执行迁移的完整命令必须在看到服务器预览指纹后再填写。Knowledge当前head k0004_render_metadata，Platform0013_worker_leases，以交付代码head再核对。禁止直接stamp、自动downgrade或清卷。

## 5. 服务器部署前检查与验收边界

本轮不连接服务器，80端口占用尚未实时检查；用户在部署前运行 `ss -ltnp 'sport = :80'`，有监听则先确认归属，不能停止未知服务。

服务器保留Compose v5.0.0-rc.2。当前配置使用常规Compose能力，无新增调度；本地config验证不等于服务器此版本已通过，目标机需先运行第2节config --quiet，并检查资源/挂载合并结果再允许启动。Docker二进制非RPM管理，来源待追溯，不阻塞准备但须保留上线核查项。

尚需：ARM64/64KB页实机运行、模型容器网络、字体及DOCX页码/Citation验收、重启恢复、空库业务闭环、完整备份恢复演练。视觉核对单次再确认样本。HTTPS/异机备份本轮不建设、不阻塞交付准备，正式上线前重新评估，不将HTTP验收等同正式生产放行。

## 6. 本轮验证记录

2026-10-12构建隔离修订：Windows PowerShell 5.1脚本语法检查通过，UTF-8 BOM及UTF-8 JSON读取检查通过；BuildKit TOML解析通过；test_compose_p5.py的2项纯静态配置测试通过。没有运行脚本入口、manifest查询、两个BuildKit探针、镜像下载、builder创建或正式构建。下面9项是前一轮配置准备测试，不冒充本次动态构建验证。

本地Compose v2.35.1-desktop.1对三个配置的config --quiet及包含tools profile的合并结果检查通过；API、两Worker、迁移和初始化五类服务共享镜像、ARM64平台，字体挂载及API显式启动命令保留，无build配置。PowerShell构建脚本语法检查通过。backend/tests/test_compose_p5.py与test_compose_p4.py共9项通过；首次运行因Windows沙箱临时目录权限失败，在获准的沙箱外重跑通过，不涉及数据库连接。服务器Compose v5.0.0-rc.2尚未验证，不能用本地版本代替。

manifest在线只读检查因网络超时未完成。未执行镜像构建/下载/导出、服务器端口探测、数据库操作、完整测试或压力测试。P5目前为“环境基线完成，交付配置已准备，镜像与目标机验收待执行”。
