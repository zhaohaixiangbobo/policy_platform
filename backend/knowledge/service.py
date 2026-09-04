"""文件说明：保留旧导入名的兼容层，实际查询统一通过公开 RAG HTTP API。"""

from app.infrastructure.rag_api_client import (
    RagApiClient as KnowledgeService,
    RagApiClientError as KnowledgeServiceError,
)

__all__ = ["KnowledgeService", "KnowledgeServiceError"]
