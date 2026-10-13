"""制度结构 Chunk 生成、来源追溯、质量校验与版本激活。

本文件只消费已经落库的 ParseRun/PolicyNode，不修改解析结果。生成结果写入
chunk_run、policy_chunk、chunk_source_node 和 chunk_validation_issue；不包含
Embedding、Qdrant、召回或重排逻辑。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import hashlib
import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..parser.database import ParserDatabase, utc_now


CHUNKER_VERSION = "1.0.2"
RETRIEVAL_TYPES = {"article", "item", "paragraph", "preamble", "table"}
CONTEXT_TYPES = {"chapter", "section", "heading", "attachment"}
EXCLUDED_TYPES = {"addressee", "signature", "distribution", "document_code"}
SENTENCE_END = re.compile(r"[。！？!?；;]\s*|\n+")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并左闭右开字符区间。"""

    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


@dataclass(frozen=True)
class ChunkerConfig:
    """一次 ChunkRun 的可重现配置。"""

    strategy: str = "structure_first_v1"
    target_chars: int = 450
    soft_max_chars: int = 600
    hard_max_chars: int = 1200
    overlap_chars: int = 60
    min_retrieval_chars: int = 20
    table_repeat_header: bool = True
    retrieval_template_version: str = "retrieval_template_v1"
    tokenizer_name: str | None = None
    tokenizer_version: str | None = None

    def validate(self) -> None:
        if self.target_chars <= 0:
            raise ValueError("target_chars 必须大于 0")
        if self.soft_max_chars < self.target_chars:
            raise ValueError("soft_max_chars 不能小于 target_chars")
        if self.hard_max_chars < self.soft_max_chars:
            raise ValueError("hard_max_chars 不能小于 soft_max_chars")
        if not 0 <= self.overlap_chars < self.hard_max_chars:
            raise ValueError("overlap_chars 必须在 0 与 hard_max_chars 之间")
        if self.min_retrieval_chars < 0:
            raise ValueError("min_retrieval_chars 不能小于 0")

    def canonical_json(self) -> str:
        self.validate()
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return _sha256(self.canonical_json())


class PolicyChunker:
    """基于已审核 Node Tree 生成可审计 Chunk。"""

    def __init__(self, database_url: str, config: ChunkerConfig | None = None) -> None:
        self.db = ParserDatabase(database_url)
        self.config = config or ChunkerConfig()
        self.config.validate()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "PolicyChunker":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run_all_active(self, *, activate: bool = False) -> list[dict[str, Any]]:
        rows = self.db.repository.run(sql_text('SELECT id FROM policy_document WHERE active_parse_run_id IS NOT NULL ORDER BY id')).mappings().fetchall()
        return [self.run_document(int(row["id"]), activate=activate) for row in rows]

    def run_document(self, document_id: int, *, activate: bool = False) -> dict[str, Any]:
        row = self.db.repository.run(sql_text('SELECT active_parse_run_id FROM policy_document WHERE id=:p0'), {'p0': document_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"Document 不存在：{document_id}")
        if row["active_parse_run_id"] is None:
            raise ValueError(f"Document {document_id} 没有 active_parse_run_id")
        return self.run_parse_run(int(row["active_parse_run_id"]), activate=activate)

    def run_parse_run(
        self,
        parse_run_id: int,
        *,
        allow_unreviewed: bool = False,
        activate: bool = False,
    ) -> dict[str, Any]:
        """生成一个 ChunkRun；正式模式只允许读取 active ParseRun。"""

        if activate:
            raise ValueError("ChunkRun自动激活已禁用，请使用review-chunk完成显式人工批准")

        context = self._source_context(parse_run_id)
        active_parse_run_id = context["active_parse_run_id"]
        is_active = active_parse_run_id is not None and int(active_parse_run_id) == parse_run_id
        if not is_active and not allow_unreviewed:
            raise ValueError(
                f"ParseRun {parse_run_id} 不是 Document {context['document_id']} 的 active 版本；"
                "如仅做测试，请显式使用 allow_unreviewed=True"
            )
        source_scope = "active" if is_active else "experimental"
        config_json = self.config.canonical_json()
        config_hash = self.config.config_hash()
        existing = self.db.repository.run(sql_text("""
            SELECT id FROM chunk_run
            WHERE parse_run_id=:p0 AND chunker_version=:p1 AND config_hash=:p2
            """), {'p0': parse_run_id, 'p1': CHUNKER_VERSION, 'p2': config_hash}).mappings().fetchone()
        if existing:
            run_id = int(existing["id"])
            return self.run_summary(run_id)

        started = time.perf_counter()
        now = utc_now()
        cursor = self.db.repository.run(sql_text("""
            INSERT INTO chunk_run (
                document_id, parse_run_id, chunker_version, strategy,
                config_json, config_hash, tokenizer_name, tokenizer_version,
                status, review_status, source_scope, started_at, created_at
            ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, 'running', 'pending', :p8, :p9, :p10) RETURNING id"""), {'p0': int(context["document_id"]), 'p1': parse_run_id, 'p2': CHUNKER_VERSION, 'p3': self.config.strategy, 'p4': config_json, 'p5': config_hash, 'p6': self.config.tokenizer_name, 'p7': self.config.tokenizer_version, 'p8': source_scope, 'p9': now, 'p10': now})
        chunk_run_id = int(cursor.scalar_one())
        self.db.repository.run(sql_text('UPDATE policy_document SET latest_chunk_run_id=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': chunk_run_id, 'p1': utc_now(), 'p2': int(context["document_id"])})
        self.db.repository.save()

        try:
            nodes = self._load_nodes(parse_run_id)
            inline_contexts = self._detect_inline_contexts(nodes)
            context_node_ids = {
                int(context_node["id"])
                for context_nodes in inline_contexts.values()
                for context_node in context_nodes
            }
            eligible = self._eligible_nodes(nodes, context, context_node_ids)
            drafts, generation_issues = self._generate_drafts(
                nodes, eligible, context, inline_contexts
            )
            chunk_ids = self._insert_drafts(chunk_run_id, drafts)
            validation_issues, metrics = self._validate_run(
                chunk_run_id, parse_run_id, eligible, source_scope
            )
            self._insert_issues(
                chunk_run_id,
                [*generation_issues, *validation_issues],
                chunk_ids,
            )
            issue_counts = self._issue_counts(chunk_run_id)
            blocked = issue_counts["error"] + issue_counts["review"] > 0
            status = "review_required" if blocked else "succeeded"
            # 零问题运行仍需人工提交最终审核，不能把“无需逐项处置”视为批准。
            review_status = "pending" if blocked else "ready_for_approval"
            elapsed = time.perf_counter() - started
            self._update_chunk_run(
                chunk_run_id,
                status=status,
                review_status=review_status,
                finished_at=utc_now(),
                elapsed_seconds=round(elapsed, 6),
                validation_issue_count=sum(issue_counts.values()),
                **metrics,
            )
        except Exception as exc:
            self._update_chunk_run(
                chunk_run_id,
                status="failed",
                review_status="pending",
                finished_at=utc_now(),
                elapsed_seconds=round(time.perf_counter() - started, 6),
                error_code=type(exc).__name__,
                error_message=str(exc)[:2000],
            )
            # 与ParseRun保持一致：失败事实先完整落库，再由Worker读取status推进任务状态。
        return self.run_summary(chunk_run_id)

    def _source_context(self, parse_run_id: int) -> dict[str, Any]:
        row = self.db.repository.run(sql_text("""
            SELECT pr.id AS parse_run_id, pr.document_id, pr.status AS parse_status,
                   pr.review_status AS parse_review_status,
                   pd.title, pd.file_name, pd.issuing_org, pd.document_code,
                   pd.active_parse_run_id
            FROM parse_run pr
            JOIN policy_document pd ON pd.id=pr.document_id
            WHERE pr.id=:p0
            """), {'p0': parse_run_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"ParseRun 不存在：{parse_run_id}")
        return dict(row)

    def _load_nodes(self, parse_run_id: int) -> list[dict[str, Any]]:
        rows = self.db.repository.run(sql_text("""
            SELECT pn.*,
                   (SELECT sb.properties_json
                    FROM node_source_span nss
                    JOIN source_block sb ON sb.id=nss.source_block_id
                    WHERE nss.node_id=pn.id
                    ORDER BY nss.id LIMIT 1) AS source_properties_json
            FROM policy_node pn
            WHERE pn.parse_run_id=:p0
            ORDER BY pn.order_no, pn.id
            """), {'p0': parse_run_id}).mappings().fetchall()
        return [dict(row) for row in rows]

    def _eligible_nodes(
        self,
        nodes: list[dict[str, Any]],
        context: dict[str, Any],
        context_node_ids: set[int] | None = None,
    ) -> dict[int, dict[str, Any]]:
        context_node_ids = context_node_ids or set()
        first_content_order = min(
            (
                int(node["order_no"])
                for node in nodes
                if node["node_type"]
                in {"addressee", "preamble", "article", "heading", "chapter", "attachment", "table"}
            ),
            default=10**9,
        )
        title = _compact(context.get("title") or Path(context["file_name"]).stem)
        issuing_org = _compact(context.get("issuing_org"))
        document_code = _compact(context.get("document_code"))
        eligible: dict[int, dict[str, Any]] = {}
        for node in nodes:
            if int(node["id"]) in context_node_ids:
                continue
            if node["node_type"] not in RETRIEVAL_TYPES:
                continue
            if node["review_status"] != "confirmed":
                continue
            text = _compact(node.get("raw_text"))
            if not text:
                continue
            # 解析器没有单独的 document_title Node；此处避免把拆行标题当正文检索。
            if node["node_type"] == "paragraph" and int(node["order_no"]) < first_content_order:
                if (len(text) >= 3 and text in title) or text in {issuing_org, document_code}:
                    continue
            eligible[int(node["id"])] = node
        return eligible

    @staticmethod
    def _detect_inline_contexts(
        nodes: list[dict[str, Any]],
    ) -> dict[int, list[dict[str, Any]]]:
        """识别“备注：”一类紧邻 item/table 的短说明标签。

        该规则是解析分类和 Chunk 语义之间的适配层：不修改 paragraph Node，
        只将其从独立检索正文转为后续结构块的 title_context。
        """

        ordered = sorted(nodes, key=lambda item: (int(item["order_no"]), int(item["id"])))
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, node in enumerate(ordered[:-1]):
            if node["node_type"] != "paragraph" or node["review_status"] != "confirmed":
                continue
            text = str(node.get("raw_text") or "").strip()
            if not text or len(_compact(text)) > 20 or not text.endswith(("：", ":")):
                continue
            target = ordered[index + 1]
            if target["node_type"] not in {"item", "table"}:
                continue
            if target["review_status"] != "confirmed":
                continue
            # 只在同一结构父节点内归并，避免跨章节或跨附件错误吸附。
            if target.get("parent_id") != node.get("parent_id"):
                continue
            result[int(target["id"])].append(node)
        return result

    def _generate_drafts(
        self,
        nodes: list[dict[str, Any]],
        eligible: dict[int, dict[str, Any]],
        context: dict[str, Any],
        inline_contexts: dict[int, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        node_by_id = {int(node["id"]): node for node in nodes}
        children: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            parent_id = int(node["parent_id"]) if node["parent_id"] is not None else None
            children[parent_id].append(node)
        for group in children.values():
            group.sort(key=lambda item: (int(item["order_no"]), int(item["id"])))

        title = context.get("title") or Path(context["file_name"]).stem
        consumed: set[int] = set()
        drafts: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        def descendants(root_id: int) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []

            def walk(parent_id: int) -> None:
                for child in children.get(parent_id, []):
                    result.append(child)
                    walk(int(child["id"]))

            walk(root_id)
            return result

        for node in nodes:
            node_id = int(node["id"])
            if node_id not in eligible or node_id in consumed:
                continue
            node_type = str(node["node_type"])
            if node_type == "table":
                table_drafts, table_issues = self._table_drafts(node, title, node_by_id)
                drafts.extend(table_drafts)
                issues.extend(table_issues)
                consumed.add(node_id)
                continue

            if node_type == "article":
                units = [node] + [
                    item
                    for item in descendants(node_id)
                    if int(item["id"]) in eligible and item["node_type"] != "table"
                ]
                units.sort(key=lambda item: (int(item["order_no"]), int(item["id"])))
                total = sum(len(str(item["raw_text"])) for item in units) + max(0, len(units) - 1)
                base_key = f"article:{node_id}"
                if total <= self.config.hard_max_chars:
                    draft = self._draft_from_nodes(
                        base_key, "article", "retrieval", node, units, title, node_by_id
                    )
                    drafts.append(draft)
                    if total > self.config.soft_max_chars:
                        issues.append(
                            self._issue(
                                "structure",
                                "SOFT_LIMIT_RETAINED",
                                "review",
                                "条款超过软上限，但为保持结构完整而未拆分",
                                node_id=node_id,
                                chunk_key=base_key,
                                details={"char_count": total, "soft_max_chars": self.config.soft_max_chars},
                            )
                        )
                else:
                    parent = self._draft_from_nodes(
                        base_key,
                        "article",
                        "context",
                        node,
                        units,
                        title,
                        node_by_id,
                        contribution_role="path_context",
                        mapping_type="ancestor_context",
                    )
                    drafts.append(parent)
                    child_drafts, child_issues = self._split_node_units(
                        units,
                        base_key=f"{base_key}:part",
                        chunk_type="item" if any(item["node_type"] == "item" for item in units) else "paragraph",
                        primary=node,
                        document_title=title,
                        node_by_id=node_by_id,
                        parent_key=base_key,
                    )
                    drafts.extend(child_drafts)
                    issues.extend(child_issues)
                    issues.append(
                        self._issue(
                            "structure",
                            "OVERSIZED_ARTICLE_SPLIT",
                            "review",
                            "条款超过硬上限，已生成上下文父块和可检索子块",
                            node_id=node_id,
                            chunk_key=base_key,
                            details={"char_count": total, "hard_max_chars": self.config.hard_max_chars},
                        )
                    )
                consumed.update(int(item["id"]) for item in units)
                continue

            if node_type == "item":
                units = [node] + [
                    item
                    for item in descendants(node_id)
                    if int(item["id"]) in eligible and item["node_type"] != "table"
                ]
                units.sort(key=lambda item: (int(item["order_no"]), int(item["id"])))
                base_key = f"item:{node_id}"
                child_drafts, child_issues = self._split_node_units(
                    units,
                    base_key=base_key,
                    chunk_type="item",
                    primary=node,
                    document_title=title,
                    node_by_id=node_by_id,
                )
                drafts.extend(child_drafts)
                issues.extend(child_issues)
                consumed.update(int(item["id"]) for item in units)
                continue

            # 无条款归属的相邻普通段落，在同一父节点下按软上限合并。
            group = [node]
            for candidate in nodes[nodes.index(node) + 1 :]:
                candidate_id = int(candidate["id"])
                if candidate_id in consumed or candidate_id not in eligible:
                    if candidate["node_type"] in CONTEXT_TYPES | {"article", "item", "table"}:
                        break
                    continue
                if candidate["node_type"] not in {"paragraph", "preamble"}:
                    break
                if candidate["parent_id"] != node["parent_id"]:
                    break
                proposed = sum(len(str(item["raw_text"])) for item in group) + len(group) + len(str(candidate["raw_text"]))
                if proposed > self.config.soft_max_chars:
                    break
                group.append(candidate)
            base_key = f"{node_type}:{node_id}"
            group_drafts, group_issues = self._split_node_units(
                group,
                base_key=base_key,
                chunk_type="preamble" if node_type == "preamble" else "paragraph",
                primary=node,
                document_title=title,
                node_by_id=node_by_id,
            )
            drafts.extend(group_drafts)
            issues.extend(group_issues)
            consumed.update(int(item["id"]) for item in group)

        unconfirmed_count = sum(
            1
            for node in nodes
            if node["node_type"] in RETRIEVAL_TYPES and node["review_status"] != "confirmed"
        )
        if unconfirmed_count:
            issues.append(
                self._issue(
                    "generation",
                    "UNCONFIRMED_NODES_EXCLUDED",
                    "review",
                    "存在未确认 Node，已从 Chunk 正文中排除",
                    details={"count": unconfirmed_count},
                )
            )
        self._attach_inline_contexts(drafts, inline_contexts)
        return drafts, issues

    @staticmethod
    def _attach_inline_contexts(
        drafts: list[dict[str, Any]],
        inline_contexts: dict[int, list[dict[str, Any]]],
    ) -> None:
        """把说明标签写入包含目标 Node 的首个检索 Chunk 前缀和来源映射。"""

        for target_node_id, context_nodes in inline_contexts.items():
            target_draft = next(
                (
                    draft
                    for draft in drafts
                    if draft["is_retrievable"]
                    and any(
                        int(source["node_id"]) == target_node_id
                        and source["contribution_role"] == "body"
                        for source in draft["sources"]
                    )
                ),
                None,
            )
            if target_draft is None:
                continue
            labels = [str(node["raw_text"]).strip() for node in context_nodes]
            target_draft["prefix_text"] += "".join(f"\n【说明】{label}" for label in labels)
            target_draft["retrieval_text"] = (
                f"{target_draft['prefix_text']}\n【正文】\n{target_draft['raw_text']}"
            )
            for source_order, context_node in enumerate(context_nodes, start=1):
                source_text = str(context_node["raw_text"])
                target_draft["sources"].append(
                    {
                        "node_id": int(context_node["id"]),
                        "source_order": -len(context_nodes) + source_order - 1,
                        "contribution_role": "title_context",
                        "node_char_start": 0,
                        "node_char_end": len(source_text),
                        "chunk_char_start": None,
                        "chunk_char_end": None,
                        "mapping_type": "ancestor_context",
                        "source_text_hash": _sha256(source_text),
                        "is_primary": 0,
                    }
                )

    def _split_node_units(
        self,
        units: list[dict[str, Any]],
        *,
        base_key: str,
        chunk_type: str,
        primary: dict[str, Any],
        document_title: str,
        node_by_id: dict[int, dict[str, Any]],
        parent_key: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        parts: list[tuple[dict[str, Any], list[tuple[dict[str, Any], int, int, str, str]]]] = []
        issues: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        current_length = 0

        def flush() -> None:
            nonlocal current, current_length
            if current:
                parts.append(
                    (
                        current[0],
                        [
                            (item, 0, len(str(item["raw_text"])), "body", "exact")
                            for item in current
                        ],
                    )
                )
                current = []
                current_length = 0

        for unit in units:
            text = str(unit["raw_text"])
            if len(text) > self.config.hard_max_chars:
                flush()
                for start, end, mapping_type in self._split_text(text):
                    parts.append((unit, [(unit, start, end, "body", mapping_type)]))
                    if mapping_type == "overlap":
                        issues.append(
                            self._issue(
                                "generation",
                                "CHARACTER_WINDOW_FALLBACK",
                                "warning",
                                "缺少足够结构边界，已使用带重叠的字符窗口",
                                node_id=int(unit["id"]),
                                details={"node_char_start": start, "node_char_end": end},
                            )
                        )
                continue
            proposed = current_length + (1 if current else 0) + len(text)
            if current and proposed > self.config.soft_max_chars:
                flush()
            current.append(unit)
            current_length += (1 if current_length else 0) + len(text)
        flush()

        drafts: list[dict[str, Any]] = []
        for index, (part_primary, segments) in enumerate(parts, start=1):
            key = base_key if len(parts) == 1 else f"{base_key}:{index:03d}"
            drafts.append(
                self._draft_from_segments(
                    key,
                    chunk_type,
                    "retrieval",
                    part_primary if part_primary else primary,
                    segments,
                    document_title,
                    node_by_id,
                    parent_key=parent_key,
                )
            )
        return drafts, issues

    def _split_text(self, text: str, max_chars: int | None = None) -> Iterator[tuple[int, int, str]]:
        """优先在段落或句末切分，最后才使用带重叠字符窗口。"""

        limit = max_chars or self.config.hard_max_chars
        start = 0
        while start < len(text):
            hard_end = min(len(text), start + limit)
            if hard_end == len(text):
                yield start, hard_end, "subspan"
                break
            candidate = text[start:hard_end]
            boundaries = [match.end() for match in SENTENCE_END.finditer(candidate)]
            viable = [point for point in boundaries if point >= max(1, int(limit * 0.5))]
            if viable:
                end = start + viable[-1]
                yield start, end, "subspan"
                start = end
            else:
                end = hard_end
                yield start, end, "overlap"
                start = max(start + 1, end - self.config.overlap_chars)

    def _table_drafts(
        self,
        node: dict[str, Any],
        document_title: str,
        node_by_id: dict[int, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        text = str(node["raw_text"])
        node_id = int(node["id"])
        base_key = f"table:{node_id}"
        if len(text) <= self.config.soft_max_chars:
            return [
                self._draft_from_segments(
                    base_key,
                    "table",
                    "retrieval",
                    node,
                    [(node, 0, len(text), "body", "exact")],
                    document_title,
                    node_by_id,
                )
            ], []

        lines = text.splitlines(keepends=True)
        if len(lines) <= 1:
            drafts, issues = self._split_node_units(
                [node],
                base_key=base_key,
                chunk_type="table",
                primary=node,
                document_title=document_title,
                node_by_id=node_by_id,
            )
            issues.append(
                self._issue(
                    "generation",
                    "TABLE_WITHOUT_ROW_BOUNDARY",
                    "review",
                    "超长表格缺少可用行边界，已按文本边界拆分",
                    node_id=node_id,
                    details={"char_count": len(text)},
                )
            )
            return drafts, issues

        spans: list[tuple[int, int]] = []
        cursor = 0
        for line in lines:
            spans.append((cursor, cursor + len(line)))
            cursor += len(line)
        header_start, header_end = spans[0]
        header_length = header_end - header_start
        body_spans = spans[1:]
        row_events: list[tuple[str, int, int]] = []
        group_start: int | None = None
        group_end: int | None = None
        group_length = header_length

        def flush_group() -> None:
            nonlocal group_start, group_end, group_length
            if group_start is not None and group_end is not None:
                row_events.append(("group", group_start, group_end))
            group_start = group_end = None
            group_length = header_length

        for start, end in body_spans:
            row_length = end - start
            if header_length + row_length > self.config.hard_max_chars:
                flush_group()
                row_events.append(("long", start, end))
                continue
            if group_start is not None and group_length + row_length > self.config.soft_max_chars:
                flush_group()
            if group_start is None:
                group_start = start
            group_end = end
            group_length += row_length
        flush_group()

        drafts: list[dict[str, Any]] = []
        header_covered = False
        available = max(1, self.config.hard_max_chars - header_length)
        for event_type, row_start, row_end in row_events:
            fragments = (
                [(row_start, row_end, "subspan")]
                if event_type == "group"
                else [
                    (row_start + local_start, row_start + local_end, mapping_type)
                    for local_start, local_end, mapping_type in self._split_text(
                        text[row_start:row_end], available
                    )
                ]
            )
            for fragment_start, fragment_end, mapping_type in fragments:
                header_role = "body" if not header_covered else "repeated_header"
                header_mapping = "exact" if not header_covered else "table_header"
                key = f"{base_key}:rows:{len(drafts) + 1:03d}"
                drafts.append(
                    self._draft_from_segments(
                        key,
                        "table",
                        "retrieval",
                        node,
                        [
                            (node, header_start, header_end, header_role, header_mapping),
                            (
                                node,
                                fragment_start,
                                fragment_end,
                                "body",
                                mapping_type,
                            ),
                        ],
                        document_title,
                        node_by_id,
                    )
                )
                header_covered = True

        if not drafts:
            fallback, fallback_issues = self._split_node_units(
                [node],
                base_key=base_key,
                chunk_type="table",
                primary=node,
                document_title=document_title,
                node_by_id=node_by_id,
            )
            drafts.extend(fallback)
        else:
            fallback_issues = []
        issues = [
            self._issue(
                "generation",
                "LARGE_TABLE_SPLIT",
                "review",
                "大表格已按完整行组拆分，并在子块中重复表头",
                node_id=node_id,
                chunk_key=drafts[0]["chunk_key"] if drafts else None,
                details={
                    "char_count": len(text),
                    "chunk_count": len(drafts),
                    "chunk_keys": [draft["chunk_key"] for draft in drafts],
                },
            )
        ] + fallback_issues
        return drafts, issues

    def _draft_from_nodes(
        self,
        chunk_key: str,
        chunk_type: str,
        chunk_role: str,
        primary: dict[str, Any],
        nodes: list[dict[str, Any]],
        document_title: str,
        node_by_id: dict[int, dict[str, Any]],
        *,
        parent_key: str | None = None,
        contribution_role: str = "body",
        mapping_type: str = "exact",
    ) -> dict[str, Any]:
        return self._draft_from_segments(
            chunk_key,
            chunk_type,
            chunk_role,
            primary,
            [
                (node, 0, len(str(node["raw_text"])), contribution_role, mapping_type)
                for node in nodes
            ],
            document_title,
            node_by_id,
            parent_key=parent_key,
        )

    def _draft_from_segments(
        self,
        chunk_key: str,
        chunk_type: str,
        chunk_role: str,
        primary: dict[str, Any],
        segments: list[tuple[dict[str, Any], int, int, str, str]],
        document_title: str,
        node_by_id: dict[int, dict[str, Any]],
        *,
        parent_key: str | None = None,
    ) -> dict[str, Any]:
        raw_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        cursor = 0
        previous = ""
        for order, (node, start, end, role, mapping_type) in enumerate(segments, start=1):
            source_text = str(node["raw_text"])[start:end]
            separator = "" if not raw_parts or previous.endswith("\n") or source_text.startswith("\n") else "\n"
            if separator:
                raw_parts.append(separator)
                cursor += len(separator)
            chunk_start = cursor
            raw_parts.append(source_text)
            cursor += len(source_text)
            sources.append(
                {
                    "node_id": int(node["id"]),
                    "source_order": order,
                    "contribution_role": role,
                    "node_char_start": start,
                    "node_char_end": end,
                    "chunk_char_start": chunk_start,
                    "chunk_char_end": cursor,
                    "mapping_type": mapping_type,
                    "source_text_hash": _sha256(source_text),
                    "is_primary": int(node["id"] == primary["id"] and role == "body"),
                }
            )
            previous = source_text
        raw_text = "".join(raw_parts)
        path_text = self._path_text(primary, node_by_id)
        prefix_text = f"【制度】{document_title}\n【路径】{path_text or '正文'}"
        retrieval_text = f"{prefix_text}\n【正文】\n{raw_text}"
        pages = [
            value
            for node, *_ in segments
            for value in (node.get("page_start"), node.get("page_end"))
            if value is not None
        ]
        return {
            "chunk_key": chunk_key,
            "primary_node_id": int(primary["id"]),
            "parent_key": parent_key,
            "chunk_type": chunk_type,
            "chunk_role": chunk_role,
            "path_text": path_text,
            "title_text": self._node_label(primary),
            "prefix_text": prefix_text,
            "raw_text": raw_text,
            "retrieval_text": retrieval_text,
            "page_start": min(pages) if pages else None,
            "page_end": max(pages) if pages else None,
            "is_retrievable": int(chunk_role == "retrieval"),
            "sources": sources,
        }

    @staticmethod
    def _node_label(node: dict[str, Any]) -> str:
        number = str(node.get("node_number") or "").strip()
        title = str(node.get("title") or "").strip()
        if number or title:
            return " ".join(part for part in (number, title) if part)
        if node["node_type"] == "table":
            return "表格"
        return str(node.get("content") or node.get("raw_text") or "")[:40].strip()

    def _path_text(
        self, node: dict[str, Any], node_by_id: dict[int, dict[str, Any]]
    ) -> str:
        chain: list[dict[str, Any]] = []
        current: dict[str, Any] | None = node
        seen: set[int] = set()
        while current is not None:
            current_id = int(current["id"])
            if current_id in seen:
                break
            seen.add(current_id)
            if current["node_type"] in CONTEXT_TYPES | {"article", "item"}:
                chain.append(current)
            parent_id = current.get("parent_id")
            current = node_by_id.get(int(parent_id)) if parent_id is not None else None
        labels = [self._node_label(item) for item in reversed(chain)]
        rendered = " > ".join(label for label in labels if label)
        if rendered:
            return rendered
        return {
            "preamble": "前言",
            "paragraph": "正文",
            "table": "表格",
        }.get(str(node["node_type"]), "正文")

    def _insert_drafts(self, chunk_run_id: int, drafts: list[dict[str, Any]]) -> dict[str, int]:
        chunk_ids: dict[str, int] = {}
        now = utc_now()
        with self.db.transaction():
            for index, draft in enumerate(drafts, start=1):
                raw_text = draft["raw_text"]
                retrieval_text = draft["retrieval_text"]
                cursor = self.db.repository.run(sql_text("""
                    INSERT INTO policy_chunk (
                        chunk_run_id, chunk_key, primary_node_id, chunk_type,
                        chunk_role, chunk_index, path_text, title_text, prefix_text,
                        raw_text, retrieval_text, char_count, retrieval_char_count,
                        token_count, page_start, page_end, is_retrievable,
                        raw_text_hash, retrieval_text_hash, template_version,
                        review_status, created_at
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, NULL, :p13, :p14, :p15, :p16, :p17, :p18, 'confirmed', :p19) RETURNING id"""), {'p0': chunk_run_id, 'p1': draft["chunk_key"], 'p2': draft["primary_node_id"], 'p3': draft["chunk_type"], 'p4': draft["chunk_role"], 'p5': index, 'p6': draft["path_text"], 'p7': draft["title_text"], 'p8': draft["prefix_text"], 'p9': raw_text, 'p10': retrieval_text, 'p11': len(raw_text), 'p12': len(retrieval_text), 'p13': draft["page_start"], 'p14': draft["page_end"], 'p15': draft["is_retrievable"], 'p16': _sha256(raw_text), 'p17': _sha256(retrieval_text), 'p18': self.config.retrieval_template_version, 'p19': now})
                chunk_id = int(cursor.scalar_one())
                chunk_ids[draft["chunk_key"]] = chunk_id
                for source in draft["sources"]:
                    self.db.repository.run(sql_text("""
                        INSERT INTO chunk_source_node (
                            chunk_id, node_id, source_order, contribution_role,
                            node_char_start, node_char_end, chunk_char_start,
                            chunk_char_end, mapping_type, source_text_hash, is_primary
                        ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10) RETURNING id"""), {'p0': chunk_id, 'p1': source["node_id"], 'p2': source["source_order"], 'p3': source["contribution_role"], 'p4': source["node_char_start"], 'p5': source["node_char_end"], 'p6': source["chunk_char_start"], 'p7': source["chunk_char_end"], 'p8': source["mapping_type"], 'p9': source["source_text_hash"], 'p10': source["is_primary"]})
            for draft in drafts:
                if draft["parent_key"]:
                    self.db.repository.run(sql_text('UPDATE policy_chunk SET parent_chunk_id=:p0 WHERE id=:p1'), {'p0': chunk_ids[draft["parent_key"]], 'p1': chunk_ids[draft["chunk_key"]]})
        return chunk_ids

    def _validate_run(
        self,
        chunk_run_id: int,
        parse_run_id: int,
        eligible: dict[int, dict[str, Any]],
        source_scope: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        chunks = [
            dict(row)
            for row in self.db.repository.run(sql_text('SELECT * FROM policy_chunk WHERE chunk_run_id=:p0 ORDER BY chunk_index'), {'p0': chunk_run_id}).mappings()
        ]
        source_rows = [
            dict(row)
            for row in self.db.repository.run(sql_text("""
                SELECT csn.*, pc.chunk_key, pc.chunk_run_id, pc.raw_text AS chunk_raw_text,
                       pc.prefix_text AS chunk_prefix_text, pc.is_retrievable,
                       pn.raw_text AS node_raw_text,
                       pn.node_type AS node_type,
                       pn.parse_run_id AS node_parse_run_id
                FROM chunk_source_node csn
                JOIN policy_chunk pc ON pc.id=csn.chunk_id
                JOIN policy_node pn ON pn.id=csn.node_id
                WHERE pc.chunk_run_id=:p0
                ORDER BY csn.chunk_id, csn.source_order, csn.id
                """), {'p0': chunk_run_id}).mappings()
        ]
        sources_by_chunk: dict[int, list[dict[str, Any]]] = defaultdict(list)
        body_intervals: dict[int, list[tuple[int, int]]] = defaultdict(list)
        retrieval_intervals: dict[int, list[tuple[int, int]]] = defaultdict(list)
        overlap_chars = 0
        issues: list[dict[str, Any]] = []
        for source in source_rows:
            sources_by_chunk[int(source["chunk_id"])].append(source)
            start = source["node_char_start"]
            end = source["node_char_end"]
            chunk_start = source["chunk_char_start"]
            chunk_end = source["chunk_char_end"]
            node_text = str(source["node_raw_text"])
            chunk_text = str(source["chunk_raw_text"])
            node_span_invalid = (
                start is None
                or end is None
                or not (0 <= int(start) <= int(end) <= len(node_text))
            )
            prefix_context = (
                source["contribution_role"] in {"title_context", "path_context"}
                and chunk_start is None
                and chunk_end is None
            )
            chunk_span_invalid = (
                not prefix_context
                and (
                    chunk_start is None
                    or chunk_end is None
                    or not (0 <= int(chunk_start) <= int(chunk_end) <= len(chunk_text))
                )
            )
            invalid = node_span_invalid or chunk_span_invalid
            if invalid:
                issues.append(
                    self._issue(
                        "lineage",
                        "INVALID_SOURCE_SPAN",
                        "error",
                        "来源 Node 或 Chunk 字符区间非法",
                        node_id=int(source["node_id"]),
                        chunk_key=source["chunk_key"],
                    )
                )
                continue
            node_slice = node_text[int(start) : int(end)]
            chunk_slice = (
                None
                if prefix_context
                else chunk_text[int(chunk_start) : int(chunk_end)]
            )
            if int(source["node_parse_run_id"]) != parse_run_id:
                issues.append(
                    self._issue(
                        "lineage",
                        "CROSS_PARSE_SOURCE",
                        "error",
                        "Chunk 引用了其他 ParseRun 的 Node",
                        node_id=int(source["node_id"]),
                        chunk_key=source["chunk_key"],
                    )
                )
            if _sha256(node_slice) != source["source_text_hash"] or (
                chunk_slice is not None and node_slice != chunk_slice
            ):
                issues.append(
                    self._issue(
                        "fidelity",
                        "SOURCE_TEXT_MISMATCH",
                        "error",
                        "来源片段、哈希或 Chunk 片段不一致",
                        node_id=int(source["node_id"]),
                        chunk_key=source["chunk_key"],
                    )
                )
            if (
                source["contribution_role"] == "title_context"
                and node_slice.strip() not in str(source["chunk_prefix_text"])
            ):
                issues.append(
                    self._issue(
                        "fidelity",
                        "PREFIX_CONTEXT_MISMATCH",
                        "error",
                        "title_context 来源文本未写入 Chunk 前缀",
                        node_id=int(source["node_id"]),
                        chunk_key=source["chunk_key"],
                    )
                )
            if source["contribution_role"] == "body":
                body_intervals[int(source["node_id"])].append((int(start), int(end)))
                if int(source["is_retrievable"]):
                    retrieval_intervals[int(source["node_id"])].append((int(start), int(end)))
            if source["mapping_type"] == "overlap":
                overlap_chars += int(end) - int(start)

        parent_by_id = {
            int(chunk["id"]): int(chunk["parent_chunk_id"])
            if chunk["parent_chunk_id"] is not None
            else None
            for chunk in chunks
        }
        chunk_ids = set(parent_by_id)
        for chunk in chunks:
            chunk_id = int(chunk["id"])
            chunk_sources = sources_by_chunk.get(chunk_id, [])
            raw_text = str(chunk["raw_text"])
            expected_retrieval = f"{chunk['prefix_text']}\n【正文】\n{raw_text}"
            if (
                _sha256(raw_text) != chunk["raw_text_hash"]
                or _sha256(str(chunk["retrieval_text"])) != chunk["retrieval_text_hash"]
                or str(chunk["retrieval_text"]) != expected_retrieval
                or int(chunk["char_count"]) != len(raw_text)
                or int(chunk["retrieval_char_count"]) != len(str(chunk["retrieval_text"]))
            ):
                issues.append(
                    self._issue(
                        "fidelity",
                        "CHUNK_TEXT_HASH_MISMATCH",
                        "error",
                        "Chunk 正文、检索模板、字符数或哈希不一致",
                        chunk_key=chunk["chunk_key"],
                    )
                )
            mapped_chunk_intervals = _merge_intervals(
                (
                    (int(source["chunk_char_start"]), int(source["chunk_char_end"]))
                    for source in chunk_sources
                    if source["chunk_char_start"] is not None and source["chunk_char_end"] is not None
                )
            )
            mapped_positions = [False] * len(raw_text)
            for start, end in mapped_chunk_intervals:
                for position in range(start, min(end, len(mapped_positions))):
                    mapped_positions[position] = True
            if any(not mapped_positions[index] and not char.isspace() for index, char in enumerate(raw_text)):
                issues.append(
                    self._issue(
                        "fidelity",
                        "UNMAPPED_CHUNK_TEXT",
                        "error",
                        "Chunk 正文存在无法追溯到来源 Node 的非空白字符",
                        chunk_key=chunk["chunk_key"],
                    )
                )
            if int(chunk["is_retrievable"]) and not raw_text.strip():
                issues.append(self._issue("generation", "EMPTY_RETRIEVAL_CHUNK", "error", "可检索 Chunk 正文为空", chunk_key=chunk["chunk_key"]))
            if int(chunk["is_retrievable"]) and int(chunk["char_count"]) > self.config.hard_max_chars:
                issues.append(
                    self._issue(
                        "structure",
                        "HARD_LIMIT_EXCEEDED",
                        "error",
                        "可检索 Chunk 超过硬上限",
                        chunk_key=chunk["chunk_key"],
                        details={"char_count": chunk["char_count"], "hard_max_chars": self.config.hard_max_chars},
                    )
                )
            if int(chunk["is_retrievable"]) and not any(source["contribution_role"] == "body" for source in chunk_sources):
                issues.append(self._issue("lineage", "MISSING_BODY_SOURCE", "error", "可检索 Chunk 没有正文来源映射", chunk_key=chunk["chunk_key"]))
            if chunk["page_start"] is not None and chunk["page_end"] is not None and int(chunk["page_start"]) > int(chunk["page_end"]):
                issues.append(self._issue("lineage", "INVALID_PAGE_RANGE", "error", "Chunk 起始页大于结束页", chunk_key=chunk["chunk_key"]))
            if not chunk["path_text"]:
                issues.append(self._issue("structure", "MISSING_PATH_CONTEXT", "review", "可检索 Chunk 缺少结构路径", chunk_key=chunk["chunk_key"]))
            primary = int(chunk["primary_node_id"]) if chunk["primary_node_id"] is not None else None
            primary_node = eligible.get(primary) if primary is not None else None
            primary_node_type = str(primary_node["node_type"]) if primary_node else None
            if primary_node_type is None and primary is not None:
                primary_node_type = next(
                    (
                        str(source["node_type"])
                        for source in chunk_sources
                        if int(source["node_id"]) == primary
                    ),
                    None,
                )
            raw_length = len(raw_text.strip())
            short_details = {
                "char_count": raw_length,
                "primary_node_id": primary,
                "node_type": primary_node_type,
            }
            if int(chunk["is_retrievable"]) and raw_length <= 5:
                issues.append(self._issue("structure", "EXTREMELY_SHORT_CHUNK", "review", "Chunk 极短，需要确认是否具有独立制度含义", node_id=primary, chunk_key=chunk["chunk_key"], details=short_details))
            elif int(chunk["is_retrievable"]) and raw_length < self.config.min_retrieval_chars:
                issues.append(self._issue("structure", "SHORT_CHUNK", "warning", "Chunk 短于建议长度，已保留原文", node_id=primary, chunk_key=chunk["chunk_key"], details=short_details))
            if primary is not None and int(chunk["is_retrievable"]) and not any(
                int(source["node_id"]) == primary and source["contribution_role"] == "body"
                for source in chunk_sources
            ):
                issues.append(self._issue("lineage", "PRIMARY_SOURCE_MISMATCH", "error", "primary_node_id 没有对应正文映射", node_id=primary, chunk_key=chunk["chunk_key"]))
            parent_id = parent_by_id[chunk_id]
            if parent_id is not None and parent_id not in chunk_ids:
                issues.append(self._issue("structure", "CROSS_RUN_PARENT", "error", "父 Chunk 不属于当前运行", chunk_key=chunk["chunk_key"]))
            seen: set[int] = set()
            cursor = chunk_id
            while cursor is not None:
                if cursor in seen:
                    issues.append(self._issue("structure", "PARENT_CYCLE", "error", "Chunk 父子关系形成循环", chunk_key=chunk["chunk_key"]))
                    break
                seen.add(cursor)
                cursor = parent_by_id.get(cursor)

        hashes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in chunks:
            if int(chunk["is_retrievable"]):
                hashes[str(chunk["raw_text_hash"])].append(chunk)
        duplicates = [group for group in hashes.values() if len(group) > 1]
        duplicate_count = sum(len(group) - 1 for group in duplicates)
        duplicate_chars = sum(
            int(item["char_count"]) for group in duplicates for item in group[1:]
        )
        for group in duplicates:
            issues.append(
                self._issue(
                    "fidelity",
                    "EXACT_DUPLICATE_RETRIEVAL",
                    "review",
                    "发现正文完全重复的可检索 Chunk",
                    chunk_key=group[0]["chunk_key"],
                    details={"chunk_keys": [item["chunk_key"] for item in group]},
                )
            )

        total_chars = sum(len(str(node["raw_text"])) for node in eligible.values())
        covered_chars = 0
        retrieval_chars = 0
        mapped_nodes = 0
        for node_id, node in eligible.items():
            merged = _merge_intervals(body_intervals.get(node_id, []))
            retrieved = _merge_intervals(retrieval_intervals.get(node_id, []))
            covered_chars += sum(end - start for start, end in merged)
            retrieval_chars += sum(end - start for start, end in retrieved)
            if merged:
                mapped_nodes += 1
            else:
                issues.append(
                    self._issue(
                        "coverage",
                        "ELIGIBLE_NODE_OMITTED",
                        "error",
                        "合格正文 Node 未进入任何 Chunk",
                        node_id=node_id,
                        details={"node_type": node["node_type"], "order_no": node["order_no"]},
                    )
                )

        if source_scope == "experimental":
            issues.append(
                self._issue(
                    "generation",
                    "EXPERIMENTAL_PARSE_SOURCE",
                    "review",
                    "ChunkRun 基于未激活 ParseRun，仅可用于实验",
                    details={"parse_run_id": parse_run_id},
                )
            )
        missing_pages = sum(1 for chunk in chunks if chunk["page_start"] is None)
        if missing_pages:
            issues.append(
                self._issue(
                    "lineage",
                    "PAGE_MAPPING_MISSING",
                    "warning",
                    "部分 Chunk 没有页码，但来源 Node 映射仍保留",
                    details={"chunk_count": missing_pages},
                )
            )

        chunk_count = len(chunks)
        retrievable_count = sum(int(chunk["is_retrievable"]) for chunk in chunks)
        metrics = {
            "chunk_count": chunk_count,
            "retrievable_count": retrievable_count,
            "context_count": chunk_count - retrievable_count,
            "eligible_node_count": len(eligible),
            "mapped_node_count": mapped_nodes,
            "eligible_node_coverage": mapped_nodes / len(eligible) if eligible else 1.0,
            "eligible_character_coverage": covered_chars / total_chars if total_chars else 1.0,
            "retrievable_character_coverage": retrieval_chars / total_chars if total_chars else 1.0,
            "unmapped_node_count": len(eligible) - mapped_nodes,
            "duplicate_count": duplicate_count,
            "duplicate_body_character_count": duplicate_chars,
            "allowed_overlap_character_count": overlap_chars,
        }
        return issues, metrics

    @staticmethod
    def _issue(
        stage: str,
        issue_code: str,
        severity: str,
        message: str,
        *,
        node_id: int | None = None,
        chunk_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "issue_code": issue_code,
            "severity": severity,
            "message": message,
            "node_id": node_id,
            "chunk_key": chunk_key,
            "details": details or {},
        }

    def _insert_issues(
        self,
        chunk_run_id: int,
        issues: list[dict[str, Any]],
        chunk_ids: dict[str, int],
    ) -> None:
        now = utc_now()
        with self.db.transaction():
            for issue in issues:
                details = dict(issue.get("details") or {})
                if issue.get("chunk_key"):
                    details.setdefault("chunk_key", issue["chunk_key"])
                self.db.repository.run(sql_text("""
                    INSERT INTO chunk_validation_issue (
                        chunk_run_id, chunk_id, node_id, stage, issue_code,
                        severity, message, details_json, created_at
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8) RETURNING id"""), {'p0': chunk_run_id, 'p1': chunk_ids.get(issue.get("chunk_key")), 'p2': issue.get("node_id"), 'p3': issue["stage"], 'p4': issue["issue_code"], 'p5': issue["severity"], 'p6': issue["message"], 'p7': json.dumps(details, ensure_ascii=False, sort_keys=True), 'p8': now})

    def _issue_counts(self, chunk_run_id: int) -> dict[str, int]:
        result = {"error": 0, "review": 0, "warning": 0}
        for row in self.db.repository.run(sql_text('SELECT severity, COUNT(*) AS n FROM chunk_validation_issue WHERE chunk_run_id=:p0 GROUP BY severity'), {'p0': chunk_run_id}).mappings():
            result[str(row["severity"])] = int(row["n"])
        return result

    def _update_chunk_run(self, chunk_run_id: int, **fields: Any) -> None:
        if not fields:
            return
        table = knowledge_metadata.tables["chunk_run"]
        self.db.repository.run(update(table).where(table.c.id == chunk_run_id).values(**fields))
        self.db.repository.save()

    def activate_run_if_ready(self, chunk_run_id: int) -> bool:
        """满足正式激活条件时原子切换 active_chunk_run_id。"""

        row = self.db.repository.run(sql_text("""
            SELECT cr.*, pd.active_parse_run_id
            FROM chunk_run cr
            JOIN policy_document pd ON pd.id=cr.document_id
            WHERE cr.id=:p0
            """), {'p0': chunk_run_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"ChunkRun 不存在：{chunk_run_id}")
        unresolved = int(
            self.db.repository.run(sql_text("""
                SELECT COUNT(*) FROM chunk_validation_issue
                WHERE chunk_run_id=:p0 AND resolved=0 AND severity IN ('error','review')
                """), {'p0': chunk_run_id}).scalar_one()
        )
        ready = (
            row["source_scope"] == "active"
            and row["status"] == "succeeded"
            and row["review_status"] == "approved"
            and row["active_parse_run_id"] is not None
            and int(row["active_parse_run_id"]) == int(row["parse_run_id"])
            and unresolved == 0
            and int(row["unmapped_node_count"] or 0) == 0
        )
        if not ready:
            return False
        with self.db.transaction():
            current = self.db.repository.run(sql_text('SELECT active_parse_run_id FROM policy_document WHERE id=:p0'), {'p0': int(row["document_id"])}).mappings().fetchone()
            if current is None or int(current["active_parse_run_id"]) != int(row["parse_run_id"]):
                raise ValueError("激活过程中 active_parse_run_id 已变化，请重新生成 Chunk")
            self.db.repository.run(sql_text('UPDATE policy_document SET active_chunk_run_id=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': chunk_run_id, 'p1': utc_now(), 'p2': int(row["document_id"])})
        return True

    def run_summary(self, chunk_run_id: int) -> dict[str, Any]:
        row = self.db.repository.run(sql_text("""
            SELECT cr.*, pd.file_name, pd.title,
                   pd.latest_chunk_run_id, pd.active_chunk_run_id,
                   (SELECT COUNT(*) FROM chunk_validation_issue cvi
                    WHERE cvi.chunk_run_id=cr.id AND cvi.severity='error') AS error_count,
                   (SELECT COUNT(*) FROM chunk_validation_issue cvi
                    WHERE cvi.chunk_run_id=cr.id AND cvi.severity='review') AS review_count,
                   (SELECT COUNT(*) FROM chunk_validation_issue cvi
                    WHERE cvi.chunk_run_id=cr.id AND cvi.severity='warning') AS warning_count
            FROM chunk_run cr
            JOIN policy_document pd ON pd.id=cr.document_id
            WHERE cr.id=:p0
            """), {'p0': chunk_run_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"ChunkRun 不存在：{chunk_run_id}")
        return dict(row)
