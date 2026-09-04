"""文件说明：声明SQLAlchemy 2.x模型统一基类，供后续领域表和Alembic使用。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Platform业务模型统一声明基类。"""
