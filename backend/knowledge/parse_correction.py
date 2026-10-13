"""文件说明：以派生ParseRun承载人工结构修正，保持已审核历史运行不可变。"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


from pathlib import Path
from typing import Any

from knowledge.parser.database import ParserDatabase, utc_now


ALLOWED_NODE_FIELDS = frozenset({"title", "node_number", "node_type", "parent_id", "order_no"})


class ParseCorrectionService:
    """克隆已批准ParseRun，并在新运行中应用受限结构修正。"""

    def __init__(self, database_url: str) -> None:
        self.db = ParserDatabase(database_url)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ParseCorrectionService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create(
        self,
        source_run_id: int,
        source_node_id: int,
        changes: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        unknown = set(changes) - ALLOWED_NODE_FIELDS
        if unknown or not changes:
            raise ValueError(f"结构修正字段必须属于：{sorted(ALLOWED_NODE_FIELDS)}")
        source_run = self.db.repository.run(sql_text('SELECT * FROM parse_run WHERE id=:p0'), {'p0': source_run_id}).mappings().fetchone()
        if source_run is None or source_run["review_status"] != "approved":
            raise ValueError("只有已批准ParseRun可以派生人工修正运行")
        source_node = self.db.repository.run(sql_text('SELECT * FROM policy_node WHERE id=:p0 AND parse_run_id=:p1'), {'p0': source_node_id, 'p1': source_run_id}).mappings().fetchone()
        if source_node is None:
            raise LookupError("待修正Node不存在")

        now = utc_now()
        with self.db.transaction():
            run_id = self._clone_row(
                "parse_run", source_run,
                {
                    "parent_parse_run_id": source_run_id,
                    "run_kind": "MANUAL_CORRECTION",
                    "status": "review_required",
                    "current_stage": "manual_structure_correction",
                    "started_at": now,
                    "finished_at": now,
                    "review_status": "pending",
                    "reviewed_by": None,
                    "reviewed_at": None,
                },
            )
            block_map: dict[int, int] = {}
            blocks = self.db.repository.run(sql_text('SELECT * FROM source_block WHERE parse_run_id=:p0 ORDER BY id'), {'p0': source_run_id}).mappings().fetchall()
            for row in blocks:
                block_map[int(row["id"])] = self._clone_row(
                    "source_block", row,
                    {
                        "parse_run_id": run_id,
                        "parent_block_id": block_map.get(int(row["parent_block_id"])) if row["parent_block_id"] is not None else None,
                    },
                )

            node_map: dict[int, int] = {}
            nodes = self.db.repository.run(sql_text('SELECT * FROM policy_node WHERE parse_run_id=:p0 ORDER BY level, order_no, id'), {'p0': source_run_id}).mappings().fetchall()
            for row in nodes:
                replacements = {
                    "parse_run_id": run_id,
                    "parent_id": node_map.get(int(row["parent_id"])) if row["parent_id"] is not None else None,
                    "review_status": "confirmed",
                    "review_reason": None,
                    "created_at": now,
                    "updated_at": now,
                }
                new_id = self._clone_row("policy_node", row, replacements)
                node_map[int(row["id"])] = new_id

            for row in self.db.repository.run(sql_text("""
                SELECT nss.* FROM node_source_span nss
                JOIN policy_node n ON n.id=nss.node_id
                WHERE n.parse_run_id=:p0 ORDER BY nss.id
                """), {'p0': source_run_id}).mappings().fetchall():
                self._clone_row("node_source_span", row, {
                    "node_id": node_map[int(row["node_id"])],
                    "source_block_id": block_map[int(row["source_block_id"])],
                })

            for row in self.db.repository.run(sql_text('SELECT * FROM extracted_field WHERE parse_run_id=:p0 ORDER BY id'), {'p0': source_run_id}).mappings().fetchall():
                self._clone_row("extracted_field", row, {
                    "parse_run_id": run_id,
                    "source_block_id": block_map.get(int(row["source_block_id"])) if row["source_block_id"] is not None else None,
                    "source_node_id": node_map.get(int(row["source_node_id"])) if row["source_node_id"] is not None else None,
                    "review_status": "confirmed",
                })

            target_node_id = node_map[source_node_id]
            normalized = dict(changes)
            if "parent_id" in normalized and normalized["parent_id"] is not None:
                requested_parent = int(normalized["parent_id"])
                if requested_parent not in node_map:
                    raise ValueError("新父Node必须来自同一个源ParseRun")
                normalized["parent_id"] = node_map[requested_parent]
            table = knowledge_metadata.tables["policy_node"]
            self.db.repository.run(update(table).where(table.c.id == target_node_id).values(**normalized, review_status="pending", updated_at=now))
            self.db.repository.run(sql_text('UPDATE policy_document SET latest_parse_run_id=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': run_id, 'p1': now, 'p2': int(source_run["document_id"])})
        return {
            "id": run_id,
            "document_id": int(source_run["document_id"]),
            "parent_parse_run_id": source_run_id,
            "corrected_node_id": target_node_id,
            "run_kind": "MANUAL_CORRECTION",
            "review_status": "pending",
            "created_by": actor_user_id,
        }

    def _clone_row(self, table: str, row: Any, replacements: dict[str, Any]) -> int:
        values = dict(row)
        values.pop("id", None)
        values.update(replacements)
        model = knowledge_metadata.tables[table]
        cursor = self.db.repository.run(insert(model).values(**values).returning(model.c.id))
        return int(cursor.scalar_one())
