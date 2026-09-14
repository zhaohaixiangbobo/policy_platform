"""文件说明：从知识数据库读取active制度、Node和受控PDF。

本服务只提供产品页面需要的active视图，不复制制度投影，也不允许调用方指定历史
ParseRun冒充正式正文。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from .config import KnowledgePaths
from .indexing.config import IndexConfig


# 知识数据库保存稳定的英文状态码，产品接口统一返回中文业务名称。
STATUS_DISPLAY_NAMES = {
    "effective": "现行有效",
    "repealed": "已废止",
    "expired": "已失效",
    "draft": "草案",
    "unknown": "状态待确认",
}
STATUS_STORAGE_NAMES = {display: storage for storage, display in STATUS_DISPLAY_NAMES.items()}


class CatalogDocumentNotFoundError(LookupError):
    """active制度不存在。"""


class CatalogFileUnavailableError(LookupError):
    """active制度没有可安全访问的PDF。"""


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    id: int
    title: str
    document_code: str | None
    issuer: str | None
    responsibility_department: str | None
    status: str
    publish_date: str | None
    effective_date: str | None
    active_parse_run_id: int
    has_pdf: bool
    updated_at: str


@dataclass(frozen=True, slots=True)
class CatalogNode:
    id: int
    document_id: int
    parse_run_id: int
    parent_id: int | None
    node_type: str
    node_number: str | None
    title: str | None
    text: str
    path_text: str | None
    order_no: int
    page_start: int | None
    page_end: int | None
    table_structure: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class QueryableDocument:
    """当前 active IndexRun 中可供查询范围解析使用的具体制度版本。"""

    id: int
    status: str


@dataclass(frozen=True, slots=True)
class QueryableIndexSnapshot:
    """当前正式索引的制度范围快照。"""

    index_run_id: int
    documents: tuple[QueryableDocument, ...]


class KnowledgeCatalogService:
    """提供已发布索引版本中的制度、Node和PDF只读目录。"""

    _SORT_COLUMNS = {
        "updated_at": "m.updated_at",
        "title": "m.title",
        "document_code": "m.document_code",
        "issuer": "m.issuing_org",
        "publish_date": "m.publish_date",
        "effective_date": "m.effective_date",
        "status": "m.status",
        "responsibility_department": "m.owner_department",
    }

    def __init__(self, paths: KnowledgePaths, profile_name: str | None = None) -> None:
        self.paths = paths
        self.profile_name = profile_name or IndexConfig().profile_name

    @staticmethod
    def _published_condition(document_alias: str = "d") -> str:
        """只允许当前active IndexRun清单中的精确Document/ParseRun/ChunkRun组合。"""

        return f"""
            EXISTS (
                SELECT 1
                FROM index_profile ip
                JOIN index_run ir ON ir.id=ip.active_index_run_id
                JOIN index_run_source src ON src.index_run_id=ir.id
                WHERE ip.profile_name=?
                  AND ir.status='succeeded' AND ir.activation_status='active'
                  AND src.document_id={document_alias}.id
            )
        """

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        database_path = self.paths.database_path.resolve()
        if not database_path.is_file():
            raise RuntimeError(f"知识数据库不存在：{database_path}")
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()

    def list_documents(
        self,
        *,
        keyword: str | None,
        status: str | None,
        issuer: str | None,
        department: str | None,
        publish_date_from: str | None,
        publish_date_to: str | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
        query_scope: str | None = None,
        allowed_document_ids: Sequence[int] | None = None,
    ) -> tuple[list[CatalogDocument], int]:
        conditions = ["ip.profile_name=?", "ir.status='succeeded'", "ir.activation_status='active'"]
        parameters: list[Any] = [self.profile_name]
        if keyword:
            term = f"%{keyword.strip()}%"
            conditions.append(
                """(
                    m.title LIKE ? OR m.document_code LIKE ? OR m.issuing_org LIKE ?
                    OR m.owner_department LIKE ? OR EXISTS (
                        SELECT 1 FROM policy_node n
                        WHERE n.document_id=d.id AND n.parse_run_id=src.parse_run_id
                          AND (n.raw_text LIKE ? OR n.content LIKE ? OR n.title LIKE ? OR n.path_text LIKE ?)
                    )
                )"""
            )
            parameters.extend([term] * 8)
        for column, value in (
            ("m.status", status),
            ("m.issuing_org", issuer),
            ("m.owner_department", department),
        ):
            if value:
                conditions.append(f"{column}=?")
                parameters.append(
                    STATUS_STORAGE_NAMES.get(value, value) if column == "m.status" else value
                )
        if query_scope == "CURRENT":
            conditions.append("m.status='effective'")
        elif query_scope == "HISTORICAL":
            conditions.append("m.status IN ('repealed','expired')")
        if publish_date_from:
            conditions.append("m.publish_date>=?")
            parameters.append(publish_date_from)
        if publish_date_to:
            conditions.append("m.publish_date<=?")
            parameters.append(publish_date_to)
        if allowed_document_ids is not None:
            normalized_ids = sorted(set(int(value) for value in allowed_document_ids))
            if normalized_ids:
                # 使用JSON数组作为单参数，避免未来权限集合超过SQLite变量数量上限。
                conditions.append(
                    "d.id IN (SELECT CAST(value AS INTEGER) FROM json_each(?))"
                )
                parameters.append(json.dumps(normalized_ids, separators=(",", ":")))
            else:
                conditions.append("1=0")

        where_sql = " AND ".join(conditions)
        sort_column = self._SORT_COLUMNS[sort_by]
        direction = "ASC" if sort_order == "asc" else "DESC"
        base_sql = """
            FROM policy_document d
            JOIN index_profile ip ON ip.profile_name=?
            JOIN index_run ir ON ir.id=ip.active_index_run_id
            JOIN index_run_source src ON src.index_run_id=ir.id AND src.document_id=d.id
            JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
            JOIN parse_run pr ON pr.id=src.parse_run_id
        """
        # profile_name由JOIN消费，条件中的profile_name参数继续保持统一顺序。
        parameters = [self.profile_name, *parameters]
        conditions[0] = "ip.profile_name=?"
        with self._connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) {base_sql} WHERE {where_sql}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT d.id,m.title,m.document_code,m.issuing_org,m.owner_department,
                       m.status,m.publish_date,m.effective_date,src.parse_run_id AS active_parse_run_id,
                       m.updated_at,pr.pdf_path
                {base_sql}
                WHERE {where_sql}
                ORDER BY {sort_column} IS NULL, {sort_column} {direction}, d.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        return [self._document(row) for row in rows], total

    def list_facets(
        self, allowed_document_ids: Sequence[int] | None = None
    ) -> dict[str, list[str]]:
        with self._connection() as connection:
            return {
                "statuses": [
                    STATUS_DISPLAY_NAMES.get(value, value)
                    for value in self._distinct(connection, "status", allowed_document_ids)
                ],
                "issuers": self._distinct(connection, "issuing_org", allowed_document_ids),
                "departments": self._distinct(connection, "owner_department", allowed_document_ids),
            }

    def queryable_index_snapshot(self) -> QueryableIndexSnapshot:
        """返回 active IndexRun 与其中每个具体制度版本的冻结状态。"""

        with self._connection() as connection:
            profile = connection.execute(
                """
                SELECT ip.active_index_run_id
                FROM index_profile ip
                JOIN index_run ir ON ir.id=ip.active_index_run_id
                WHERE ip.profile_name=?
                  AND ir.status='succeeded' AND ir.activation_status='active'
                """,
                (self.profile_name,),
            ).fetchone()
            if profile is None or profile["active_index_run_id"] is None:
                raise RuntimeError("当前没有正式可查询的 active IndexRun")
            rows = connection.execute(
                """
                SELECT src.document_id,m.status
                FROM index_run_source src
                JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
                WHERE src.index_run_id=?
                ORDER BY src.document_id
                """,
                (int(profile["active_index_run_id"]),),
            ).fetchall()
        return QueryableIndexSnapshot(
            index_run_id=int(profile["active_index_run_id"]),
            documents=tuple(
                QueryableDocument(id=int(row["document_id"]), status=str(row["status"]))
                for row in rows
            ),
        )

    def get_document(self, document_id: int) -> CatalogDocument:
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT d.id,m.title,m.document_code,m.issuing_org,m.owner_department,
                       m.status,m.publish_date,m.effective_date,src.parse_run_id AS active_parse_run_id,
                       m.updated_at,pr.pdf_path
                FROM policy_document d
                JOIN index_profile ip ON ip.profile_name=?
                JOIN index_run ir ON ir.id=ip.active_index_run_id
                JOIN index_run_source src ON src.index_run_id=ir.id AND src.document_id=d.id
                JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
                JOIN parse_run pr ON pr.id=src.parse_run_id
                WHERE d.id=? AND ir.status='succeeded' AND ir.activation_status='active'
                """,
                (self.profile_name, document_id),
            ).fetchone()
        if row is None:
            raise CatalogDocumentNotFoundError
        return self._document(row)

    def list_nodes(self, document_id: int) -> tuple[int, list[CatalogNode]]:
        document = self.get_document(document_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id,document_id,parse_run_id,parent_id,node_type,node_number,
                       title,COALESCE(raw_text,content,'') AS text,path_text,order_no,
                       page_start,page_end,
                       CASE WHEN node_type='table' THEN (
                           SELECT sb.properties_json
                           FROM node_source_span nss
                           JOIN source_block sb ON sb.id=nss.source_block_id
                           WHERE nss.node_id=policy_node.id AND sb.block_type='table'
                           ORDER BY nss.id
                           LIMIT 1
                       ) END AS table_structure_json
                FROM policy_node
                WHERE document_id=? AND parse_run_id=?
                ORDER BY order_no,id
                """,
                (document_id, document.active_parse_run_id),
            ).fetchall()
        nodes = [
            CatalogNode(
                id=int(row["id"]),
                document_id=int(row["document_id"]),
                parse_run_id=int(row["parse_run_id"]),
                parent_id=int(row["parent_id"]) if row["parent_id"] is not None else None,
                node_type=str(row["node_type"]),
                node_number=self._optional_text(row["node_number"]),
                title=self._node_display_title(row),
                text=str(row["text"]),
                path_text=self._optional_text(row["path_text"]),
                order_no=int(row["order_no"]),
                page_start=int(row["page_start"]) if row["page_start"] is not None else None,
                page_end=int(row["page_end"]) if row["page_end"] is not None else None,
                table_structure=self._table_structure(row),
            )
            for row in rows
        ]
        return document.active_parse_run_id, nodes

    @staticmethod
    def _table_structure(row: sqlite3.Row) -> dict[str, Any] | None:
        """读取 Parser 已保存的表格几何信息；异常旧数据保持文本降级能力。"""

        value = row["table_structure_json"]
        if row["node_type"] != "table" or not value:
            return None
        try:
            structure = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return structure if isinstance(structure, dict) and isinstance(structure.get("rows"), list) else None

    def resolve_pdf(self, document_id: int) -> Path:
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT pr.pdf_path
                FROM policy_document d
                JOIN index_profile ip ON ip.profile_name=?
                JOIN index_run ir ON ir.id=ip.active_index_run_id
                JOIN index_run_source src ON src.index_run_id=ir.id AND src.document_id=d.id
                JOIN parse_run pr ON pr.id=src.parse_run_id
                WHERE d.id=? AND ir.status='succeeded' AND ir.activation_status='active'
                """,
                (self.profile_name, document_id),
            ).fetchone()
        if row is None:
            raise CatalogDocumentNotFoundError
        relative_path = str(row["pdf_path"] or "").replace("\\", "/")
        if not relative_path or Path(relative_path).is_absolute():
            raise CatalogFileUnavailableError
        candidate = (self.paths.data_root / relative_path).resolve()
        if (
            not candidate.is_relative_to(self.paths.data_root)
            or candidate.suffix.lower() != ".pdf"
            or not candidate.is_file()
        ):
            raise CatalogFileUnavailableError
        return candidate

    @staticmethod
    def _document(row: sqlite3.Row) -> CatalogDocument:
        return CatalogDocument(
            id=int(row["id"]),
            title=str(row["title"] or row["document_code"] or f"制度{row['id']}"),
            document_code=row["document_code"],
            issuer=row["issuing_org"],
            responsibility_department=row["owner_department"],
            status=STATUS_DISPLAY_NAMES.get(str(row["status"]), str(row["status"])),
            publish_date=row["publish_date"],
            effective_date=row["effective_date"],
            active_parse_run_id=int(row["active_parse_run_id"]),
            has_pdf=bool(row["pdf_path"]),
            updated_at=str(row["updated_at"]),
        )

    def _distinct(
        self,
        connection: sqlite3.Connection,
        column: str,
        allowed_document_ids: Sequence[int] | None = None,
    ) -> list[str]:
        access_sql = ""
        parameters: list[Any] = [self.profile_name]
        if allowed_document_ids is not None:
            normalized_ids = sorted(set(int(value) for value in allowed_document_ids))
            if normalized_ids:
                access_sql = (
                    " AND d.id IN "
                    "(SELECT CAST(value AS INTEGER) FROM json_each(?))"
                )
                parameters.append(json.dumps(normalized_ids, separators=(",", ":")))
            else:
                access_sql = " AND 1=0"
        rows = connection.execute(
            f"""
            SELECT DISTINCT m.{column}
            FROM policy_document d
            JOIN index_profile ip ON ip.profile_name=?
            JOIN index_run ir ON ir.id=ip.active_index_run_id
            JOIN index_run_source src ON src.index_run_id=ir.id AND src.document_id=d.id
            JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
            WHERE ir.status='succeeded' AND ir.activation_status='active'
              AND m.{column} IS NOT NULL AND m.{column}!=''
              {access_sql}
            ORDER BY m.{column}
            """,
            parameters,
        ).fetchall()
        return [str(row[0]) for row in rows]

    @classmethod
    def _node_display_title(cls, row: sqlite3.Row) -> str | None:
        """恢复旧公开视图的标题规则，使章、条、项按编号稳定分段。"""

        number = cls._compact_text(row["node_number"])
        title = cls._compact_text(row["title"])
        if number and title:
            return f"{number} {title}"
        return number or title

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _compact_text(cls, value: Any) -> str | None:
        text = cls._optional_text(value)
        return " ".join(text.split()) if text else None
