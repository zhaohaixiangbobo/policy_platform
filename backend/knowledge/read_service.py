"""文件说明：以只读查询服务暴露审核详情、证据候选和索引状态。

Platform 应用层只依赖本服务，不直接拼接知识 SQLite 查询；所有文件路径均经过
知识数据根目录约束校验。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import json
from knowledge.storage.repository import CoreRepository
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from knowledge.config import KnowledgePaths
from knowledge.indexing.config import IndexConfig


class KnowledgeReadService:
    """知识管理读模型，为管理后台提供稳定的字典契约。"""

    def __init__(self, paths: KnowledgePaths) -> None:
        self.paths = paths

    @contextmanager
    def _connection(self) -> Iterator[CoreRepository]:
        with CoreRepository(self.paths.database_url) as connection:
            yield connection

    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def review_detail(self, target_type: str, run_id: int) -> dict[str, Any]:
        """返回ParseRun或ChunkRun的真实结构、问题、来源映射和质量指标。"""

        if target_type == "PARSE_RUN":
            return self._parse_detail(run_id)
        if target_type == "CHUNK_RUN":
            return self._chunk_detail(run_id)
        raise ValueError("未知审核对象类型")

    def _parse_detail(self, run_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            run = connection.run(sql_text("""
                SELECT pr.*, pd.title AS document_title, pd.document_code,
                       pd.issuing_org, pd.status AS document_status
                FROM parse_run pr JOIN policy_document pd ON pd.id=pr.document_id
                WHERE pr.id=:p0
                """), {'p0': run_id}).mappings().fetchone()
            if run is None:
                raise LookupError("ParseRun不存在")
            nodes = self._rows(
                connection.run(sql_text("""
                    SELECT id,parent_id,node_type,node_number,title,content AS text,
                           path_text,level,order_no,page_start,page_end,
                           parser_confidence,decision_method,rule_id,
                           review_status,review_reason
                    FROM policy_node WHERE parse_run_id=:p0 ORDER BY order_no,id
                    """), {'p0': run_id}).mappings()
            )
            fields = self._rows(
                connection.run(sql_text("""
                    SELECT id,field_name,raw_value,normalized_value,source_node_id,
                           confidence,decision_method,review_status
                    FROM extracted_field WHERE parse_run_id=:p0 ORDER BY id
                    """), {'p0': run_id}).mappings()
            )
            issues = self._rows(
                connection.run(sql_text("""
                    SELECT id,node_id,source_block_id,stage,issue_code,severity,
                           message,details_json,resolved
                    FROM validation_issue WHERE parse_run_id=:p0 ORDER BY resolved,severity,id
                    """), {'p0': run_id}).mappings()
            )
            for issue in issues:
                issue["details"] = self._json(issue.pop("details_json"), {})
                issue["issue_type"] = self._issue_type(str(issue["issue_code"]))
                issue["resolved"] = bool(issue["resolved"])
            block_counts = {
                str(row["block_type"]): int(row["count"])
                for row in connection.run(sql_text('SELECT block_type,COUNT(*) AS count FROM source_block WHERE parse_run_id=:p0 GROUP BY block_type'), {'p0': run_id}).mappings()
            }
            data = dict(run)
            return {
                "target_type": "PARSE_RUN",
                "run": data,
                "metrics": {
                    "node_count": len(nodes),
                    "source_block_count": sum(block_counts.values()),
                    "block_counts": block_counts,
                    "field_count": len(fields),
                    "issue_count": len(issues),
                    "open_issue_count": sum(1 for item in issues if not item["resolved"]),
                    "page_mapping_coverage": data.get("page_mapping_coverage"),
                    "character_coverage": data.get("character_coverage"),
                    "block_coverage": data.get("block_coverage"),
                    "table_cell_coverage": data.get("table_cell_coverage"),
                },
                "nodes": nodes,
                "fields": fields,
                "chunks": [],
                "issues": issues,
                "pdf_available": bool(data.get("pdf_path")),
            }

    def _chunk_detail(self, run_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            run = connection.run(sql_text("""
                SELECT cr.*, pd.title AS document_title, pd.document_code,
                       pd.status AS document_status
                FROM chunk_run cr JOIN policy_document pd ON pd.id=cr.document_id
                WHERE cr.id=:p0
                """), {'p0': run_id}).mappings().fetchone()
            if run is None:
                raise LookupError("ChunkRun不存在")
            chunks = self._rows(
                connection.run(sql_text("""
                    SELECT id,chunk_key,primary_node_id,parent_chunk_id,chunk_type,
                           chunk_role,chunk_index,path_text,title_text,prefix_text,
                           raw_text,retrieval_text,char_count,retrieval_char_count,
                           token_count,page_start,page_end,is_retrievable,review_status
                    FROM policy_chunk WHERE chunk_run_id=:p0 ORDER BY chunk_index,id
                    """), {'p0': run_id}).mappings()
            )
            source_rows = self._rows(
                connection.run(sql_text("""
                    SELECT csn.chunk_id,csn.node_id,csn.source_order,
                           csn.contribution_role,csn.mapping_type,csn.is_primary,
                           pn.path_text,pn.title,pn.node_type,pn.page_start,pn.page_end
                    FROM chunk_source_node csn
                    JOIN policy_chunk pc ON pc.id=csn.chunk_id
                    JOIN policy_node pn ON pn.id=csn.node_id
                    WHERE pc.chunk_run_id=:p0 ORDER BY csn.chunk_id,csn.source_order
                    """), {'p0': run_id}).mappings()
            )
            sources: dict[int, list[dict[str, Any]]] = {}
            for source in source_rows:
                source["is_primary"] = bool(source["is_primary"])
                sources.setdefault(int(source["chunk_id"]), []).append(source)
            for chunk in chunks:
                chunk["is_retrievable"] = bool(chunk["is_retrievable"])
                chunk["sources"] = sources.get(int(chunk["id"]), [])
            issues = self._rows(
                connection.run(sql_text("""
                    SELECT id,chunk_id,node_id,stage,issue_code,severity,message,
                           details_json,resolved
                    FROM chunk_validation_issue WHERE chunk_run_id=:p0
                    ORDER BY resolved,severity,id
                    """), {'p0': run_id}).mappings()
            )
            for issue in issues:
                issue["details"] = self._json(issue.pop("details_json"), {})
                issue["issue_type"] = self._issue_type(str(issue["issue_code"]))
                issue["resolved"] = bool(issue["resolved"])
            data = dict(run)
            return {
                "target_type": "CHUNK_RUN",
                "run": data,
                "metrics": {
                    key: data.get(key)
                    for key in (
                        "chunk_count", "retrievable_count", "context_count",
                        "eligible_node_count", "mapped_node_count",
                        "eligible_node_coverage", "eligible_character_coverage",
                        "retrievable_character_coverage", "unmapped_node_count",
                        "duplicate_count", "validation_issue_count",
                    )
                },
                "nodes": [],
                "fields": [],
                "chunks": chunks,
                "issues": issues,
                "pdf_available": False,
            }

    def resolve_parse_pdf(self, run_id: int) -> Path:
        """只解析指定ParseRun记录的受控PDF路径。"""

        with self._connection() as connection:
            row = connection.run(sql_text('SELECT pdf_path FROM parse_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
        if row is None or not row["pdf_path"]:
            raise LookupError("审核PDF不可用")
        path = (self.paths.data_root / str(row["pdf_path"])).resolve()
        if not path.is_relative_to(self.paths.pdf_documents.resolve()) or not path.is_file():
            raise LookupError("审核PDF不可用")
        return path

    def evidence_catalog(self, keyword: str | None = None) -> list[dict[str, Any]]:
        """列出当前已发布IndexRun中的制度和Node，作为关系/流程证据候选。"""

        with self._connection() as connection:
            sql = """
                SELECT d.id,m.title,m.document_code,m.status,
                       src.parse_run_id AS active_parse_run_id
                FROM policy_document d
                JOIN index_profile ip ON ip.profile_name=:profile
                JOIN index_run ir ON ir.id=ip.active_index_run_id
                JOIN index_run_source src ON src.index_run_id=ir.id AND src.document_id=d.id
                JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
                WHERE ir.status='succeeded' AND ir.activation_status='active'
            """
            parameters = {"profile": IndexConfig.from_environment().profile_name}
            if keyword and keyword.strip():
                sql += " AND (m.title LIKE :keyword OR COALESCE(m.document_code,'') LIKE :keyword)"
                value = f"%{keyword.strip()}%"
                parameters["keyword"] = value
            sql += " ORDER BY m.updated_at DESC,d.id DESC"
            documents = self._rows(connection.run(sql_text(sql), parameters).mappings())
            for document in documents:
                document["nodes"] = self._rows(
                    connection.run(sql_text("""
                        SELECT id,parent_id,node_type,node_number,title,
                               COALESCE(content,raw_text) AS text,path_text,
                               page_start,page_end,order_no
                        FROM policy_node WHERE parse_run_id=:p0 ORDER BY order_no,id
                        """), {'p0': int(document["active_parse_run_id"])}).mappings()
                )
            return documents

    def validate_evidence(
        self,
        document_id: int,
        parse_run_id: int,
        primary_node_id: int,
        quote_snapshot: str,
        snapshot_hash: str,
    ) -> tuple[str, str]:
        """按active版本、Node归属和快照哈希验证跨库引用。"""

        import hashlib

        try:
            with self._connection() as connection:
                document = connection.run(sql_text("""
                    SELECT src.parse_run_id AS active_parse_run_id
                    FROM index_profile ip
                    JOIN index_run ir ON ir.id=ip.active_index_run_id
                    JOIN index_run_source src ON src.index_run_id=ir.id
                    WHERE ip.profile_name=:p0 AND ir.status='succeeded'
                      AND ir.activation_status='active' AND src.document_id=:p1
                    """), {'p0': IndexConfig.from_environment().profile_name, 'p1': document_id}).mappings().fetchone()
                if document is None:
                    return "MISSING", "制度不存在"
                if document["active_parse_run_id"] is None or int(document["active_parse_run_id"]) != parse_run_id:
                    return "STALE", "active ParseRun已经变化"
                node = connection.run(sql_text('SELECT document_id,parse_run_id,COALESCE(content,raw_text) AS text FROM policy_node WHERE id=:p0'), {'p0': primary_node_id}).mappings().fetchone()
                if node is None:
                    return "MISSING", "证据Node不存在"
                if int(node["document_id"]) != document_id or int(node["parse_run_id"]) != parse_run_id:
                    return "MISMATCH", "证据Node与版本标识不一致"
                expected = hashlib.sha256(quote_snapshot.encode("utf-8")).hexdigest()
                if snapshot_hash.removeprefix("sha256:") != expected:
                    return "MISMATCH", "证据快照哈希不一致"
                if quote_snapshot.strip() not in str(node["text"]):
                    return "MISMATCH", "证据原文已变化"
                return "VALID", "证据引用有效"
        except (LookupError, SQLAlchemyError):
            return "UNAVAILABLE", "知识数据库暂不可读"

    def validate_document_version(self, document_id: int, parse_run_id: int) -> tuple[str, str]:
        """验证制度与ParseRun仍是当前active版本。"""

        try:
            with self._connection() as connection:
                row = connection.run(sql_text("""
                    SELECT src.parse_run_id AS active_parse_run_id
                    FROM index_profile ip
                    JOIN index_run ir ON ir.id=ip.active_index_run_id
                    JOIN index_run_source src ON src.index_run_id=ir.id
                    WHERE ip.profile_name=:p0 AND ir.status='succeeded'
                      AND ir.activation_status='active' AND src.document_id=:p1
                    """), {'p0': IndexConfig.from_environment().profile_name, 'p1': document_id}).mappings().fetchone()
            if row is None:
                return "MISSING", "制度不存在"
            if row["active_parse_run_id"] is None or int(row["active_parse_run_id"]) != parse_run_id:
                return "STALE", "active ParseRun已经变化"
            return "VALID", "制度版本有效"
        except (LookupError, SQLAlchemyError):
            return "UNAVAILABLE", "知识数据库暂不可读"

    def index_status(self) -> dict[str, Any]:
        """返回独立索引配置和最近IndexRun，不读取其他RAG命名空间。"""

        with self._connection() as connection:
            profile = connection.run(sql_text('SELECT * FROM index_profile WHERE profile_name=:p0'), {'p0': IndexConfig.from_environment().profile_name}).mappings().fetchone()
            runs = self._rows(connection.run(sql_text('SELECT * FROM index_run WHERE profile_id=:p0 ORDER BY id DESC LIMIT 20'), {'p0': profile["id"]}).mappings()) if profile else []
        return {"profile": dict(profile) if profile else None, "runs": runs}

    @staticmethod
    def _json(value: str | None, default: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return default

    @staticmethod
    def _issue_type(code: str) -> str:
        value = code.upper()
        rules = (
            (("TITLE",), "TITLE_RECOGNITION_ERROR"),
            (("LEVEL", "HIERARCH", "NUMBER"), "HIERARCHY_ERROR"),
            (("PAGE",), "PAGE_ANOMALY"),
            (("TABLE",), "TABLE_PARSE_ERROR"),
            (("LONG", "TOKEN"), "CHUNK_TOO_LONG"),
            (("DUPLICATE",), "CHUNK_DUPLICATE"),
            (("SOURCE", "UNMAPPED"), "SOURCE_NODE_MISSING"),
        )
        for needles, issue_type in rules:
            if any(needle in value for needle in needles):
                return issue_type
        return value
