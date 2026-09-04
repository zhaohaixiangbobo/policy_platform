"""文件说明：制度管理能力的包入口；问答调用由 Platform 的 HTTP 客户端负责。"""

from .catalog import KnowledgeCatalogService

__all__ = ["KnowledgeCatalogService"]
