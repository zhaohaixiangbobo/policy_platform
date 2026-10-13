# P3 Worker与索引发布恢复记录

文件说明：2026-10-11。P3本地最小验收通过，有条件放行进入P4；专项边界验收保留，不代表生产放行。取代10月10日进度记录的当前状态描述。

## 当前版本及实现

- Platform：`0013_worker_leases`；Knowledge：`k0003_worker_operation`。新增迁移前已检查开发库身份、revision及指纹，旧数据未清理。
- 三类任务以`FOR UPDATE SKIP LOCKED`候选选择及`UPDATE RETURNING`原子领取；数据库时钟、owner、递增generation和有效期共同约束执行。
- 租约默认120秒，`PLATFORM_WORKER_LEASE_SECONDS`可配置（至少30秒）；独立短会话每租约三分之一、最多30秒续租。续租失败放弃本代次结果，不把租约当模型超时。
- Platform提交在同一事务校验并锁定租约；学习进度/成功/失败条件更新。新任务使旧代次失效；外部模型调用不持有业务事务。
- Knowledge写事务校验并锁定操作代次，记录解析/分块完成回执；每轮有界扫描恢复已完成结果及文件登记。收尾再次中断仍可重试；失败回执恢复FAILED，running结果禁止进入审核。
- 两类Worker使用独立PG角色锁；CLI及Worker构建/激活/恢复共用profile互斥。专用NullPool/AUTOCOMMIT会话不持有长事务；批次写Qdrant和切Alias前再次校验。
- Alias操作前持久化switching。未收尾状态阻止新构建/激活，不自动回切；PUBLISHING异常保留待核查事实，不统一写FAILED。
- 已切Alias恢复校验管理员确认、请求冻结来源、命名空间、active基线、物理point和payload，然后补双库状态；不重跑Embedding、不再切Alias。Platform任务、元数据和请求单事务收尾，重复恢复不重复事件。
- BUILDING可明确确认旧执行结束后重排原冻结请求，沿用Indexer幂等复用；READY_TO_PUBLISH仍须管理员确认。

互斥及租约不是Qdrant分布式事务，不承诺外部计算恰好一次。Alias结果不明、指向其他目标、旧调用未结束时保留人工核查。旧collection清理入口继续禁用，本轮未开放删除功能。

连接预算：三进程业务池上限33，Worker角色锁另加2，索引操作另加1；迁移/诊断/测试另计，不作为容量承诺。

## 诊断与恢复

默认只读预览：

```powershell
Set-Location 'D:\2-code\policy-platform'
& 'D:\3-anaconda\envs\py312\python.exe' scripts/recover-publication-pg.py
```

以下仅是故障处理模板，正常运行不要执行。先确认旧进程及外部调用结束，核对请求ID；构建重试还需确认模型/索引配置未变化：

```powershell
# Alias已到目标，补齐收尾；不重新切换Alias
& 'D:\3-anaconda\envs\py312\python.exe' scripts/recover-publication-pg.py --request-id '<请求ID>' --action publish-finish --execute --confirm-executor-stopped
# BUILDING中断，重排原冻结请求，不自动确认发布
& 'D:\3-anaconda\envs\py312\python.exe' scripts/recover-publication-pg.py --request-id '<请求ID>' --action build-retry --execute --confirm-executor-stopped
# 缺少完成回执的中断：优先兑现回执，否则登记中断失败
& 'D:\3-anaconda\envs\py312\python.exe' scripts/recover-publication-pg.py --job-id '<任务ID>' --action ingestion-fail --execute --confirm-executor-stopped
```

预检/解析中断登记后可在任务中心人工重试。分块不删除或覆盖旧ChunkRun，需核查后走返工流程。网络不可达、基线/来源冲突时停止，不直接改库标记发布成功。普通网络有限重试沿用客户端，审核内容错误不自动重试。

## 验证与实际数据

P1/P2/P3共24项最小测试通过，覆盖三类争抢、续租/过期拒绝、知识代次屏障、模型调用无长事务、回执恢复幂等、Alias部分成功恢复及目标冲突拒绝、受控中断登记与构建重排，包含P2解析/分块/索引/目录/引用来源/学习取材回归。PG业务写入使用随机schema，结束清理；测试锁和命名空间隔离，模型/Qdrant写操作使用替身。

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
$env:PYTHONIOENCODING='utf-8'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_pg_p1.py tests/test_pg_p2.py tests/test_pg_p3.py -q --tb=short -p no:cacheprovider -p no:tmpdir
```

2026-10-11只读核查用户数据：6个PUBLISHED入库任务、1个PUBLISHED发布请求、1个READY学习槽位；active IndexRun 1包含6份来源，Qdrant实际497 point与expected/verified=497一致，failed=0，Alias目标匹配；HTTP ready为200。此核查不等于重做上传、权限或问答端到端测试，没有重新发布用户索引。

### 用户执行的登录态联合验收

证据来源：用户于2026-10-11提供的实际执行结果；本轮仅登记，不由Codex重复执行，也不保存账号密码。API请求经前端5173代理，与浏览器访问路径一致。

| 验收项 | 用户报告结果 |
| --- | --- |
| 浏览器制度入库闭环 | 完成上传到发布，6份制度已发布 |
| 登录 | 200，ADMIN角色，不要求修改密码 |
| `/auth/me` | 200 |
| 任务中心 / 发布记录 / 制度治理 / 制度库 / 资料库 | 全部200，数量分别为6 / 1 / 6 / 6 / 25 |
| 配套资料推荐：“八项规定 典型案例” | 200，返回2条案例 |
| 写请求不带CSRF令牌 | 403，正确拦截 |
| 带CSRF令牌创建问答会话 | 201 |
| 真实问答：“违反中央八项规定精神会受到什么处理？” | 200，18秒，8条引用，内容正常 |
| 退出后请求`/auth/me` | 401，会话失效 |

**登录态联合验收已通过（API经5173代理测试 + 浏览器上传发布6份制度），不用再测登录。** 先前Codex登录尝试返回401保留为历史观察，其原因未确认；该观察不再作为当前验收阻断，也不据此认定账号异常。18秒是单次问答样本，不作为响应时间SLA或容量结论。

## 放行结论

P3本地最小验收通过，可有条件进入P4 Docker Compose集成。依据为此前24项最小测试、真实数据只读核验及本次用户提供的登录态业务闭环结果。此结论允许推进容器化，不等于原计划所有故障和权限边界均已实测通过。

以下专项继续保留为P4/P5联合验收及正式上线前检查项；本轮没有执行P4、重新登录、运行测试、修改代码或操作业务数据。

## 剩余验收

- CURRENT/HISTORICAL范围隔离、非ADMIN角色权限矩阵及Citation越权/失效边界仍需专项验证；本次8条引用正常和ADMIN登录成功不替代这些边界用例。学习侧已有最小回归和READY状态核验，完整用户学习流程仍留待联合验收。
- 物理杀进程/断网故障、提交瞬间连接中断、锁会话丢失而外部调用未结束等边界还需专项验收；当前为受控最小故障注入，不宣称全部无人值守恢复。
- Alias仍在base时当前命令停止；需核查后决定重试，不自动重切。READY_TO_PUBLISH不自动确认。
- 全量测试、压力/稳定性测试、Linux/ARM64、完整Compose与备份恢复未执行；未安装依赖、未清理用户数据。P4/P5尚未开始。
