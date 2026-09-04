"""文件说明：统一验证Platform跨库证据引用，在详情、审核和发布时返回稳定有效性状态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge.config import KnowledgePaths
from knowledge.read_service import KnowledgeReadService


@dataclass(frozen=True)
class EvidenceValidationResult:
    status: str
    reason: str


class EvidenceReferenceValidator:
    """只读检查知识库，不建立跨库外键且不修改active指针。"""

    def __init__(self, knowledge_database: Path) -> None:
        self.reader = KnowledgeReadService(KnowledgePaths(knowledge_database.resolve().parent))

    def validate(self, document_id: int, parse_run_id: int, primary_node_id: int, quote_snapshot: str, snapshot_hash: str) -> EvidenceValidationResult:
        status, reason = self.reader.validate_evidence(
            document_id, parse_run_id, primary_node_id, quote_snapshot, snapshot_hash
        )
        return EvidenceValidationResult(status, reason)

    def validate_document_version(self, document_id: int, parse_run_id: int) -> EvidenceValidationResult:
        status, reason = self.reader.validate_document_version(document_id, parse_run_id)
        return EvidenceValidationResult(status, reason)
