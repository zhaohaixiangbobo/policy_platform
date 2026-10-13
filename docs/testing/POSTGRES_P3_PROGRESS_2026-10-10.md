# P3实施进度（尚未放行）

> 历史记录：下文保留首批互斥实施时的状态，当前实现、数据库版本、测试和命令见[2026-10-11验证记录](POSTGRES_P3_VERIFICATION_2026-10-11.md)。

文件说明：记录已落实代码与剩余验收，不以局部测试替代P3完成声明。

## 已完成

- README初始化、管理员、服务启动及最小测试段落直接替换为PG当前命令；移除历史启动命令的可执行示例。
- API/Worker仍使用P2数据库结构，没有新增或执行迁移。
- ingestion-worker和learning-worker主入口增加PG session advisory lock。同一Platform库同角色串行，两个角色独立；专用NullPool、AUTOCOMMIT连接，不占用业务池、不持有长事务。原Windows角色文件锁保留。
- `tests/test_pg_p3.py`一项PG测试通过：同角色第二连接拒绝、不同角色并行、正常/异常退出释放锁。测试没有创建业务数据或写Qdrant。

## 明确边界

此互斥只落实首版单实例部署约束，**不是任务原子领取、租约代次保护或Qdrant分布式锁**。连接丢失后的旧执行者防护尚未实现；不能据此部署多Worker或开始故障恢复验收。锁每角色另需一个专用连接，三服务业务池预算33之外增加2，运维连接另计。

## 下一批必须完成

1. 入库/发布当前先查后执行改为短事务原子领取；学习已有条件更新，统一补执行身份/有效租约、续租和终态防护。每次结果登记校验代次，不复用业务state_version作为长任务租约代次。
2. 长调用前释放Platform事务；Knowledge侧登记操作身份，禁止旧执行者推进active指针。
3. 发布profile互斥、持久化阶段及不明确状态冻结；Alias已切换时先对账，再处理base变化。不能沿用当前异常统一FAILED覆盖部分成功事实。
4. 有界重启恢复与管理员诊断CLI；维护/清理入口继续阻断，待保护规则验证后开放。
5. 增加PG争抢、过期提交拒绝、Alias部分成功恢复测试；真实模型/Qdrant及完整上传问答/学习/资料闭环另行最小验证，不启动全量或压力测试。

执行命令（仅互斥测试）：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:PLATFORM_ENV_FILE='D:\2-code\policy-platform\var\postgres-dev\platform.env'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_pg_p3.py -q --tb=short -p no:cacheprovider -p no:tmpdir
```

旧SQLite/Qdrant/文件保持不变；未安装依赖，未开始P4。P3仍为IN_PROGRESS。
