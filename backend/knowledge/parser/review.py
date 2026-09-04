"""解析结果人工审核服务。

该文件负责确认、驳回或修正 Issue、字段和 Node，并完整记录审核操作；
只有所有待审对象处理完且显式批准后，ParseRun 才会成为 active_parse_run。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import ParserDatabase, utc_now


TARGET_TABLES = {
    "issue": ("validation_issue", "id"),
    "field": ("extracted_field", "id"),
    "node": ("policy_node", "id"),
}
ALLOWED_ACTIONS = {"confirm", "reject", "ignore", "correct"}
DOCUMENT_FIELD_NAMES = {
    "title",
    "document_code",
    "document_type",
    "issuing_org",
    "addressee_text",
    "authority_level",
    "publish_date",
    "effective_date",
    "expiry_date",
    "status",
    "version",
    "owner_department",
    "confidentiality_level",
}


class ReviewService:
    """提供带审计记录的 ParseRun 人工审核操作。"""

    def __init__(self, database_path: Path) -> None:
        self.db = ParserDatabase(database_path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ReviewService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _target(self, run_id: int, target_type: str, target_id: int) -> dict[str, Any]:
        if target_type not in TARGET_TABLES:
            raise ValueError(f"不支持的审核对象：{target_type}")
        table, key = TARGET_TABLES[target_type]
        row = self.db.connection.execute(
            f"SELECT * FROM {table} WHERE {key}=? AND parse_run_id=?",
            (target_id, run_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"ParseRun {run_id} 中不存在 {target_type} {target_id}")
        return dict(row)

    def decide(
        self,
        *,
        run_id: int,
        target_type: str,
        target_id: int,
        action: str,
        reviewed_by: str,
        comment: str | None = None,
        corrected_value: str | None = None,
    ) -> dict[str, Any]:
        """审核一个 Issue、字段或 Node，并刷新 ParseRun 审核状态。"""

        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"不支持的审核动作：{action}")
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空")
        before = self._target(run_id, target_type, target_id)
        now = utc_now()
        with self.db.transaction():
            if target_type == "issue":
                self.db.connection.execute(
                    """
                    UPDATE validation_issue
                    SET resolved=1, resolved_by=?, resolved_at=?
                    WHERE id=? AND parse_run_id=?
                    """,
                    (reviewed_by, now, target_id, run_id),
                )
            elif target_type in {"field", "node"}:
                if action == "correct":
                    if target_type != "field" or corrected_value is None:
                        raise ValueError("correct 当前只支持字段，且必须提供 corrected_value")
                    self.db.connection.execute(
                        """
                        UPDATE extracted_field
                        SET normalized_value=?, review_status='confirmed'
                        WHERE id=? AND parse_run_id=?
                        """,
                        (corrected_value, target_id, run_id),
                    )
                else:
                    status = "rejected" if action == "reject" else "confirmed"
                    table = "extracted_field" if target_type == "field" else "policy_node"
                    self.db.connection.execute(
                        f"UPDATE {table} SET review_status=? WHERE id=? AND parse_run_id=?",
                        (status, target_id, run_id),
                    )
            after = self._target(run_id, target_type, target_id)
            self.db.connection.execute(
                """
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    target_type,
                    target_id,
                    action,
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False),
                    comment,
                    reviewed_by,
                    now,
                ),
            )
        return self.refresh_state(run_id)

    def _pending_counts(self, run_id: int) -> dict[str, int]:
        queries = {
            "issues": "SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=? AND resolved=0 AND severity IN ('error','review')",
            "fields": "SELECT COUNT(*) FROM extracted_field WHERE parse_run_id=? AND review_status='pending'",
            "nodes": "SELECT COUNT(*) FROM policy_node WHERE parse_run_id=? AND review_status='pending'",
            "rejected_fields": "SELECT COUNT(*) FROM extracted_field WHERE parse_run_id=? AND review_status='rejected'",
            "rejected_nodes": "SELECT COUNT(*) FROM policy_node WHERE parse_run_id=? AND review_status='rejected'",
            "rejected_decisions": """
                SELECT COUNT(*)
                FROM review_decision rd
                JOIN (
                    SELECT target_type, target_id, MAX(id) AS latest_id
                    FROM review_decision
                    WHERE parse_run_id=? AND target_type IN ('issue','field','node')
                    GROUP BY target_type, target_id
                ) latest ON latest.latest_id=rd.id
                WHERE rd.action='reject'
            """,
        }
        return {
            name: int(self.db.connection.execute(query, (run_id,)).fetchone()[0])
            for name, query in queries.items()
        }

    def refresh_state(self, run_id: int) -> dict[str, Any]:
        """根据待审对象刷新运行状态，但不自动批准成为 active。"""

        run = self.db.connection.execute("SELECT * FROM parse_run WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"ParseRun 不存在：{run_id}")
        counts = self._pending_counts(run_id)
        rejected = counts["rejected_fields"] + counts["rejected_nodes"] + counts["rejected_decisions"] > 0
        # 元数据字段交由独立修订页统一确认；ParseRun 只冻结结构、页码和解析问题。
        pending = counts["issues"] + counts["nodes"] > 0
        review_status = "rejected" if rejected else ("pending" if pending else "ready_for_approval")
        status = "failed" if run["status"] == "failed" else ("review_required" if pending or rejected else "succeeded")
        self.db.update_run(run_id, status=status, review_status=review_status)
        return {"run_id": run_id, "status": status, "review_status": review_status, **counts}

    def approve_run(self, run_id: int, reviewed_by: str, comment: str | None = None) -> dict[str, Any]:
        """在所有待审对象完成后批准 ParseRun，并将其设为 active。"""

        state = self.refresh_state(run_id)
        if state["status"] == "failed":
            raise ValueError(f"失败的 ParseRun 不能批准：{state}")
        if state["review_status"] != "ready_for_approval":
            raise ValueError(f"ParseRun 尚不能批准：{state}")
        run = self.db.connection.execute("SELECT * FROM parse_run WHERE id=?", (run_id,)).fetchone()
        confirmed_rows = self.db.connection.execute(
            """
            SELECT field_name, raw_value, normalized_value, confidence, id
            FROM extracted_field
            WHERE parse_run_id=? AND review_status='confirmed'
            ORDER BY confidence DESC, id
            """,
            (run_id,),
        ).fetchall()
        document_fields: dict[str, str] = {}
        for field in confirmed_rows:
            name = str(field["field_name"])
            if name in DOCUMENT_FIELD_NAMES and name not in document_fields:
                document_fields[name] = field["normalized_value"] or field["raw_value"]
        now = utc_now()
        with self.db.transaction():
            self.db.connection.execute(
                "UPDATE parse_run SET status='succeeded', review_status='approved', reviewed_by=?, reviewed_at=? WHERE id=?",
                (reviewed_by, now, run_id),
            )
            # ParseRun批准只推进候选解析指针；公开元数据由IndexRun冻结的修订决定。
            document_updates: dict[str, Any] = {
                "active_parse_run_id": run_id,
                "parser_status": "succeeded",
                "review_status": "passed",
                "updated_at": now,
            }
            columns = ", ".join(f"{name}=?" for name in document_updates)
            self.db.connection.execute(
                f"UPDATE policy_document SET {columns} WHERE id=?",
                (*document_updates.values(), int(run["document_id"])),
            )
            snapshot = {
                "status": "succeeded",
                "review_status": "approved",
                "document_fields": document_fields,
            }
            self.db.connection.execute(
                """
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (?, 'run', ?, 'approve', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_id,
                    json.dumps(dict(run), ensure_ascii=False),
                    json.dumps(snapshot, ensure_ascii=False),
                    comment,
                    reviewed_by,
                    now,
                ),
            )
        return {"run_id": run_id, **snapshot, "active_parse_run_id": run_id}
