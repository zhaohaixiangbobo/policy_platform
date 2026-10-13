"""文件说明：旧SQLite专用工具已归档；PG维护恢复在P3按新事务边界实施。"""

def retire_collections(*args, **kwargs):
    raise RuntimeError("PostgreSQL清理入口待P3验收；旧SQLite工具已归档")


def validate_targets(*args, **kwargs):
    raise RuntimeError("请使用P3 PostgreSQL维护流程")
