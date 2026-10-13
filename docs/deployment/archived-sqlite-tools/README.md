# 旧SQLite工具归档

文件说明：2026-10-10 P2归档；状态HISTORICAL。以下`.txt`为原源码快照，不作为Python运行入口。

| 快照 | 原用途 | 当前替代/边界 |
|---|---|---|
| backend__knowledge__data_migrations.py.txt | 历史元数据回填 | 新系统不迁移历史业务数据 |
| backend__knowledge__indexing__maintenance.py.txt | 双SQLite锁保护的索引退役 | PG维护锁及恢复待P3 |
| scripts__migrate-knowledge-data.py.txt | 旧库业务与文件迁移 | 空库新导入，不再使用 |
| scripts__migrate-knowledge-metadata.py.txt | 显式历史回填 | 空库新导入，不再使用 |
| scripts__retire-index-storage.py.txt | 旧索引清理命令 | 当前入口阻断，待P3验收 |
| scripts__repair-phase2-consistency.py.txt | 旧环境一次性业务纠错 | 当前入口阻断，待P3恢复机制 |

结构迁移使用`scripts/migrate-platform-pg.py`与`scripts/migrate-knowledge-pg.py`，不导入这些旧脚本。旧SQLite/Qdrant/业务文件本轮均未删除。
