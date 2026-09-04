"""文件说明：将Rerank Top8构造成有预算、可引用、可审计的LLM证据上下文。

该模块不调用Embedding、Reranker或LLM；它只接受两阶段检索结果，并从SQLite
active IndexRun权威回读Chunk与全部Node来源。Parent Expansion在第一版明确关闭。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from typing import Any, Mapping, Protocol, Sequence

from .citation import build_evidence_uid, safe_source_reference, source_rows_to_spans
from .config import ContextBuilderConfig
from .models import ContextBundle, EvidenceGroup, EvidenceRecord, OmittedEvidence
from .token_budget import ConservativeTokenEstimator, TokenBudget


class ContextDatabase(Protocol):
    """Context Builder所需的最小只读数据库接口。"""

    def active_context(self, profile_name: str) -> dict[str, Any]: ...

    def hydrate_chunks(
        self, index_run_id: int, chunk_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]: ...

    def hydrate_citation_sources(
        self, index_run_id: int, chunk_ids: Sequence[int]
    ) -> dict[int, list[dict[str, Any]]]: ...


class TokenEstimator(Protocol):
    version: str

    def estimate(self, text: str) -> int: ...


class ContextBuilder:
    """构造确定性的ContextBundle和Citation证据集合。"""

    def __init__(
        self,
        database: ContextDatabase,
        *,
        config: ContextBuilderConfig | None = None,
        estimator: TokenEstimator | None = None,
        profile_name: str = "policy_platform_dense",
    ) -> None:
        self.database = database
        self.config = config or ContextBuilderConfig()
        self.estimator = estimator or ConservativeTokenEstimator()
        self.profile_name = profile_name
        if self.estimator.version != self.config.token_estimator_version:
            raise ValueError("Token估算器实现与Context配置版本不一致")

    def build(
        self,
        question: str,
        reranked_results: Sequence[Mapping[str, Any]],
        *,
        retrieval_config_hash: str | None = None,
    ) -> ContextBundle:
        normalized_question = " ".join(question.split())
        if not normalized_question:
            raise ValueError("Question不能为空")

        active = self.database.active_context(self.profile_name)
        if active.get("status") != "succeeded" or active.get("activation_status") != "active":
            raise RuntimeError("active IndexRun状态不允许构造RAG上下文")
        active_run_id = int(active["id"])

        all_results = list(reranked_results)
        if not all_results:
            return ContextBundle(
                question=normalized_question,
                index_run_id=active_run_id,
                retrieval_config_hash=retrieval_config_hash or "no_results",
                context_config_hash=self.config.config_hash,
                estimator_version=self.estimator.version,
                evidence_budget_tokens=self.config.evidence_budget_tokens,
                estimated_tokens=0,
                evidences=(),
                groups=(),
                omitted=(),
                rendered_context="",
            )

        run_ids = {int(item["index_run_id"]) for item in all_results}
        if run_ids != {active_run_id}:
            raise RuntimeError(
                f"Rerank结果必须全部来自active IndexRun {active_run_id}，实际为{sorted(run_ids)}"
            )
        resolved_retrieval_hash = self._resolve_retrieval_hash(
            all_results, retrieval_config_hash
        )

        ranked = sorted(all_results, key=self._rank_key)
        selected = ranked[: self.config.max_evidence]
        omitted: list[OmittedEvidence] = [
            OmittedEvidence(
                chunk_id=_optional_int(item.get("chunk_id")),
                rerank_rank=_optional_int(item.get("rerank_rank", item.get("rank"))),
                reason="outside_rerank_top8",
            )
            for item in ranked[self.config.max_evidence :]
        ]
        chunk_ids = [int(item["chunk_id"]) for item in selected]
        chunks = self.database.hydrate_chunks(active_run_id, list(dict.fromkeys(chunk_ids)))
        missing = sorted(set(chunk_ids) - set(chunks))
        if missing:
            raise RuntimeError(f"以下Chunk无法从active IndexRun权威回读：{missing}")
        source_rows = self.database.hydrate_citation_sources(
            active_run_id, list(dict.fromkeys(chunk_ids))
        )

        budget = TokenBudget(self.config.evidence_budget_tokens)
        accepted: list[EvidenceRecord] = []
        blocks: list[str] = []
        seen_chunks: set[int] = set()
        seen_document_text: set[tuple[int, str]] = set()

        for result in selected:
            chunk_id = int(result["chunk_id"])
            chunk = chunks[chunk_id]
            rerank_rank = int(result.get("rerank_rank", result.get("rank", 0)))
            if self.config.deduplicate_same_chunk and chunk_id in seen_chunks:
                omitted.append(OmittedEvidence(chunk_id, "duplicate_chunk", rerank_rank))
                continue
            document_text_key = (int(chunk["document_id"]), str(chunk["raw_text_hash"]))
            if (
                self.config.deduplicate_same_document_text
                and document_text_key in seen_document_text
            ):
                omitted.append(
                    OmittedEvidence(chunk_id, "duplicate_same_document_text", rerank_rank)
                )
                continue

            rows = source_rows.get(chunk_id, [])
            if not rows:
                raise RuntimeError(f"Chunk {chunk_id}缺少可审计的Node来源映射")
            base = self._build_record(active_run_id, chunk, rows, result)
            label = f"E{len(accepted) + 1}"
            record = replace(base, citation_label=label)
            block = self._render_evidence(record)
            incremental_text = ("\n\n" if blocks else "") + block
            block_tokens = self.estimator.estimate(incremental_text)
            if not budget.try_add(block_tokens):
                omitted.append(OmittedEvidence(chunk_id, "token_budget_exceeded", rerank_rank))
                continue

            accepted.append(replace(record, estimated_tokens=block_tokens))
            blocks.append(block)
            seen_chunks.add(chunk_id)
            seen_document_text.add(document_text_key)

        groups = self._build_groups(accepted)
        return ContextBundle(
            question=normalized_question,
            index_run_id=active_run_id,
            retrieval_config_hash=resolved_retrieval_hash,
            context_config_hash=self.config.config_hash,
            estimator_version=self.estimator.version,
            evidence_budget_tokens=self.config.evidence_budget_tokens,
            estimated_tokens=budget.used,
            evidences=tuple(accepted),
            groups=groups,
            omitted=tuple(omitted),
            rendered_context="\n\n".join(blocks),
        )

    @staticmethod
    def _rank_key(item: Mapping[str, Any]) -> tuple[int, int]:
        rerank_rank = int(item.get("rerank_rank", item.get("rank", 10**9)))
        chunk_id = int(item.get("chunk_id", 10**9))
        return rerank_rank, chunk_id

    @staticmethod
    def _resolve_retrieval_hash(
        results: Sequence[Mapping[str, Any]], explicit: str | None
    ) -> str:
        reported = {
            str(item["retrieval_config_hash"])
            for item in results
            if item.get("retrieval_config_hash")
        }
        if len(reported) > 1:
            raise RuntimeError("Rerank结果混用了多个retrieval_config_hash")
        if explicit and reported and explicit not in reported:
            raise RuntimeError("显式retrieval_config_hash与结果记录不一致")
        resolved = explicit or (next(iter(reported)) if reported else None)
        if not resolved:
            raise ValueError("构造RAG上下文必须记录retrieval_config_hash")
        return resolved

    def _build_record(
        self,
        index_run_id: int,
        chunk: Mapping[str, Any],
        source_rows: Sequence[Mapping[str, Any]],
        result: Mapping[str, Any],
    ) -> EvidenceRecord:
        checksum = str(
            chunk.get("accepted_document_checksum")
            or chunk.get("document_checksum")
            or ""
        )
        chunk_key = str(chunk["chunk_key"])
        path_text = _optional_str(chunk.get("path_text"))
        document_id = int(chunk["document_id"])
        group_key = f"document:{document_id}|path:{path_text or '<unknown>'}"
        return EvidenceRecord(
            citation_label="",
            evidence_uid=build_evidence_uid(
                document_checksum=checksum,
                chunk_key=chunk_key,
                raw_text_hash=str(chunk["raw_text_hash"]),
                chunker_version=str(chunk["chunker_version"]),
                template_version=str(chunk["template_version"]),
                uid_version=self.config.evidence_uid_version,
            ),
            index_run_id=index_run_id,
            chunk_run_id=int(chunk["chunk_run_id"]),
            parse_run_id=int(chunk["parse_run_id"]),
            chunk_id=int(chunk["id"]),
            chunk_key=chunk_key,
            document_id=document_id,
            document_title=str(chunk.get("document_title") or "制度名称未识别"),
            document_code=_optional_str(chunk.get("document_code")),
            document_status=str(chunk.get("document_status") or "unknown"),
            source_reference=safe_source_reference(
                _optional_str(chunk.get("source_file")),
                _optional_str(chunk.get("file_name")),
            ),
            path_text=path_text,
            page_start=_optional_int(chunk.get("page_start")),
            page_end=_optional_int(chunk.get("page_end")),
            primary_node_id=_optional_int(chunk.get("primary_node_id")),
            source_nodes=source_rows_to_spans(source_rows),
            raw_text_hash=str(chunk["raw_text_hash"]),
            dense_rank=int(result.get("dense_rank", result.get("rank", 0))),
            dense_score=float(result.get("dense_score", result.get("score", 0.0))),
            rerank_rank=int(result.get("rerank_rank", result.get("rank", 0))),
            rerank_score=float(result.get("rerank_score", result.get("score", 0.0))),
            text=str(chunk["raw_text"]),
            estimated_tokens=0,
            group_key=group_key,
            citation_version=self.config.citation_version,
            evidence_uid_version=self.config.evidence_uid_version,
        )

    @staticmethod
    def _render_evidence(record: EvidenceRecord) -> str:
        status_label = {
            "effective": "现行有效",
            "expired": "已失效",
            "abolished": "已废止",
            "unknown": "状态未知",
        }.get(record.document_status, record.document_status)
        code = record.document_code or "文号未识别"
        path = record.path_text or "条款未识别"
        page = _format_page(record.page_start, record.page_end)
        return "\n".join(
            [
                f"[{record.citation_label}]",
                f"制度名称：{record.document_title}",
                f"文号：{code}",
                f"状态：{status_label}",
                f"条款：{path}",
                f"页码：{page}",
                f"来源：{record.source_reference}",
                f"证据ID：{record.evidence_uid}",
                "原文：",
                record.text,
                f"[/{record.citation_label}]",
            ]
        )

    @staticmethod
    def _build_groups(records: Sequence[EvidenceRecord]) -> tuple[EvidenceGroup, ...]:
        grouped: OrderedDict[str, list[EvidenceRecord]] = OrderedDict()
        for record in records:
            grouped.setdefault(record.group_key, []).append(record)
        return tuple(
            EvidenceGroup(
                group_key=key,
                document_id=items[0].document_id,
                document_title=items[0].document_title,
                document_code=items[0].document_code,
                path_text=items[0].path_text,
                evidence_labels=tuple(item.citation_label for item in items),
            )
            for key, items in grouped.items()
        )


def _format_page(start: int | None, end: int | None) -> str:
    if start is None:
        return "页码未知"
    if end is None or end == start:
        return f"P{start}"
    return f"P{start}-P{end}"


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
