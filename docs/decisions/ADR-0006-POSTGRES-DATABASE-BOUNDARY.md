# ADR-0006：PostgreSQL 双 database 边界

文件说明：2026-10-10，状态 Accepted；P0/P1/P2本地最小验收通过。API/Worker只读就绪检查已实现；完整可靠性验收留在P3。当前运行以[P2记录](../testing/POSTGRES_P2_VERIFICATION_2026-10-10.md)为准，旧存储保留但当前代码只支持PostgreSQL。

## 决策

同一PostgreSQL 17实例使用`platform`、`knowledge`两个database，各自owner/app账号、连接池和Alembic入口。Platform沿用ORM与0001—0012；Knowledge采用Core + Repository，以最终模型建立独立基线。旧SQLite数据不迁移且暂保留。

## 理由

现有Platform Session与Knowledge原生连接已经分离，业务通过应用服务协调而非跨库外键。两个database延续边界，权限与迁移目标清晰；代价是独立连接和无法共享单一事务。一个database两个schema可支持同连接跨schema事务，但当前代码仍需重构才能利用，还增加search_path、反射和迁移归属管理，本轮收益不足。

双库事务与Qdrant Alias不具备全局原子性；P3复用发布阶段、来源清单和幂等对账处理，不引入分布式事务。数据库创建由环境配置负责，结构由Alembic负责，角色/provider及管理员由独立初始化负责。API/Worker只做版本就绪检查的最终要求在P2/P3完成。

## 实施边界

本机开发库与旧环境完全分离。生产仍为空库部署，应用升级保留数据。新系统完整业务验收前不替换旧.env、不删除旧存储。见[阶段方案](../deployment/DOCKER_READY_AND_INDEX_RETIREMENT.md)和[验证记录](../testing/POSTGRES_P0_P1_VERIFICATION_2026-10-10.md)。
