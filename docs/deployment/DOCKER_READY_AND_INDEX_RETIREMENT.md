# PostgreSQL 迁移与 Docker 部署实施方案（含 Docker-ready 历史记录）

> 文件说明：方案版本postgres_compose_plan_v1.3，2026-10-11更新进度：P0—P3本地最小验收通过，非生产放行；P4镜像已核验，构建配置/迁移入口及5项最小测试完成，待用户手动构建和容器业务验收，P5待实施。见[P4进度](../testing/DOCKER_P4_PROGRESS_2026-10-11.md)。
> 第5节为当前P0—P5实施方案，取代此前MySQL建议；启动见[P2记录](../testing/POSTGRES_P2_VERIFICATION_2026-10-10.md)，当前验收及保留边界见[P3记录](../testing/POSTGRES_P3_VERIFICATION_2026-10-11.md)。API/Worker已可用PG启动，用户登录态上传发布及问答联合验收通过。第1—4节保留原Docker-ready实施历史，不作为当前SQLite运行指令。

## P2当前执行结果

2026-10-11 P3进展：0013_worker_leases/k0003_worker_operation已实施；原子领取、租约代次、知识写入保护和受控发布恢复已落地。此前24项最小测试及只读核验通过；用户补充5173代理登录态联合验收和浏览器6份制度上传发布结果，登录验收已完成，不再重复。P3本地最小验收通过，有条件进入P4；故障及权限等专项边界继续保留，详见[P3记录](../testing/POSTGRES_P3_VERIFICATION_2026-10-11.md)。以下P2版本为历史快照。

Platform head为0012_supporting_materials；Knowledge独立基线及索引补充迁移已到k0002_document_series_index。Core Repository与全部正式连接入口切换PostgreSQL，API/Worker启动只读检查；旧迁移/清理工具归档并阻断。12项最小PG测试、API健康检查和两类Worker空队列启动通过，真实外部服务与故障恢复仍待P3。

P1版本表REVOKE已固化于两套迁移入口，初始化和测试动态读取head。当前连接预算按每进程Platform 5+2、Knowledge 3+1计算，三个进程上限33，替代下文设计期26的估值；不包含运维连接，不是容量承诺。Knowledge保持既有JSON文本、0/1标志和UTC时间字符串契约。

下文代码核查表及末尾P0/P1记录是实施前/分阶段事实；其中Knowledge待改、运行时建表及无法启动等事项已由P2完成。使用scripts/dev-postgres.ps1选择新配置，旧.env及旧数据仅保留，当前代码不再支持SQLite运行。尚未创建新管理员或写入正式制度；原子领取、发布恢复与维护互斥仍在P3。
> 第1—4、6节保留2026-09-24实施记录，版本 docker_ready_v1 / index_storage_retirement_v1；其中运行状态、数量和测试结果均为当日快照，不代表已重新核验的当前环境。

## 1. 本轮实施边界

- 保留当前双SQLite运行方式、单Worker和进程内RAG，不使用原rag工程或8010。
- `scripts/run-service.py api|worker|migrate` 提供与工作目录无关的启动入口；使用调用它的解释器。
- 本机PS1入口仍固定 `D:\3-anaconda\envs\py312\python.exe`，API保留开发热重载。
- `.env`统一从工程根读取，容器/系统已注入的环境变量优先；知识模块的POLICY配置同步生效。
- Linux安装清单排除pywin32、docx2pdf；python-dotenv固定为当前已安装的1.2.1，无新增安装。
- Worker处理SIGTERM/SIGINT时等待当前阶段完成再退出。未来Compose的停止宽限期需覆盖阶段执行时间；不能据此宣称强杀时也能完成阶段。
- `.dockerignore`排除数据库、上传文件、日志、密钥和本机node_modules。

## 2. Linux部署准备

环境模板：`docs/deployment/container.env.example`。生产时通过环境注入，禁止把实际密钥复制进镜像。

未来镜像需Python 3.12、LibreOffice Writer/Headless、fontconfig及经授权的中文字体。
固定 `POLICY_DOCX_RENDER_ENGINE=libreoffice`，soffice路径按镜像实际安装位置设置。
LibreOffice与Word存在字体和分页差异，Linux真实转换须单独验收，本轮未执行。

建议挂载：

| 内容 | 容器路径 | 所有权 |
|---|---|---|
| 当前Platform SQLite | /data/platform | API、Worker，未来按第5节迁移PostgreSQL后替换 |
| 知识数据库及DOCX/PDF/temp | /data/knowledge | API、Worker，共享同一卷 |
| 日志 | /data/logs | 每进程独立日志文件 |
| Qdrant存储 | /qdrant/storage | 仅Qdrant |

镜像更新只替换程序，卷保持独立。数据库升级由独立迁移步骤执行，不让每个API副本同时执行迁移。
当前知识模块仍有运行时建表/补列，下一阶段接入知识库Alembic后移出运行时路径。
前端未来使用构建出的静态文件和同源 `/api` 反向代理，不以Vite开发服务器作为生产服务。
健康探针可调用 `/api/v1/health/ready`；它不代表所有模型依赖均已完成暖态验收。

本机入口示例：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' api
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' worker
# 仅在需要升级Platform库时显式执行
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' migrate
```

## 3. 旧索引复用和退役契约

历史构建成功不等于物理存储仍可用：

- 成功IndexRun复用和人工发布前，检查collection存在及exact count匹配。
- 增加知识控制表 `index_storage_retirement`，记录DELETING/DELETED、物理名称、时间和原因。
- 清理中或已清理的IndexRun拒绝再次复用/发布；不创建空collection并沿用旧verified记录。
- 当前实现采用明确拒绝策略，不提供自动恢复旧collection功能。需要原样恢复时另行实施受控恢复；新的来源快照按正常构建路径执行。
- 清理保护所有profile的active/latest、全部Qdrant Alias、显式保留ID；只接受已终结运行。
- 存在任何未结束的发布请求时停止清理，包含“已构建待确认发布”。
- 维护期间暂停Worker和发布写操作。清理工具持有Platform写锁、分阶段知识库写锁；禁止其他外部运维工具同时操作Qdrant Alias。该锁实现迁PostgreSQL时必须重写，见P3。
- 删除前持久化DELETING；网络错误或进程中断后重复相同清单可继续。删除后确认不存在再记录DELETED。
- 不删除IndexRun、来源清单、Chunk索引记录、聊天、Citation或原始文档。它们用于历史审计，不代表旧向量仍在线。
- CLI目前不清理未登记的孤儿collection，也不启用定时自动清理。

预览与执行命令（未来使用需重新审核ID）：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts/retire-index-storage.py --runs 1 2 3 4 5 6 7 --keep 8 9
# --execute永久删除明确清单中的向量存储
& 'D:\3-anaconda\envs\py312\python.exe' scripts/retire-index-storage.py --runs 1 2 3 4 5 6 7 --keep 8 9 --execute
```

## 4. 2026-09-24实际清理结果

| IndexRun | Collection | 结果 |
|---|---|---|
| 1 | policy_platform_dense_cfeaea5224cb_4ffad605 | 已删除 |
| 2 | policy_platform_dense_dda15a723244_4ffad605 | 已删除 |
| 3 | policy_platform_dense_b621e8ff037a_4ffad605 | 已删除 |
| 4 | policy_platform_dense_06885286f72d_4ffad605 | 已删除 |
| 5 | policy_platform_dense_1df584cadaeb_4ffad605 | 已删除 |
| 6 | policy_platform_dense_a3e3b5e18e05_4ffad605 | 已删除 |
| 7 | policy_platform_dense_36ad02cd1b88_4ffad605 | 已删除 |
| 8 | policy_platform_dense_253687aa1917_4ffad605 | 保留 |
| 9 | policy_platform_dense_acd380ffb89f_4ffad605 | 保留、当前Alias目标 |

执行前核验无Worker进程、无未完成发布请求。执行后 `/collections` 只返回8、9；
`policy_platform_dense_active` 仍指向9。未制作向量快照备份，不能直接撤销删除；
保留关系数据库与原文不等于拥有已删除向量的备份。未声称Docker虚拟磁盘已自动缩小。

## 5. 当前实施方案：PostgreSQL → 业务验证 → 完整Compose

### 5.1 已确认范围与代码核查

**原则：镜像携带程序、依赖和版本化迁移脚本；配置提供环境参数和存储映射；Alembic管理结构；数据独立持久化。首次部署空库、正式资料后导入，后续升级保留业务数据。**

- 仅支持PostgreSQL。Platform继续SQLAlchemy ORM；Knowledge优先SQLAlchemy Core + Repository，不强制全面ORM化，不改变业务接口和数据访问结果契约。
- PostgreSQL固定17系列，开发、测试、生产保持相同批准的小版本；实际镜像固定版本和digest、驱动固定版本后再执行。用户已拉取17.11；升级17系列补丁也须同步更新环境清单，不使用浮动postgres:17作为正式部署锁定值。
- Windows 10 + WSL2 Ubuntu 22.04；P1—P3仅PostgreSQL运行在容器中，复用既有Qdrant服务。本地Python固定 `D:\3-anaconda\envs\py312\python.exe`，Node 22.23.2、pnpm 11.22.0保持；不安装本机PostgreSQL Server。
- **代码与来稿冲突：** `frontend/package.json` 使用React 18 + Vite 6，不是UmiJS；保持实际技术栈，不进行前端框架迁移。
- 约1000名注册用户、初期数百份制度，单机Compose；API、两种Worker共用后端镜像但独立运行。模型服务仍远程调用，不改变接口、模型配置或业务超时。
- 不迁移任何旧账号、聊天、学习记录、资料、文件、流程、审核任务、SQLite内容和Qdrant历史；仅初始化预置角色、必要系统配置和新管理员。旧环境保持原样，验收后另行审批清理。
- 不调整权限、制度版本、Citation、CURRENT/HISTORICAL及ALL/SELECTED、RAG策略、Chunk切分、Prompt、学习业务规则和UI。不以迁移为理由新增产品功能。

以下是2026-10-10源代码核查，不是数据库实测；本轮没有启动服务或访问数据库。

| 分类 | 依据和判断 | 纳入阶段/验收 |
|---|---|---|
| 已存在 | `app/infrastructure/db/session.py`已用SQLAlchemy、pool_pre_ping；`migrations/versions`有0001—0012，历史基线使用固定DDL | P1保留、在空PostgreSQL重放；不能据此宣布已兼容 |
| 确定待改 | Parser/Index仓储仍使用sqlite3、PRAGMA、运行时建表；Chunk/元数据/纠错存在lastrowid，目录和读取服务直接连接SQLite | P2端到端替换，包含间接调用者，不只替换import |
| 确定待改 | `app/main.py` lifespan调用initialize_empty_baseline和ensure_auth_baseline | P2取消启动期DDL/业务初始化；只校验就绪 |
| 确定待改 | `worker.py:run_once`对入库任务先SELECT再赋租约；发布请求先SELECT后推进，无数据库原子领取门禁 | P3并发测试证明唯一领取；当前文件锁仅覆盖本机角色互斥 |
| 已存在/需扩展 | `learning_worker.py`已有条件UPDATE领取、rowcount检查、task_id/状态/时限结果校验，模型生成在会话外；尚无统一owner/租约代次 | P3复用已有CAS，增加续租及过期旧执行者隔离，不重写学习业务 |
| 已存在/需扩展 | Indexer有Alias切换核验和_reconcile_switching_run；该对账位于build路径，Worker选择的是排队态请求 | P3补启动恢复入口和Platform状态收尾；不能写成“完全没有对账” |
| 已存在/需替换 | 清理有退役记录和引用保护，但使用BEGIN IMMEDIATE双库锁 | P3替换锁机制，保留清单/保护/重入原则 |
| 已存在 | KnowledgeService专用单线程Runtime；KnowledgePaths受控目录、materials_root、独立学习Worker | P2会话适配、P4完整部署和挂载；不承诺迁库自动提升问答并发 |
| 待验证风险 | PostgreSQL迁移SQL、NULL/时区/排序、断连恢复、ARM64依赖和字体、实际UOS运行时 | P1—P5对应测试后才能确认，不作为已经发生的故障 |

### 5.2 P0：环境核查、边界确定、旧环境保护

**范围：** 只读环境盘点、架构决策和资源清单，不安装、不清库。后续任何新依赖先给出精确版本和手工命令，由用户安装确认。

**数据库边界推荐：一个PostgreSQL实例、两个database（platform、knowledge）。**

| 比较项 | 两个database（推荐） | 一个database、两个schema |
|---|---|---|
| 当前代码适配 | 延续两套连接/所有权，无需合并事务上下文 | 必须增加schema限定、search_path及迁移隔离策略 |
| 事务 | 各自本地事务，跨库操作显式补偿 | 可以共享事务，但现有独立连接不会自动共享；强行合并将扩大改造 |
| 权限 | 独立连接权限、运行账号和迁移权限更直观 | 可实现细粒度隔离，但需谨慎管理schema和默认权限 |
| 连接管理 | 每进程两套有界连接池 | 若保留模块会话边界，不会自然消除双池；共享池需额外设计 |
| Alembic | 两个入口、各库独立版本表 | 两个入口、独立schema版本表，自动生成需严格过滤 |
| 一致性/恢复 | 两库与Qdrant需维护窗口和发布协调 | 同样无法将Qdrant纳入关系库原子事务 |

结论：合并schema当前没有足够收益，不引入跨库外键、跨模块ORM关系或分布式事务。各模块只通过既有服务契约协作。该推荐作为本方案实施基准，无需再次向用户重复询问技术选型。

**关键任务：**

1. 盘点本机容器、端口、卷、collection、Alias和配置；复用已有Qdrant容器，但新测试使用独立profile/collection前缀/Alias，禁止与旧环境共用发布Alias。命名隔离不能替代删除保护；不删除旧collection、不导入旧数据。
   **前置阻断：** 当前IndexConfig三个字段为默认常量，management/catalog/read_service调用默认配置，CLI还显式写入旧名称；只有RagRuntime部分支持POLICY_INDEX_PROFILE。参数化dataclass不等于环境配置已贯通。必须先统一profile、alias、collection_prefix配置源，覆盖初始化、构建、发布、读取、CLI和维护入口，并验证跨命名空间Run ID不能被激活/清理；隔离未验收前禁止新系统向共享Qdrant写入。
2. 固定新开发PostgreSQL双库及文件测试根目录；冻结依赖候选、SQL差异及当前公开数据契约。开发重置只允许显式命令检查环境、库名、目录和二次确认；生产没有自动重置路径。
3. 记录生产信息为**用户三轮检查提供，尚未由本轮实机验证**：UOS20 fuyu/仓库1070，Kunpeng920 5250、aarch64、16核，内核4.19.90-2403.3.0.0270.84.uel20.aarch64，内存30GiB约27GiB可用、Swap8GiB，XFS根分区70GB剩余约61GB、ftype=1，签名OverlayFS模块、cgroup v1控制器；仅已知22/111/631监听，Docker/Compose未安装。
4. 记录UOS仓库域名解析失败，不能据此认定完全断网。优先官方兼容包或已验证ARM64离线包，核对Engine/containerd/runc/Compose依赖组合；不使用其他发行版一键安装脚本。当前不操作生产服务器。
5. 提前核查固定版本的linux/arm64镜像、Python依赖wheel/构建条件、LibreOffice与字体来源；记录远程模型网络验收方法。无ARM64实机时只能记录“待实机验收”，不能提前判通过。

**交付物：** 双database ADR、环境/保护清单、SQLite依赖清单、版本/安装候选清单、待部署门禁。

**测试与放行：** 静态检查路径和配置无旧环境写入目标；明确隔离名称与精确依赖版本。UOS实机、单位合规、HTTPS、RPO/RTO等可保留到P5，不阻塞本地代码改造。

### 5.3 P1：Platform PostgreSQL迁移与空库重放

**范围：** Platform数据库连接、驱动、既有迁移与初始化入口；本阶段不宣称整个系统已脱离SQLite。

**关键任务：**

1. 保留0001—0012及revision身份，优先完整重放；逐项检查主键生成、Boolean、DateTime、NULL唯一槽位、约束/索引名称、batch_alter_table和原生SQL。确有方言问题才修改其兼容表达，记录审查依据，不用当前ORM.create_all跳过历史迁移。
2. 新增PG驱动并锁定经Windows/Linux ARM64验证的版本；数据库URL从环境读取，缺失时报配置错误，不回退SQLite。先使用同步SQLAlchemy，避免同步改为异步框架。
   PostgreSQL镜像由用户手动拉取；P1由Codex配置独立容器、持久卷、双database、角色、连接和迁移，不安装Windows PostgreSQL Server。驱动仍由用户执行获批准的安装命令。
3. 职责拆分：基础设施/授权安装命令创建双库和角色；迁移账号执行DDL；应用账号仅具有必要业务DML权限；独立幂等seed初始化预置角色/配置；bootstrap命令创建管理员。已有管理员时明确跳过或报冲突，绝不覆盖密码；不预置通用口令。
4. 连接预算供P2/P4沿用，以下为**待集成验证的保守起始值，不是容量承诺**：API每库pool_size=5/max_overflow=2；ingestion、learning每进程每库2/1；pool_timeout=10s、pool_recycle=1800s、pre_ping=true、连接超时5s。每种服务暂一进程；三者双库合计上限26，另预留维护互斥专用连接最多2和迁移/运维余量。迁移使用NullPool顺序执行，PG max_connections初始拟100；P4确认总预算，增加进程时重新计算。
5. 事务统一使用短with begin提交/异常回滚；普通业务会话建议statement_timeout=60s、lock_timeout=5s、idle_in_transaction_session_timeout=60s，作为可配置数据库保护值在P1/P2实测；迁移任务独立配置，不能套用短查询超时。以上不改变模型HTTP超时或业务SLA。
6. 迁移前默认预览并核验目标环境标识、连接主机/端口、数据库名、current_database/current_user、PG主版本、当前Alembic revision、代码head及有序待执行迁移；URL脱敏。执行需显式匹配预期目标身份与计划，未知/超前revision、错库、非17版本、目标变化即停止；执行前重查并取得迁移互斥。空库先确认无业务表，不能以“无版本表”认定可直接初始化，更不能自动stamp或清库。
7. 建立全项目连接入口审计清单：API/两种Worker、Alembic、CLI、bootstrap、修复/迁移/清理脚本、测试启动器、环境模板和PS1入口。P1完成Platform路径替换，列出仍留给P2的Knowledge路径；P2收口全部正式运行入口。审计包含sqlite URL、sqlite3、DB文件默认值及旧环境变量，不只搜索import。

**交付物：** PG配置与连接工厂、0001—0012兼容审查记录、双库/角色创建说明、Platform迁移和独立初始化命令、最小PG集成测试。

**测试与放行：** 隔离空Platform库升级至0012；重复upgrade无结构漂移；检查约束/索引与模型一致；初始化重复执行不重置管理员；提交/回滚、断连后新连接恢复有效。仅编译SQL不算空库验收。保留既有纯单元测试，无需把全部测试改为PG。

### 5.4 P2：Knowledge Repository、独立Alembic与启动只读检查

**范围：** parser/index仓储、chunker、metadata、parse_correction、catalog/read_service、RAG读取、管理/CLI及维护工具的数据访问；保持服务接口和结果字段语义。

**关键任务：**

1. 从现有最终数据模型建立Knowledge初始Alembic基线，包含必要外键、唯一约束、索引、审核/快照/退役记录。不搬运旧业务数据，不机械复制SQLite补列/回填历史。
2. 使用SQLAlchemy Core Table/表达式+Repository替换sqlite3、PRAGMA、executescript、?绑定、lastrowid、INSERT OR IGNORE、SQLite异常。主键用RETURNING/inserted_primary_key，明确冲突键的幂等写入，禁止用忽略全部异常替代。
3. Repository内部使用RowMapping，边界转换为既有dict/值对象；核对字段名、缺失与NULL区别、JSON编码、Boolean、主键类型、排序及稳定分页。时间内部统一有时区UTC，外部继续既有格式；遇到旧接口期待字符串时显式序列化。不顺手将全部Text JSON迁成JSONB，不改变用于哈希的规范化编码和证据身份。
4. Knowledge拥有独立Engine/连接工厂、MetaData、Alembic入口/版本表；数据库URL与文件data_root解耦。禁止模拟sqlite3.Connection或用字符串替换?的兼容壳隐藏方言问题。
5. 移除API/Worker启动路径的自动建表、补列和业务seed/回填；必要初始化只由独立命令执行。启动检查数据库可达、所需revision和受控目录权限，版本不满足则明确失败；空制度库本身合法。模型依赖保留惰性初始化，不能因远程模型暂不可用阻止登录和治理。
6. RAG保留现有专用执行线程策略，改为短连接/会话，先取得所需不可变证据数据再调用模型，不持有跨请求裸连接或长事务。解析/转换先准备临时结果，再短事务写入；按现有运行版本保证重试可追踪。
7. 将错误分为连接/事务故障、约束冲突和业务校验；断连或提交结果不明先按唯一业务键查询结果，再决定有限重试。禁止盲目重放整个外部调用流程；失败连接先rollback/丢弃。
8. 完成P1连接入口清单：统一数据库URL与文件根目录语义，移除POLICY_DB_PATH等DB文件回退；检查PLATFORM_KNOWLEDGE_DATA_ROOT与CLI的POLICY_KNOWLEDGE_DATA_ROOT分叉。逐个验证正式CLI/后台脚本不会访问旧SQLite；历史工具明确归档或阻断，不作为可用运维入口。验收兼顾静态扫描和隔离环境实际调用，不要求删除历史资料中的SQLite字样。

**交付物：** Core仓储、Knowledge Alembic基线、访问契约对照、无DDL启动检查、旧SQLite运维脚本归档/禁用说明（历史文档可留，不参与新运行）。

**测试与放行：** 空Knowledge库迁移、两库独立revision、主键与JSON/时间/NULL/排序契约测试；用无DDL权限的应用账号重启API/Worker，确认不建表、不写seed、不改业务记录。生产运行路径无sqlite3/SQLite回退；隔离PG集成测试替换依赖SQLite行为的部分，纯单元测试继续复用。P2结束前不同时支持新旧数据引擎运行。

### 5.5 P3：原子领取、发布恢复与业务闭环

**2026-10-11阶段结论：** 本地最小验收通过，有条件进入P4，非生产放行。下列原定验收要求继续有效；尚未完成的物理故障、历史范围、非ADMIN权限及Citation边界、完整学习流程验证纳入P4/P5联合验收，并在正式上线前完成。本次登录态验收依据用户执行记录，不重复登录，不将单次18秒问答作为SLA。

**范围：** 在现有Worker和发布服务内修可靠性；不建恢复微服务、不引入新队列产品，仍各一个Worker实例。

**最小必要原则：** 优先复用现有状态、CAS、任务/发布记录和部分对账；只增加领取互斥、执行身份及恢复判定确实需要的字段和短事务，不另建通用调度系统或平行状态机。每项新增需对应本阶段故障验收用例。

**领取与租约任务：**

- 入库、学习和发布任务使用条件UPDATE RETURNING；复杂候选选择可用短事务SELECT FOR UPDATE SKIP LOCKED再更新。领取成功以受影响记录/返回行为准，不能以先查到记录为准。
- 统一必要字段lease_owner、lease_expires_at、heartbeat_at及单调递增lease_generation（可复用已有等价字段）。使用数据库时间比较租约；每次领取产生新代次。续租、进度、成功和失败写入均带任务ID、owner、代次和有效期条件。
- 租约初始建议120s、每30s通过独立短会话续租，可配置；与当前10分钟入库租约区别记入迁移记录，不把租约当模型超时。续租失败即停止接受新阶段；过期结果不得激活、覆盖新任务或写终态。
- 知识侧发布/激活和结果登记也必须携带执行身份并校验，不只保护Platform终态。跨库没有原子租约验证：知识侧记录接收的操作键/代次，激活入口串行化；跨库交接不明确则进入恢复判定，不自动接管推进。
- 运行中的外部调用可能无法取消，故保证的是“同一有效租约唯一拥有者”和“旧执行者不能提交有效结果”，不承诺所有外部计算恰好执行一次。临时文件用任务/代次目录，未发布索引用确定性point和版本化collection重入；旧结果保持不可见。
- 过期回收先核查阶段及已落库运行，能收尾则收尾、能幂等续做则续做；审核驳回/内容错误不自动重试，网络类故障有限退避、记录attempt，超过上限人工处理。不改变学习题量、有效期和模型重试业务规则。
- 长模型调用、DOCX转换、Embedding/Qdrant操作放在数据库事务外；短事务完成领取、进度、结果收尾。数据库断连导致提交结果不明时先查询幂等操作键，不能直接重复发布。

**发布与清理互斥：**

1. 同一profile的发布、激活、恢复和清理使用同一数据库互斥入口及持久化维护/操作记录，替换BEGIN IMMEDIATE。建议在Platform库使用session级advisory lock的专用连接（不持有长事务），短事务记录owner/代次/目标/base/来源指纹/管理员确认信息，异常释放并关闭连接，不把带锁连接返回普通池。
2. 所有写Alias/删除collection的CLI也必须走该入口；外部人工Qdrant操作列为维护禁令。临近外部操作再次检查owner、维护标记、base和目标。Qdrant不提供本方案所需的租约代次CAS，单靠前置检查存在检查后竞争窗口，不能称为分布式原子锁。
3. 锁连接丢失、旧调用未结束或Alias结果不明时标记需核查、冻结该profile后续发布/清理；确认旧进程/调用结束并读取实际状态后再恢复，禁止仅因租约过期立即并发接管Alias。该保守策略优先保护有效索引。
4. 清理仍须明确清单和二次引用检查：全部Alias目标、active/latest、保留ID、未完成发布绑定来源与IndexRun、维护状态；持续保留退役墓碑。保护检查失败或服务不可达则停止，不据“不知道”判定可删。

**发布状态的权威与恢复表：**

Alias表示实际向量路由；Knowledge保存版本化内容及已确认active；Platform保存操作意图、人工确认、任务和审计。任何一个单独状态都不能证明三者完整一致。沿用“Alias切换成功是正式发布必要时点”，只有来源/内容核验和指针收尾一致才对外报告正常完成；不一致时拒绝有风险的问答/变更，不拼接两份快照。

| 持久化阶段/事实 | 恢复动作 | 验收 |
|---|---|---|
| BUILDING或INDEXING，租约已失效 | 用操作键、冻结来源和IndexRun核查，续做缺失批次或标记可重试；来源变化要求重新请求 | 不重复创建业务版本，不改变现行Alias |
| READY_TO_PUBLISH | 复核物理索引，恢复“待管理员确认”；保留确认信息，绝不自动越过审批 | 重启不自动发布 |
| PUBLISHING/switching，Alias仍指向已记录base | 核验有效管理员确认、目标、来源及旧执行者已停止后再幂等切换；否则人工处理 | 不切换未获确认的目标 |
| Alias已指向已核验目标，但Knowledge/Platform未完成 | 用已持久化请求、目标和来源清单补齐Knowledge active及Platform任务/审计；先识别此场景，不能因base已变化直接报废请求 | 重复恢复不再次Embedding、不重复业务事件 |
| Alias为其他目标、指针/来源冲突、目标缺失或旧执行者未停止 | 冻结该profile发布/清理，记录差异并要求人工确认；不猜测回切/覆盖 | 保护现有有效索引，可解释错误 |
| Qdrant/数据库暂不可达 | 保留待恢复状态，有限重试；绝不当成Alias不存在或任务未成功 | 恢复后可继续对账 |

Worker启动时执行有界恢复扫描；操作异常后在同一Worker的后续轮询中有限重查，复用现有_reconcile_switching_run并补Platform收尾。包括READY_TO_PUBLISH但不自动确认。提供同一服务的管理员CLI预览/受控修复入口，不新增管理UI或定时调度系统。正式状态名以当前枚举为准，表中的INDEXING等阶段不能被当作新增状态直接写库。

**交付物：** 统一领取/续租及代次保护、发布互斥/阶段日志、恢复表实现、诊断CLI、最小故障注入集成测试。

**测试与放行：** 两个测试Worker连接争抢同一任务仅一个领取；过期旧执行者的进度/失败/成功提交被拒绝；解析、Embedding、Alias切换前后分别中断后恢复；重点验证Alias已切换而任一库提交失败。Qdrant或PG断连不破坏旧快照。完成空系统管理员→上传→解析复核→元数据→分块复核→索引→人工发布→问答，以及权限、历史范围、Citation、学习、配套资料最小回归。测试并发领取不等于生产启用多实例。P3通过才进入完整应用Docker化。

### 5.6 P4：Compose、共享文件、持久化与升级

**范围：** 单Compose管理web、api、ingestion-worker、learning-worker、postgres、qdrant及独立migrate入口；不把多个后台进程塞进同一容器。保留本机开发入口。

**关键任务：**

1. web为Nginx+现有Vite静态产物，统一IP入口、同源/api；配置SPA路由、上传大小限制、代理请求/响应及信任代理范围。生产API、数据库、Qdrant不发布不必要的宿主机端口；开发数据库端口只绑定本机。
2. 先数据库health，再显式迁移双库和必要seed，最后API/Worker检查版本启动；管理员独立初始化。区分容器存活、数据库就绪和远程模型可用，不循环启动来掩盖迁移失败。
3. API和相关Worker挂载同一受控文件根目录，包括制度原文、accepted、PDF和materials。按职责授予最小读写权限，统一UID/GID；检查XFS、SELinux等宿主策略及容器用户权限，禁止用全目录777代替配置。
4. 临时区按任务/代次隔离，正式文件不可覆盖。写入先临时文件、校验完整性，再在**同一文件系统**原子重命名；元数据标记就绪后才提供读取。文件和数据库不能原子提交，利用现有artifact/任务记录保存准备/完成状态：文件失败回滚业务可见状态；提交不明先查任务和checksum；孤儿文件仅按受控路径、无引用、保留期清理，不自动清扫用户目录。
5. PostgreSQL、Qdrant、业务文件、日志分别持久化；镜像排除真实.env、数据库、上传文件和备份。数据库数据优先放WSL2 Linux卷；生产挂载根目录上线前确定。业务文件路径存相对路径，严格防路径逃逸。
6. 开发Compose复用已有Qdrant外部地址/网络，不接管或重建原容器；完整独立验收/生产Compose启用自己的qdrant服务和新卷。同一套配置用明确覆盖文件/profile区分，两种模式禁止同时绑定旧端口/卷。
7. 固定镜像版本，生产不用latest或启动时pip安装；build阶段安装审批过的依赖。配置密钥通过受控文件/环境注入，避免日志明文。生产Cookie/CSRF/HTTPS按入口实际配置，HTTPS责任未明确前不能宣称已满足上线安全要求。
8. 每种Worker一实例，停止先停止领取、完成阶段或按P3恢复；配置有界停止宽限期。验证重启策略、内存/CPU约束在cgroup v1实际生效及日志轮转。估算峰值需包含全量新旧collection同时存在、PDF/temp、镜像旧版和备份；61GB剩余不是容量承诺。
9. 增加轻量运行巡检命令/结构化日志：连接池使用量与等待超时、PG活动连接、宿主数据盘剩余空间、Qdrant健康/collection数量及存储目录占用、容器健康与RestartCount。阈值通过配置提供，异常给出明确告警输出和处理指引；不新建监控平台，不把point数量等同磁盘字节。P4用模拟低空间/池超时和测试容器重启验证可见性。

**交付物：** 双架构Dockerfile、Compose及dev/prod配置模板、Nginx、卷/目录权限说明、文件补偿策略、迁移/管理员入口、更新操作说明。

**测试与放行：** 本地Linux容器空系统闭环；上传和资料读取、临时写入中断及补偿、共享权限验证；重建容器/更新应用镜像后账号、制度、文件、Alias和索引保留；迁移失败阻止新业务启动；旧Qdrant容器与数据不变。禁止升级脚本down -v、drop/recreate生产库或自动重置索引。

### 5.7 P5：UOS ARM64、离线交付、备份恢复及上线

**交付准备记录：** [P5 ARM64交付说明](P5_ARM64_DELIVERY.md)包含独立生产Compose、摘要候选锁、手动构建导出和9项最小测试结果。当前仅完成本地配置准备；manifest、镜像构建、服务器Compose版本兼容性及实机验收待执行，未部署。用户确认HTTP 80内网验收，HTTPS/异机备份不阻塞交付准备，正式上线前再评估。

**2026-10-12 已核实环境更新：** 以[UOS P5环境基线](UOS_P5_ENVIRONMENT_BASELINE.md)为当前服务器事实源（用户实测）。/data 挂载、Docker 与其管理的 containerd 持久化目录、启动挂载保护均已完成，不重复迁移或重装；Engine 29.0.4/containerd 2.1.5/runc 1.3.3 保留，Compose v5.0.0-rc.2 暂保留，正式部署前验证兼容性并按需更换稳定版。安装来源仍待确认；当前仅登记，未执行镜像导入、项目部署、业务数据库初始化或历史数据迁移。

**范围：** 本地业务及Compose验证完成后，经授权实施生产环境准备。当前无独立ARM64测试机，最终以UOS实际运行验收为准；模拟器/镜像构建成功不能替代。

**关键任务与交付物：**

1. 验证兼容UOS20/cgroup v1的Engine、containerd、runc、Compose包组合及依赖；准备经批准来源的ARM64离线安装包。不得根据内核版本自动推断支持，也不照搬其他发行版安装脚本。合规软件清单、安全扫描要求作为上线门禁。
2. 交付包含web、backend、postgres、qdrant的固定linux/arm64镜像、架构/版本/校验清单、Compose模板、迁移脚本、操作手册；说明离线导出/传输/load及启动方法，生产不现场联网构建。旧版本程序镜像另留以备兼容回退，无需建设供应链管理系统。
3. 目标机验证容器网络、DNS、路由、模型服务TLS/证书、现有HTTP接口超时、资源限制、存储权限和重启恢复。模型暂不可用应有可解释状态，不重写接口协议。
4. LibreOffice Headless与经授权中文字体在ARM64实际转换样本文档，核对页码映射和引用定位。结构/页码映射自动检查与视觉版式检查分开；本计划将中文字体、分页、引用位置列为验收项，执行视觉核对前按项目规则确认具体样本和范围，不能用本地Word结果替代。
5. 首次生产部署空双库、空Qdrant和空业务目录；迁移/seed/新管理员完成后由业务系统导入正式制度、案例及流程等，不复制开发测试卷。约1000注册用户不等于已验证并发；耗时压力/容量测试只准备命令和说明，另行批准执行。
6. 在UOS验证P4巡检的权限与采集结果，记录连接池、磁盘、Qdrant占用和容器重启初始基线；上线前指定巡检责任人、执行频率、告警接收方式及阈值。没有通知渠道时明确仅提供命令/日志，不宣称已经自动告警。

**备份、恢复与回滚：**

- 首版维护窗口暂停写入口与后台任务，确认无正在执行/结果不明的发布、清理及文件操作后生成一致备份集。备份两个PG库（例如pg_dump/pg_restore逻辑格式）、角色/授权恢复说明、Qdrant支持的快照及Alias清单、正式业务文件；运行中的数据目录不能直接拷贝当作可靠备份。
- 每套备份记录应用/镜像版本、双库Alembic revision、IndexRun与冻结来源、Alias目标、文件清单/校验值、备份时间、工具/数据库/Qdrant版本。密钥单独受控保存；同磁盘副本不能作为完整容灾。
- 独立环境恢复：先创建数据库/权限，恢复兼容版本的两个库及文件、Qdrant快照，按清单核对/恢复Alias；检查revision、IndexRun来源、指针、文件checksum、登录与一次问答后才能宣布恢复成功。禁止对来源不明的新空库直接stamp冒充迁移成功。
- 升级前备份、审查变更、迁移、验证，再恢复写入。程序回滚只适用于旧程序仍兼容当前结构；结构回退单独审查，不默认alembic downgrade。业务数据恢复只在明确批准后执行；如升级后已有新写入，先保全并制定处理策略，不能自动用旧备份覆盖。
- PG大版本和Qdrant格式升级独立排期，禁止只换major镜像标签并复用旧数据目录。优先小步、向后兼容结构变更；破坏性迁移必须单独审核。
- 上线前确定RPO、RTO、备份频率/保留期、异机位置和磁盘增长阈值。测算镜像、双库、新旧索引、文件/temp及至少一套备份的峰值；空间不满足则扩容或迁移挂载盘，不能通过自动删除历史业务来“腾空间”。

**测试与放行：** ARM64联合业务测试、实际DOCX验收、容器重建/停止恢复、内部模型连通，以及至少一次独立环境完整备份恢复演练通过并留记录。HTTPS责任、单位合规、运行时安装来源、磁盘空间及备份目标全部确认后方可导入正式数据并上线。

### 5.8 本次新增的必要事项

| 必要事项 | 阶段 | 验收依据 |
|---|---|---|
| 两database明确边界、旧Qdrant命名隔离、UmiJS描述纠正 | P0 | ADR/资源清单与实际代码一致 |
| 保留Platform历史重放、独立seed/管理员与连接预算 | P1 | 空库到0012，重复执行不重置数据 |
| Core Repository兼容契约、Knowledge新基线、无DDL启动 | P2 | 双库独立版本、只读启动检查及类型回归 |
| 原子领取、代次隔离、租约续期、Alias部分成功恢复 | P3 | 两执行者争抢/过期写入/断连/中断故障用例 |
| 共享文件原子落盘与补偿、完整服务和卷配置 | P4 | 文件失败及容器更新数据保留 |
| UOS安装来源、ARM64实测、成套备份恢复和离线包 | P5 | 目标机及独立恢复环境验收记录 |

### 5.9 简化或暂缓的事项

- 不迁历史业务数据、不同时兼容SQLite/MySQL、不全面ORM化Knowledge、不强制重写纯单元测试。
- 不引入Redis、Celery、Kafka、Kubernetes、分布式事务、独立恢复服务、复杂备份平台或镜像供应链系统。
- 不改检索/Chunk/Prompt/模型配置/学习规则/UI，不顺带增加全自动索引恢复、孤儿collection自动删除或多Worker生产扩容。
- 不重排既有Platform历史迁移；Knowledge从最终模型建初始基线。已存在学习CAS和Indexer部分对账直接复用，避免重复实现。
- 先本地PG和闭环，后应用容器；ARM64前期做可行性预检，最终离线部署和实机联合验收放P5。
- 仅执行阶段必要的小规模测试；长耗时转换/压力/恢复测试预先给出耗时、进度和手动命令，按项目规则另行批准。

### 5.10 需要用户决定的架构问题与部署门禁

**当前无需重复确认的技术基准：** PostgreSQL、两个database、Core+Repository、两套Alembic、单机Compose、每种Worker一实例、现有远程模型、无历史数据迁移。数据库边界由上述代码分析明确推荐，不为合库扩大范围。

**仍须用户/单位在P5前决定：** 指定软件/国产化及基础镜像限制；Docker兼容安装包批准来源；HTTPS由网关还是Nginx承担及证书；实际网络策略和传输方式；正式持久化挂载位置/是否扩容；RPO/RTO、备份周期/保留期及异机位置。以上不是已满足条件，不阻塞P1—P3本地验证，但阻止未经验证正式上线。旧数据清理以后单独授权，不与新系统验收自动绑定。

**P0/P1执行进展（2026-10-10）：** 固定linux/amd64镜像`postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`，实连版本17.11，用户安装的psycopg 3.3.6已验证。隔离容器`policy-platform-pg17-dev`监听127.0.0.1:55432，独立持久卷；Platform空库完整重放0001—0012并重复执行通过，Knowledge空库保留给P2。两库owner/app权限分离，迁移前校验数据库身份、标记、revision及迁移文件指纹。独立初始化角色/provider，不创建默认管理员。

Qdrant三元组配置已统一，修改命名空间须同时指定profile/alias/prefix；激活与清理拒绝跨命名空间运行。新配置为`policy_platform_pg17_dev` / `policy_platform_pg17_dev_active` / `policy_platform_pg17_dev`，尚未创建新collection或切Alias。最终只读复核旧Alias仍指向`policy_platform_dense_acd380ffb89f_4ffad605`，两个旧collection保留。旧.env、SQLite及业务文件不清理、不切换。

19项最小测试通过。完整API/Worker无SQLite运行、取消Knowledge运行时DDL、故障恢复与完整业务闭环仍属于P2/P3；当前不能据此宣称全项目已迁移完成。ARM64与生产部署尚未验证。迁移保护目前只放行本机P1身份，生产身份配置在P4适配。详细入口清单、边界、手动命令见[验证记录](../testing/POSTGRES_P0_P1_VERIFICATION_2026-10-10.md)，数据库决策见[ADR-0006](../decisions/ADR-0006-POSTGRES-DATABASE-BOUNDARY.md)。

参考：[驱动发布信息](https://pypi.org/project/psycopg-binary/3.3.6/)、[SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)、[Alembic迁移审查](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)、[Compose启动依赖](https://docs.docker.com/compose/how-tos/startup-order/)、[多平台镜像](https://docs.docker.com/build/building/multi-platform/)、[PostgreSQL逻辑备份](https://www.postgresql.org/docs/current/backup-dump.html)。

## 6. 历史验证记录（2026-09-24，非本次P0—P5验收）

本轮测试集中在存储复用、清理保护/重入、发布失败保持旧快照，以及跨平台入口命令。
最终12项必要测试通过（含删除断连后DELETING持久化及重试），启动入口help检查通过。
实库只读核验：IndexRun仍为9条，1—7的来源记录仍为34条；退役标记均DELETED。
保留8为325 points、9为382 points，均green，active/latest指针均为9。
未运行全量测试、真实Embedding重建、压力测试、Linux容器构建或LibreOffice版式验收。

复测：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:POLICY_TEST_RUNTIME_ROOT='D:\2-code\policy-platform\var\tests\docker-ready'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_index_storage_lifecycle.py tests/test_portable_startup.py tests/test_v2_governance.py::test_alias_failure_keeps_old_metadata_and_old_index_active -q -p no:cacheprovider -p no:tmpdir
```

正式打包阶段再执行Linux启动、卷持久化、迁移、DOCX渲染与Compose停止/重启验收；届时另行确认依赖安装和视觉检查。
