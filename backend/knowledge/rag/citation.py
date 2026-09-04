"""文件说明：生成稳定证据ID、来源Node映射和响应级Citation Registry。

E1/E2只在单次回答中有效；跨响应审计使用由文档校验值、Chunk业务键、正文哈希
和版本共同计算的evidence_uid。引用元数据只能来自SQLite，不由LLM生成。
"""

from __future__ import annotations

from pathlib import PurePath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from ..indexing.config import canonical_json, sha256_text

from .models import EvidenceRecord, SourceNodeSpan


def build_evidence_uid(
    *,
    document_checksum: str,
    chunk_key: str,
    raw_text_hash: str,
    chunker_version: str,
    template_version: str,
    uid_version: str = "evidence_uid_v1",
) -> str:
    """计算不依赖本次Rerank名次的稳定证据标识。"""

    if not document_checksum or not chunk_key or not raw_text_hash:
        raise ValueError("生成evidence_uid所需的文档/Chunk哈希字段不能为空")
    payload = {
        "uid_version": uid_version,
        "document_checksum": document_checksum,
        "chunk_key": chunk_key,
        "raw_text_hash": raw_text_hash,
        "chunker_version": chunker_version,
        "template_version": template_version,
    }
    return "ev_" + sha256_text(canonical_json(payload))[:32]


def safe_source_reference(source_file: str | None, file_name: str | None) -> str:
    """将源文件转换为可公开的相对引用，避免泄露服务器绝对路径。"""

    raw = str(source_file or "").strip()
    if raw:
        # 同时兼容Windows和POSIX风格路径，优先截取source_documents以下部分。
        parts = PureWindowsPath(raw).parts if "\\" in raw else PurePath(raw).parts
        lowered = [part.lower() for part in parts]
        if "source_documents" in lowered:
            start = lowered.index("source_documents")
            return "/".join(parts[start:])
        if not PureWindowsPath(raw).is_absolute() and not raw.startswith("/"):
            return raw.replace("\\", "/")
    return str(file_name or "source-unavailable")


def source_rows_to_spans(rows: Sequence[Mapping[str, Any]]) -> tuple[SourceNodeSpan, ...]:
    """把数据库来源行转换为不可变、按来源顺序排列的Node映射。"""

    ordered = sorted(rows, key=lambda row: (int(row["source_order"]), int(row["id"])))
    return tuple(
        SourceNodeSpan(
            node_id=int(row["node_id"]),
            source_order=int(row["source_order"]),
            contribution_role=str(row["contribution_role"]),
            node_char_start=_optional_int(row.get("node_char_start")),
            node_char_end=_optional_int(row.get("node_char_end")),
            chunk_char_start=_optional_int(row.get("chunk_char_start")),
            chunk_char_end=_optional_int(row.get("chunk_char_end")),
            mapping_type=str(row["mapping_type"]),
            source_text_hash=str(row["source_text_hash"]),
            is_primary=bool(row["is_primary"]),
            node_type=_optional_str(row.get("node_type")),
            node_number=_optional_str(row.get("node_number")),
            node_title=_optional_str(row.get("node_title")),
            node_path_text=_optional_str(row.get("node_path_text")),
            node_page_start=_optional_int(row.get("node_page_start")),
            node_page_end=_optional_int(row.get("node_page_end")),
        )
        for row in ordered
    )


class CitationRegistry:
    """响应级E编号白名单和程序引用渲染入口。"""

    def __init__(self, evidences: Iterable[EvidenceRecord]) -> None:
        records = tuple(evidences)
        mapping = {record.citation_label: record for record in records}
        if len(mapping) != len(records):
            raise ValueError("Citation Registry存在重复E编号")
        expected = tuple(f"E{index}" for index in range(1, len(records) + 1))
        if tuple(record.citation_label for record in records) != expected:
            raise ValueError("Citation Registry的E编号必须从E1连续递增")
        self._records = records
        self._mapping: Mapping[str, EvidenceRecord] = MappingProxyType(mapping)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self._mapping)

    def __contains__(self, label: object) -> bool:
        return label in self._mapping

    def get(self, label: str) -> EvidenceRecord:
        try:
            return self._mapping[label]
        except KeyError as exc:
            raise ValueError(f"引用编号不在本次证据白名单：{label}") from exc

    def resolve(self, labels: Sequence[str]) -> tuple[EvidenceRecord, ...]:
        return tuple(self.get(label) for label in labels)

    def api_citations(
        self, labels: Sequence[str] | None = None, *, include_debug: bool = False
    ) -> list[dict[str, Any]]:
        selected = self._records if labels is None else self.resolve(labels)
        return [record.to_dict(include_debug=include_debug) for record in selected]


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
