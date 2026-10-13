"""文件说明：PostgreSQL解析Core仓储。

该文件读写解析设计文档中定义的 Document、ParseRun、SourceBlock、
Node、Chunk、来源映射、字段候选和校验问题，所有文本均按 UTF-8 语义处理。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import json
from knowledge.storage.repository import CoreRepository
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


def utc_now() -> str:
    """返回带时区的 ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ParserDatabase:
    """解析结果仓储；建表由Knowledge独立Alembic负责。"""

    def __init__(self, url: str) -> None:
        self.repository = CoreRepository(url)

    def close(self) -> None:
        self.repository.close()

    def __enter__(self) -> "ParserDatabase":
        """支持在服务和迁移中明确限定数据库连接生命周期。"""

        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[CoreRepository]:
        """将一个解析阶段包装成事务，失败时只回滚当前阶段。"""

        try:
            yield self.repository
            self.repository.save()
        except Exception:
            self.repository.discard()
            raise


    def get_or_create_document(self, data: dict[str, Any]) -> int:
        row = self.repository.run(sql_text('SELECT id FROM policy_document WHERE checksum = :p0'), {'p0': data["checksum"]}).mappings().fetchone()
        now = utc_now()
        if row:
            document_id = int(row["id"])
            self.repository.run(sql_text("""
                UPDATE policy_document
                SET source_file=:p0, file_name=:p1, file_size=:p2, parser_status='queued',
                    review_status='pending', updated_at=:p3
                WHERE id=:p4
                """), {'p0': data["source_file"], 'p1': data["file_name"], 'p2': data["file_size"], 'p3': now, 'p4': document_id})
            self.ensure_document_series(document_id)
            self.repository.save()
            return document_id

        cursor = self.repository.run(sql_text("""
            INSERT INTO policy_document (
                source_file, file_name, file_type, mime_type, file_size,
                parser_status, review_status, checksum, created_at, updated_at
            ) VALUES (:p0, :p1, 'docx', :p2, :p3, 'queued', 'pending', :p4, :p5, :p6) RETURNING id"""), {'p0': data["source_file"], 'p1': data["file_name"], 'p2': data["mime_type"], 'p3': data["file_size"], 'p4': data["checksum"], 'p5': now, 'p6': now})
        document_id = int(cursor.scalar_one())
        self.ensure_document_series(document_id)
        self.repository.save()
        return document_id

    def ensure_document_series(self, document_id: int) -> int:
        """在正常建档流程中为正式文件版本建立默认制度系列。"""

        document = self.repository.run(sql_text('SELECT id,series_id,title,file_name FROM policy_document WHERE id=:p0'), {'p0': document_id}).mappings().fetchone()
        if document is None:
            raise LookupError(f"Document 不存在：{document_id}")
        if document["series_id"] is not None:
            return int(document["series_id"])
        now = utc_now()
        cursor = self.repository.run(sql_text("""
            INSERT INTO policy_series (series_key,canonical_title,status,created_at,updated_at)
            VALUES (:p0,:p1,'ACTIVE',:p2,:p3) RETURNING id"""), {'p0': f"policy-series-{document_id}", 'p1': str(document["title"] or document["file_name"] or f"制度{document_id}"), 'p2': now, 'p3': now})
        series_id = int(cursor.scalar_one())
        self.repository.run(sql_text('UPDATE policy_document SET series_id=:p0,document_version_no=1 WHERE id=:p1'), {'p0': series_id, 'p1': document_id})
        return series_id

    def create_parse_run(
        self, document_id: int, parser_version: str, config_hash: str
    ) -> int:
        cursor = self.repository.run(sql_text("""
            INSERT INTO parse_run (
                document_id, parser_version, config_hash, status,
                current_stage, started_at
            ) VALUES (:p0, :p1, :p2, 'running', 'file_validation', :p3) RETURNING id"""), {'p0': document_id, 'p1': parser_version, 'p2': config_hash, 'p3': utc_now()})
        run_id = int(cursor.scalar_one())
        self.repository.run(sql_text("UPDATE policy_document SET parser_status='running', updated_at=:p0 WHERE id=:p1"), {'p0': utc_now(), 'p1': document_id})
        self.repository.save()
        return run_id

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        table = knowledge_metadata.tables["parse_run"]
        self.repository.run(update(table).where(table.c.id == run_id).values(**fields))
        self.repository.save()

    def update_document(self, document_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        table = knowledge_metadata.tables["policy_document"]
        self.repository.run(update(table).where(table.c.id == document_id).values(**fields))
        self.repository.save()

    def insert_blocks(self, run_id: int, blocks: list[dict[str, Any]]) -> dict[str, int]:
        key_to_id: dict[str, int] = {}
        with self.transaction():
            for block in blocks:
                cursor = self.repository.run(sql_text("""
                    INSERT INTO source_block (
                        parse_run_id, temp_key, parent_temp_key, part_type, block_type,
                        order_no, raw_text, clean_text, style_name, numbering_id,
                        numbering_level, display_number, properties_json,
                        source_locator_json, excluded_role, exclusion_reason,
                        normalization_actions_json
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14, :p15, :p16) RETURNING id"""), {'p0': run_id, 'p1': block["temp_key"], 'p2': block.get("parent_temp_key"), 'p3': block["part_type"], 'p4': block["block_type"], 'p5': block["order_no"], 'p6': block["raw_text"], 'p7': block["clean_text"], 'p8': block.get("style_name"), 'p9': block.get("numbering_id"), 'p10': block.get("numbering_level"), 'p11': block.get("display_number"), 'p12': json.dumps(block.get("properties", {}), ensure_ascii=False), 'p13': json.dumps(block.get("source_locator", {}), ensure_ascii=False), 'p14': block.get("excluded_role", "none"), 'p15': block.get("exclusion_reason"), 'p16': json.dumps(block.get("normalization_actions", []), ensure_ascii=False)})
                key_to_id[block["temp_key"]] = int(cursor.scalar_one())

            for block in blocks:
                parent_key = block.get("parent_temp_key")
                if parent_key and parent_key in key_to_id:
                    self.repository.run(sql_text('UPDATE source_block SET parent_block_id=:p0 WHERE id=:p1'), {'p0': key_to_id[parent_key], 'p1': key_to_id[block["temp_key"]]})
        return key_to_id

    def insert_nodes(
        self,
        document_id: int,
        run_id: int,
        nodes: list[dict[str, Any]],
        block_ids: dict[str, int],
    ) -> tuple[dict[str, int], dict[str, int]]:
        key_to_id: dict[str, int] = {}
        block_to_node: dict[str, int] = {}
        now = utc_now()
        with self.transaction():
            for node in nodes:
                cursor = self.repository.run(sql_text("""
                    INSERT INTO policy_node (
                        document_id, parse_run_id, temp_key, parent_temp_key,
                        node_type, node_number, title, raw_text, content,
                        normalized_content, level, path, path_text, order_no,
                        effect_status_candidate, parser_confidence, decision_method,
                        rule_id, candidate_types, review_status, review_reason,
                        created_at, updated_at
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14, :p15, :p16, :p17, :p18, :p19, :p20, :p21, :p22) RETURNING id"""), {'p0': document_id, 'p1': run_id, 'p2': node["temp_key"], 'p3': node.get("parent_temp_key"), 'p4': node["node_type"], 'p5': node.get("node_number"), 'p6': node.get("title"), 'p7': node["raw_text"], 'p8': node.get("content"), 'p9': node.get("normalized_content"), 'p10': node["level"], 'p11': node.get("path"), 'p12': node.get("path_text"), 'p13': node["order_no"], 'p14': node.get("effect_status_candidate"), 'p15': node["parser_confidence"], 'p16': node["decision_method"], 'p17': node.get("rule_id"), 'p18': json.dumps(node.get("candidate_types", []), ensure_ascii=False), 'p19': node.get("review_status", "pending"), 'p20': node.get("review_reason"), 'p21': now, 'p22': now})
                node_id = int(cursor.scalar_one())
                key_to_id[node["temp_key"]] = node_id
                block_to_node[node["source_block_key"]] = node_id
                block_id = block_ids[node["source_block_key"]]
                self.repository.run(sql_text("""
                    INSERT INTO node_source_span (
                        node_id, source_block_id, char_start, char_end, mapping_type
                    ) VALUES (:p0, :p1, 0, :p2, 'exact') RETURNING id"""), {'p0': node_id, 'p1': block_id, 'p2': len(node["raw_text"])})

            for node in nodes:
                parent_key = node.get("parent_temp_key")
                if parent_key and parent_key in key_to_id:
                    self.repository.run(sql_text('UPDATE policy_node SET parent_id=:p0 WHERE id=:p1'), {'p0': key_to_id[parent_key], 'p1': key_to_id[node["temp_key"]]})
        return key_to_id, block_to_node

    def insert_fields(
        self,
        run_id: int,
        fields: Iterable[dict[str, Any]],
        block_ids: dict[str, int],
        block_to_node: dict[str, int],
    ) -> None:
        with self.transaction():
            for field in fields:
                block_key = field.get("source_block_key")
                self.repository.run(sql_text("""
                    INSERT INTO extracted_field (
                        parse_run_id, field_name, raw_value, normalized_value,
                        source_block_id, source_node_id, confidence,
                        decision_method, rule_id, review_status
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9) RETURNING id"""), {'p0': run_id, 'p1': field["field_name"], 'p2': field["raw_value"], 'p3': field.get("normalized_value"), 'p4': block_ids.get(block_key) if block_key else None, 'p5': block_to_node.get(block_key) if block_key else None, 'p6': field["confidence"], 'p7': field["decision_method"], 'p8': field.get("rule_id"), 'p9': field.get("review_status", "pending")})

    def insert_issues(
        self,
        run_id: int,
        issues: Iterable[dict[str, Any]],
        block_ids: dict[str, int] | None = None,
        node_ids: dict[str, int] | None = None,
    ) -> None:
        block_ids = block_ids or {}
        node_ids = node_ids or {}
        with self.transaction():
            for issue in issues:
                self.repository.run(sql_text("""
                    INSERT INTO validation_issue (
                        parse_run_id, node_id, source_block_id, stage,
                        issue_code, severity, message, details_json
                    ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7) RETURNING id"""), {'p0': run_id, 'p1': node_ids.get(issue.get("node_key")), 'p2': block_ids.get(issue.get("source_block_key")), 'p3': issue["stage"], 'p4': issue["issue_code"], 'p5': issue["severity"], 'p6': issue["message"], 'p7': json.dumps(issue.get("details", {}), ensure_ascii=False)})

    def update_block_pages(self, mappings: dict[int, tuple[int | None, int | None, float]]) -> None:
        with self.transaction():
            self.repository.run(sql_text("""
                UPDATE source_block
                SET page_start=:p0, page_end=:p1, page_mapping_confidence=:p2,
                    page_mapping_method='pdf_text_alignment'
                WHERE id=:p3
                """), [dict(zip(('p0', 'p1', 'p2', 'p3'), row, strict=True)) for row in [
                    (page_start, page_end, confidence, block_id)
                    for block_id, (page_start, page_end, confidence) in mappings.items()
                ]])

    def inherit_child_block_pages(self, run_id: int) -> None:
        """正文文本框和图片继承宿主 Block 页码，并降低少量置信度。"""

        with self.transaction():
            self.repository.run(sql_text("""
                UPDATE source_block AS child
                SET page_start=(SELECT parent.page_start FROM source_block parent WHERE parent.id=child.parent_block_id),
                    page_end=(SELECT parent.page_end FROM source_block parent WHERE parent.id=child.parent_block_id),
                    page_mapping_confidence=(
                        SELECT CASE
                            WHEN parent.page_mapping_confidence IS NULL THEN NULL
                            ELSE parent.page_mapping_confidence * 0.95
                        END
                        FROM source_block parent WHERE parent.id=child.parent_block_id
                    ),
                    page_mapping_method='parent_anchor'
                WHERE child.parse_run_id=:p0
                  AND child.part_type='document'
                  AND child.block_type IN ('textbox', 'image')
                  AND child.parent_block_id IS NOT NULL
                  AND child.page_start IS NULL
                  AND EXISTS (
                      SELECT 1 FROM source_block parent
                      WHERE parent.id=child.parent_block_id AND parent.page_start IS NOT NULL
                  )
                """), {'p0': run_id})

    def update_node_pages(self, run_id: int) -> None:
        with self.transaction():
            self.repository.run(sql_text("""
                UPDATE policy_node
                SET page_start = (
                        SELECT MIN(sb.page_start)
                        FROM node_source_span nss
                        JOIN source_block sb ON sb.id=nss.source_block_id
                        WHERE nss.node_id=policy_node.id
                    ),
                    page_end = (
                        SELECT MAX(sb.page_end)
                        FROM node_source_span nss
                        JOIN source_block sb ON sb.id=nss.source_block_id
                        WHERE nss.node_id=policy_node.id
                    )
                WHERE parse_run_id=:p0
                """), {'p0': run_id})

    def run_summary(self, run_id: int) -> dict[str, Any]:
        row = self.repository.run(sql_text("""
            SELECT pr.*, pd.file_name, pd.title, pd.document_type,
                   (SELECT COUNT(*) FROM source_block WHERE parse_run_id=pr.id) AS block_count,
                   (SELECT COUNT(*) FROM policy_node WHERE parse_run_id=pr.id) AS node_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id) AS issue_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id AND severity='review') AS review_count,
                   (SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=pr.id AND severity='error') AS error_count
            FROM parse_run pr
            JOIN policy_document pd ON pd.id=pr.document_id
            WHERE pr.id=:p0
            """), {'p0': run_id}).mappings().fetchone()
        return dict(row) if row else {}
