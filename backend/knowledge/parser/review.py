"""解析结果人工审核服务。

该文件负责确认、驳回或修正 Issue、字段和 Node，并完整记录审核操作；
只有所有待审对象处理完且显式批准后，ParseRun 才会成为 active_parse_run。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import json
from pathlib import Path
from typing import Any

from .analyzer import PATTERNS
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

    def __init__(self, database_url: str) -> None:
        self.db = ParserDatabase(database_url)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ReviewService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _target(self, run_id: int, target_type: str, target_id: int) -> dict[str, Any]:
        if target_type not in TARGET_TABLES:
            raise ValueError(f"不支持的审核对象：{target_type}")
        table_name, key = TARGET_TABLES[target_type]
        table = knowledge_metadata.tables[table_name]
        row = self.db.repository.run(select(table).where(table.c[key] == target_id, table.c.parse_run_id == run_id)).mappings().fetchone()
        if row is None:
            raise ValueError(f"ParseRun {run_id} 中不存在 {target_type} {target_id}")
        return dict(row)

    def _resolve_article_title_issue(
        self, run_id: int, node_id: int, reviewed_by: str, reviewed_at: str
    ) -> None:
        """节点结论确定后同步关闭其启发式标题问题，避免重复处置。"""

        self.db.repository.run(sql_text("""
            UPDATE validation_issue
            SET resolved=1,resolved_by=:p0,resolved_at=:p1
            WHERE parse_run_id=:p2 AND node_id=:p3
              AND issue_code='NODE_ARTICLE_TITLE_HEURISTIC' AND resolved=0
            """), {'p0': reviewed_by, 'p1': reviewed_at, 'p2': run_id, 'p3': node_id})

    def _rebuild_path_text(self, run_id: int, updated_at: str) -> None:
        """按父子顺序重算当前运行的路径文字，使标题调整同步影响后代。"""

        rows = self.db.repository.run(sql_text("""
            SELECT id,parent_id,node_type,node_number,title,content
            FROM policy_node WHERE parse_run_id=:p0 ORDER BY level,order_no,id
            """), {'p0': run_id}).mappings().fetchall()
        path_by_id: dict[int, str] = {}
        for row in rows:
            label = row["title"] or row["node_number"] or (row["content"] or "")[:32] or row["node_type"]
            parent_path = path_by_id.get(int(row["parent_id"])) if row["parent_id"] else None
            path_text = f"{parent_path} > {label}" if parent_path else str(label)
            path_by_id[int(row["id"])] = path_text
            self.db.repository.run(sql_text('UPDATE policy_node SET path_text=:p0,updated_at=:p1 WHERE id=:p2 AND parse_run_id=:p3'), {'p0': path_text, 'p1': updated_at, 'p2': int(row["id"]), 'p3': run_id})

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
        if target_type == "issue" and before["severity"] == "error" and action != "reject":
            raise ValueError("Error级问题不能直接确认或忽略，必须驳回并修正后重跑")
        now = utc_now()
        with self.db.transaction():
            if target_type == "issue":
                self.db.repository.run(sql_text("""
                    UPDATE validation_issue
                    SET resolved=1, resolved_by=:p0, resolved_at=:p1
                    WHERE id=:p2 AND parse_run_id=:p3
                    """), {'p0': reviewed_by, 'p1': now, 'p2': target_id, 'p3': run_id})
            elif target_type in {"field", "node"}:
                if action == "correct":
                    if target_type != "field" or corrected_value is None:
                        raise ValueError("correct 当前只支持字段，且必须提供 corrected_value")
                    self.db.repository.run(sql_text("""
                        UPDATE extracted_field
                        SET normalized_value=:p0, review_status='confirmed'
                        WHERE id=:p1 AND parse_run_id=:p2
                        """), {'p0': corrected_value, 'p1': target_id, 'p2': run_id})
                else:
                    status = "rejected" if action == "reject" else "confirmed"
                    table = knowledge_metadata.tables["extracted_field" if target_type == "field" else "policy_node"]
                    self.db.repository.run(update(table).where(table.c.id == target_id, table.c.parse_run_id == run_id).values(review_status=status))
                    if target_type == "node" and action == "confirm":
                        self._resolve_article_title_issue(run_id, target_id, reviewed_by, now)
            after = self._target(run_id, target_type, target_id)
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8) RETURNING id"""), {'p0': run_id, 'p1': target_type, 'p2': target_id, 'p3': action, 'p4': json.dumps(before, ensure_ascii=False), 'p5': json.dumps(after, ensure_ascii=False), 'p6': comment, 'p7': reviewed_by, 'p8': now})
        return self.refresh_state(run_id)

    def decide_article_title(
        self,
        *,
        run_id: int,
        node_id: int,
        mode: str,
        reviewed_by: str,
        title: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """人工确认启发式条标题，或将其恢复为条文正文。"""

        if mode not in {"TITLE", "CONTENT"}:
            raise ValueError("条标题审核模式必须为TITLE或CONTENT")
        if not reviewed_by.strip():
            raise ValueError("reviewed_by不能为空")
        run = self.db.repository.run(sql_text('SELECT status,review_status FROM parse_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
        if run is None:
            raise ValueError(f"ParseRun不存在：{run_id}")
        if run["review_status"] in {"approved", "rejected"} or run["status"] == "failed":
            raise ValueError("已完成或失败的ParseRun不可原位修改，请创建派生修订")
        before = self._target(run_id, "node", node_id)
        if before["node_type"] != "article" or before["rule_id"] != "NODE_ARTICLE_TITLE_HEURISTIC_V2":
            raise ValueError("当前节点不是待确认的启发式条标题")
        if before["review_status"] != "pending":
            raise ValueError("当前条标题已经处理")

        if mode == "TITLE":
            selected_title = (title if title is not None else before["title"] or "").strip().rstrip("：:").rstrip()
            if not selected_title:
                raise ValueError("确认条标题时标题不能为空")
            content = None
            rule_id = "NODE_ARTICLE_TITLE_HUMAN_V1"
            action = "confirm_article_title"
        else:
            source_text = str(before["normalized_content"] or before["raw_text"] or "").strip()
            match = PATTERNS["article"].match(source_text)
            content = match.group(2).strip() if match else source_text
            if not content:
                raise ValueError("无法从节点原文恢复条文正文")
            selected_title = None
            rule_id = "NODE_ARTICLE_CONTENT_HUMAN_V1"
            action = "mark_article_content"

        now = utc_now()
        with self.db.transaction():
            self.db.repository.run(sql_text("""
                UPDATE policy_node
                SET title=:p0,content=:p1,decision_method='human',rule_id=:p2,
                    review_status='confirmed',review_reason=NULL,updated_at=:p3
                WHERE id=:p4 AND parse_run_id=:p5
                """), {'p0': selected_title, 'p1': content, 'p2': rule_id, 'p3': now, 'p4': node_id, 'p5': run_id})
            self._rebuild_path_text(run_id, now)
            self._resolve_article_title_issue(run_id, node_id, reviewed_by, now)
            after = self._target(run_id, "node", node_id)
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id,target_type,target_id,action,old_value_json,
                    new_value_json,comment,reviewed_by,reviewed_at
                ) VALUES (:p0,:p1,:p2,:p3,:p4,:p5,:p6,:p7,:p8) RETURNING id"""), {'p0': run_id, 'p1': "node", 'p2': node_id, 'p3': action, 'p4': json.dumps(before, ensure_ascii=False), 'p5': json.dumps(after, ensure_ascii=False), 'p6': comment, 'p7': reviewed_by, 'p8': now})
        return self.refresh_state(run_id)

    def decide_many(
        self,
        *,
        run_id: int,
        target_type: str,
        target_ids: list[int],
        action: str,
        reviewed_by: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """原子批量确认节点或接受普通问题，任一对象不合法时整批不写入。"""

        ids = list(dict.fromkeys(int(value) for value in target_ids))
        if not ids or len(ids) > 500:
            raise ValueError("批量审核必须包含1至500个对象")
        if target_type == "node" and action != "confirm":
            raise ValueError("节点批量操作只支持确认")
        if target_type == "issue" and action != "ignore":
            raise ValueError("普通问题批量操作只支持接受")
        if target_type not in {"node", "issue"}:
            raise ValueError("ParseRun批量操作只支持节点或普通问题")
        if target_type == "issue" and not (comment or "").strip():
            raise ValueError("批量接受普通问题必须填写统一接受理由")
        before_rows = [self._target(run_id, target_type, target_id) for target_id in ids]
        for before in before_rows:
            if target_type == "node" and before["review_status"] != "pending":
                raise ValueError(f"Node {before['id']} 已处理，不能重复批量确认")
            if target_type == "issue" and (before["resolved"] or before["severity"] == "error"):
                raise ValueError(f"问题 {before['id']} 不是可批量接受的普通待处理问题")

        now = utc_now()
        with self.db.transaction():
            for before in before_rows:
                target_id = int(before["id"])
                if target_type == "node":
                    self.db.repository.run(sql_text("UPDATE policy_node SET review_status='confirmed' WHERE id=:p0 AND parse_run_id=:p1"), {'p0': target_id, 'p1': run_id})
                    self._resolve_article_title_issue(run_id, target_id, reviewed_by, now)
                else:
                    self.db.repository.run(sql_text('UPDATE validation_issue SET resolved=1,resolved_by=:p0,resolved_at=:p1 WHERE id=:p2 AND parse_run_id=:p3'), {'p0': reviewed_by, 'p1': now, 'p2': target_id, 'p3': run_id})
                after = self._target(run_id, target_type, target_id)
                self.db.repository.run(sql_text("""
                    INSERT INTO review_decision (
                        parse_run_id,target_type,target_id,action,old_value_json,
                        new_value_json,comment,reviewed_by,reviewed_at
                    ) VALUES (:p0,:p1,:p2,:p3,:p4,:p5,:p6,:p7,:p8) RETURNING id"""), {'p0': run_id, 'p1': target_type, 'p2': target_id, 'p3': action, 'p4': json.dumps(before, ensure_ascii=False), 'p5': json.dumps(after, ensure_ascii=False), 'p6': comment, 'p7': reviewed_by, 'p8': now})
        return {**self.refresh_state(run_id), "processed_count": len(ids)}

    def _pending_counts(self, run_id: int) -> dict[str, int]:
        queries = {
            "issues": "SELECT COUNT(*) FROM validation_issue WHERE parse_run_id=:run_id AND resolved=0 AND severity IN ('error','review')",
            "fields": "SELECT COUNT(*) FROM extracted_field WHERE parse_run_id=:run_id AND review_status='pending'",
            "nodes": "SELECT COUNT(*) FROM policy_node WHERE parse_run_id=:run_id AND review_status='pending'",
            "rejected_fields": "SELECT COUNT(*) FROM extracted_field WHERE parse_run_id=:run_id AND review_status='rejected'",
            "rejected_nodes": "SELECT COUNT(*) FROM policy_node WHERE parse_run_id=:run_id AND review_status='rejected'",
            "rejected_decisions": """
                SELECT COUNT(*)
                FROM review_decision rd
                JOIN (
                    SELECT target_type, target_id, MAX(id) AS latest_id
                    FROM review_decision
                    WHERE parse_run_id=:run_id AND target_type IN ('issue','field','node')
                    GROUP BY target_type, target_id
                ) latest ON latest.latest_id=rd.id
                WHERE rd.action='reject'
            """,
        }
        return {
            name: int(self.db.repository.run(sql_text(query), {"run_id": run_id}).scalar_one())
            for name, query in queries.items()
        }

    def refresh_state(self, run_id: int) -> dict[str, Any]:
        """根据待审对象刷新运行状态，但不自动批准成为 active。"""

        run = self.db.repository.run(sql_text('SELECT * FROM parse_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
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
        run = self.db.repository.run(sql_text('SELECT * FROM parse_run WHERE id=:p0'), {'p0': run_id}).mappings().fetchone()
        confirmed_rows = self.db.repository.run(sql_text("""
            SELECT field_name, raw_value, normalized_value, confidence, id
            FROM extracted_field
            WHERE parse_run_id=:p0 AND review_status='confirmed'
            ORDER BY confidence DESC, id
            """), {'p0': run_id}).mappings().fetchall()
        document_fields: dict[str, str] = {}
        for field in confirmed_rows:
            name = str(field["field_name"])
            if name in DOCUMENT_FIELD_NAMES and name not in document_fields:
                document_fields[name] = field["normalized_value"] or field["raw_value"]
        now = utc_now()
        with self.db.transaction():
            self.db.repository.run(sql_text("UPDATE parse_run SET status='succeeded', review_status='approved', reviewed_by=:p0, reviewed_at=:p1 WHERE id=:p2"), {'p0': reviewed_by, 'p1': now, 'p2': run_id})
            # ParseRun批准只推进候选解析指针；公开元数据由IndexRun冻结的修订决定。
            document_updates: dict[str, Any] = {
                "active_parse_run_id": run_id,
                "parser_status": "succeeded",
                "review_status": "passed",
                "updated_at": now,
            }
            table = knowledge_metadata.tables["policy_document"]
            self.db.repository.run(update(table).where(table.c.id == int(run["document_id"])).values(**document_updates))
            snapshot = {
                "status": "succeeded",
                "review_status": "approved",
                "document_fields": document_fields,
            }
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (:p0, 'run', :p1, 'approve', :p2, :p3, :p4, :p5, :p6) RETURNING id"""), {'p0': run_id, 'p1': run_id, 'p2': json.dumps(dict(run), ensure_ascii=False), 'p3': json.dumps(snapshot, ensure_ascii=False), 'p4': comment, 'p5': reviewed_by, 'p6': now})
        return {"run_id": run_id, **snapshot, "active_parse_run_id": run_id}
