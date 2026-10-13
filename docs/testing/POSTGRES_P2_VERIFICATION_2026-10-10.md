# P2 Knowledge PostgreSQL 实施与运行记录

文件说明：2026-10-10，postgres_compose_plan_v1.3；P1收口及P2本地最小验收通过。P3可靠性、真实外部服务闭环和P4/P5部署验收尚未执行。

## 1. 当前版本与边界

| 部分 | 当前状态 |
|---|---|
| PostgreSQL / 驱动 | 17.11 / psycopg[binary] 3.3.6；复用P1容器及两个database |
| Platform Alembic | 0012_supporting_materials，保留0001—0012历史 |
| Knowledge Alembic | k0001_baseline → k0002_document_series_index；独立版本表 |
| Knowledge存储 | SQLAlchemy Core + Repository；生产路径移除原生sqlite3、PRAGMA、?参数、lastrowid及文件库回退 |
| 初始化 | 独立迁移、独立角色/管理员、独立Knowledge目录/profile命令 |
| 启动 | API及两个Worker只读检查双库版本、认证配置和文件目录，不建表、不seed |
| Qdrant | 新命名空间policy_platform_pg17_dev；本轮没有创建collection或切Alias |
| 业务数据 | 新Platform用户0、新Knowledge制度0；仅预置角色/provider及索引profile |

原.env、SQLite、旧业务文件和旧Qdrant保持不变，但**当前代码正式运行只支持PG**；旧.env不能继续用于启动新代码。原先已运行的进程未被停止。两环境Worker锁目录已隔离；如旧API占用8020，先由用户停止旧API或为新进程另设端口。

Knowledge基线保留已有唯一约束、外键及删除行为、索引、审核、元数据、快照和退役表。首次空库验收后核对发现制度系列查询索引需补齐，使用k0002追加，未重写已执行的k0001。冻结模型`knowledge_migrations/baseline_v1.py`独立于当前模型，且参与迁移审批指纹。

## 2. 数据访问契约与事务

- ParserDatabase、IndexDatabase保持业务方法，内部使用CoreRepository和SQLAlchemy语句。静态查询使用明确命名参数的TextClause；动态字段更新/克隆使用Table表达式，列表过滤使用expanding绑定或PG数组。没有运行时占位符翻译或模拟sqlite连接。
- SELECT结果在连接内物化，经RowMapping转换为既有dict/值对象，连接立即归还池；写阶段显式save/discard。异常保留SQLAlchemy约束/连接分类，释放失败事务，不盲目重放模型调用。
- 主键使用RETURNING；chunk_index_record只对明确的(index_run_id,chunk_id)唯一键执行ON CONFLICT DO NOTHING，其他冲突正常报错。
- Text JSON、0/1标志和Knowledge既有ISO 8601 UTC时间字符串保持存储/输出契约；不顺带改为JSONB/Boolean或改变证据哈希。Platform原DateTime(timezone=True)保持PG时区语义；Knowledge时间由UTC函数生成，文件日期仍为业务日期字符串。
- 多步学习取材使用短REPEATABLE READ只读快照，模型调用发生在连接释放之后。RAG保留原专用线程，Repository空闲时不持有裸连接。解析/渲染、Embedding、Qdrant调用不由仓储包裹成长事务。
- Platform每进程池上限7，Knowledge每进程上限4；API及两类Worker按3进程估算上限33，不含迁移/测试连接。更多API进程需重新计算预算，不能照此推定并发容量。
- 发布跨库恢复、任务原子领取与过期租约处理仍为P3；本轮没有实现新的调度器或自动对账服务。

## 3. P1收口

两套Alembic入口在迁移事务内收紧版本表写权限：app只读，owner迁移。head上重复执行也固化权限。测试明确断言版本表SELECT可用、写权限关闭、Platform app不能在public建表。

Platform管理员初始化及持续维护的测试动态读取代码head，不再写死0012。Knowledge的旧“必须空库”断言已替换为版本、结构和权限验收；历史P1记录仍保留当时结论。

## 4. 运行步骤

P1容器已运行，双库迁移和必要初始化已执行。**不要重建容器、删卷、重跑建库脚本或复制旧数据。** 如需核查或在未来重复部署：

```powershell
Set-Location 'D:\2-code\policy-platform'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[System.Text.UTF8Encoding]::new($false)

# 两库分别预览；审阅目标、head、待执行列表后，传入各自当次指纹
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-platform-pg.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/migrate-knowledge-pg.py
# --execute-plan '<对应预览sha256>'

# 独立基础初始化；已有角色/profile及管理员密码不会被重置
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-knowledge-pg.py

# 首次创建新的管理员，交互输入密码；旧账号不迁入
& 'D:\3-anaconda\envs\py312\python.exe' scripts/initialize-platform-pg.py --username '<管理员名>' --display-name '<显示名>'

# 分别在终端启动，显式选用新PG配置
& '.\scripts\dev-postgres.ps1' api
& '.\scripts\dev-postgres.ps1' worker
& '.\scripts\dev-postgres.ps1' learning-worker
```

`initialize-knowledge-pg.py --inherit-runtime-settings`已执行一次：仅从旧.env继承模型、渲染、学习开关等白名单配置，保留新库、目录及Qdrant隔离值。后续可直接编辑受控新配置，不要把真实密码提交或输出；生产账号与部署标记机制仍在P4适配。

Knowledge CLI沿用`-m knowledge.cli`，需相同PLATFORM_ENV_FILE；`--data-root`只指定文件目录，数据库固定从KNOWLEDGE_DATABASE_URL读取，不能用它切换数据库。未设置PG配置时明确失败，不创建SQLite文件。

## 5. 最小验证结果

12项测试通过，pytest退出码0：

1. P0命名空间完整性及跨环境激活拒绝。
2. Platform迁移账号身份、动态head、模型/数据库结构一致、最小权限。
3. 管理员重复创建保护；临时测试用户事务回滚。
4. Knowledge head、Core结构及版本表权限。
5. Core主键返回、NULL、中文、读后归还连接、事务回滚、约束错误后连接可重新使用。
6. 真实小DOCX解析（禁用渲染）：SourceBlock、Node落PG，没有生成.db文件。
7. Parse审核→元数据提交/批准→Chunk生成/审核→IndexRun构建/校验/激活及幂等复用；数据库全部为真实PG，模型和Qdrant为测试替身。
8. 来源hydrate、证据候选、公开目录、权限ID过滤、关键词、学习取材、元数据草稿不影响当前快照、派生ParseRun不修改旧正文。
9. API重复启动，live/ready均200；SQL监听确认无DDL/INSERT/UPDATE/DELETE。
10. 生产模块静态扫描无sqlite3、POLICY_DB_PATH、lastrowid、BEGIN IMMEDIATE。

上述为12个测试函数的覆盖范围，不表示每条覆盖项各为一个独立测试。另实际执行两类Worker --once，均空队列正常退出；Knowledge独立迁移、初始化执行成功。测试使用随机schema，结束均移除；var/tests/pg-p2中的小样本保留便于复查。

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
$env:PYTHONIOENCODING='utf-8'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_pg_p1.py tests/test_pg_p2.py -q --tb=short -p no:cacheprovider -p no:tmpdir
```

未执行全量测试、压力/稳定性测试、真实外部模型与Qdrant写入、完整浏览器上传发布、Worker故障注入、Linux/ARM64、LibreOffice视觉验收。这些属于P3—P5；不因本轮模拟索引通过而宣称外部系统已联合验收。旧SQLite集成夹具仍是历史测试，不能直接作为当前PG验收命令；纯规则单元测试保留。本轮没有要求用户立即运行耗时测试。

## 6. 历史工具与后续

旧历史数据迁移、元数据回填、双SQLite清理和一致性修复入口已阻断；原源码存放在[归档目录](../deployment/archived-sqlite-tools/README.md)，仅供追溯，不可作为当前运维脚本。P3完成PG维护互斥及恢复验收后再开放清理操作。

下一步P3：原子任务领取、租约失效写入保护、双库与Alias部分成功恢复、真实上传至问答及学习/资料/权限闭环。正式迁移只使用新环境，不处理旧数据清理。P4完整Compose，P5 ARM64/离线/备份恢复顺序不变。
