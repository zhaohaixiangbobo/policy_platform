"""文件说明：旧SQLite专用工具已归档；PG维护恢复在P3按新事务边界实施。"""

def migrate_historical_published_metadata(*args, **kwargs):
    raise RuntimeError("新系统空库部署，不迁移历史业务数据")
