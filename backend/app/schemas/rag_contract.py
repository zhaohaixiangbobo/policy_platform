"""文件说明：兼容导出知识模块的稳定查询契约。

新代码直接使用knowledge.contracts；本模块只保留旧测试和调用方使用的Rag前缀名称，
避免维护两套完全相同的Pydantic模型。
"""

from knowledge.contracts import (
    CitationResponse as RagCitation,
    ConflictPositionResponse as RagConflictPosition,
    ConflictResponse as RagConflict,
    ErrorDetail as RagErrorDetail,
    ErrorResponse as RagErrorResponse,
    LatencyResponse as RagLatency,
    ProvenanceResponse as RagProvenance,
    QualityGateResponse as RagQualityGate,
    QueryResponse as RagQueryResponse,
    RetrievalResponse as RagRetrieval,
)

__all__ = [
    "RagCitation",
    "RagConflict",
    "RagConflictPosition",
    "RagErrorDetail",
    "RagErrorResponse",
    "RagLatency",
    "RagProvenance",
    "RagQualityGate",
    "RagQueryResponse",
    "RagRetrieval",
]
