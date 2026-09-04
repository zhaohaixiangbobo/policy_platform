"""ChunkRun 人工审核、审计记录与正式激活服务。

审核结果复用现有 review_decision 表。Error 只能驳回并重新生成；Review 问题可确认
或忽略。只有来源仍是当前 active ParseRun 的正式运行才能批准并激活。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..parser.database import ParserDatabase, utc_now


ALLOWED_ACTIONS = {"confirm", "ignore", "reject"}


class ChunkReviewService:
    """提供 Chunk Issue、Chunk 和 ChunkRun 的人工审核操作。"""

    def __init__(self, database_path: Path) -> None:
        self.db = ParserDatabase(database_path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ChunkReviewService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _run(self, chunk_run_id: int) -> dict[str, Any]:
        row = self.db.connection.execute(
            "SELECT * FROM chunk_run WHERE id=?", (chunk_run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"ChunkRun 不存在：{chunk_run_id}")
        return dict(row)

    def _target(
        self, chunk_run_id: int, target_type: str, target_id: int
    ) -> dict[str, Any]:
        if target_type == "chunk_issue":
            query = "SELECT * FROM chunk_validation_issue WHERE id=? AND chunk_run_id=?"
        elif target_type == "chunk":
            query = "SELECT * FROM policy_chunk WHERE id=? AND chunk_run_id=?"
        else:
            raise ValueError(f"不支持的 Chunk 审核对象：{target_type}")
        row = self.db.connection.execute(query, (target_id, chunk_run_id)).fetchone()
        if row is None:
            raise ValueError(f"ChunkRun {chunk_run_id} 中不存在 {target_type} {target_id}")
        return dict(row)

    def decide(
        self,
        *,
        chunk_run_id: int,
        target_type: str,
        target_id: int,
        action: str,
        reviewed_by: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"不支持的审核动作：{action}")
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空")
        run = self._run(chunk_run_id)
        before = self._target(chunk_run_id, target_type, target_id)
        if (
            target_type == "chunk_issue"
            and before["severity"] == "error"
            and action != "reject"
        ):
            raise ValueError("Error 级问题不能直接确认或忽略，必须驳回并调整配置后重跑")
        now = utc_now()
        with self.db.transaction():
            if target_type == "chunk_issue":
                if action != "reject":
                    self.db.connection.execute(
                        """
                        UPDATE chunk_validation_issue
                        SET resolved=1, resolved_by=?, resolved_at=?
                        WHERE id=? AND chunk_run_id=?
                        """,
                        (reviewed_by, now, target_id, chunk_run_id),
                    )
            else:
                status = "rejected" if action == "reject" else "confirmed"
                self.db.connection.execute(
                    "UPDATE policy_chunk SET review_status=? WHERE id=? AND chunk_run_id=?",
                    (status, target_id, chunk_run_id),
                )
            after = self._target(chunk_run_id, target_type, target_id)
            self.db.connection.execute(
                """
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run["parse_run_id"]),
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
        return self.refresh_state(chunk_run_id)

    def reject_run(
        self, chunk_run_id: int, reviewed_by: str, comment: str | None = None
    ) -> dict[str, Any]:
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空")
        run = self._run(chunk_run_id)
        now = utc_now()
        snapshot = {"status": "review_required", "review_status": "rejected"}
        with self.db.transaction():
            self.db.connection.execute(
                """
                UPDATE chunk_run
                SET status='review_required', review_status='rejected',
                    reviewed_by=?, reviewed_at=?
                WHERE id=?
                """,
                (reviewed_by, now, chunk_run_id),
            )
            self.db.connection.execute(
                """
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (?, 'chunk_run', ?, 'reject', ?, ?, ?, ?, ?)
                """,
                (
                    int(run["parse_run_id"]),
                    chunk_run_id,
                    json.dumps(run, ensure_ascii=False),
                    json.dumps(snapshot, ensure_ascii=False),
                    comment,
                    reviewed_by,
                    now,
                ),
            )
        return {"chunk_run_id": chunk_run_id, **snapshot}

    def refresh_state(self, chunk_run_id: int) -> dict[str, Any]:
        run = self._run(chunk_run_id)
        unresolved = int(
            self.db.connection.execute(
                """
                SELECT COUNT(*) FROM chunk_validation_issue
                WHERE chunk_run_id=? AND resolved=0 AND severity IN ('error','review')
                """,
                (chunk_run_id,),
            ).fetchone()[0]
        )
        rejected_chunks = int(
            self.db.connection.execute(
                "SELECT COUNT(*) FROM policy_chunk WHERE chunk_run_id=? AND review_status='rejected'",
                (chunk_run_id,),
            ).fetchone()[0]
        )
        rejected_decisions = int(
            self.db.connection.execute(
                """
                SELECT COUNT(*) FROM review_decision
                WHERE parse_run_id=? AND action='reject' AND (
                    (target_type='chunk_issue' AND target_id IN (
                        SELECT id FROM chunk_validation_issue WHERE chunk_run_id=?
                    )) OR
                    (target_type='chunk' AND target_id IN (
                        SELECT id FROM policy_chunk WHERE chunk_run_id=?
                    )) OR
                    (target_type='chunk_run' AND target_id=?)
                  )
                """,
                (int(run["parse_run_id"]), chunk_run_id, chunk_run_id, chunk_run_id),
            ).fetchone()[0]
        )
        rejected = rejected_chunks + rejected_decisions > 0
        review_status = "rejected" if rejected else (
            "pending" if unresolved else "ready_for_approval"
        )
        status = "failed" if run["status"] == "failed" else (
            "review_required" if rejected or unresolved else "succeeded"
        )
        self.db.connection.execute(
            "UPDATE chunk_run SET status=?, review_status=? WHERE id=?",
            (status, review_status, chunk_run_id),
        )
        self.db.connection.commit()
        return {
            "chunk_run_id": chunk_run_id,
            "status": status,
            "review_status": review_status,
            "unresolved": unresolved,
            "rejected_chunks": rejected_chunks,
        }

    def approve_run(
        self, chunk_run_id: int, reviewed_by: str, comment: str | None = None
    ) -> dict[str, Any]:
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空")
        state = self.refresh_state(chunk_run_id)
        if state["status"] == "failed":
            raise ValueError(f"失败的 ChunkRun 不能批准：{state}")
        if state["review_status"] != "ready_for_approval":
            raise ValueError(f"ChunkRun 尚不能批准：{state}")
        run = self._run(chunk_run_id)
        document = self.db.connection.execute(
            "SELECT active_parse_run_id FROM policy_document WHERE id=?",
            (int(run["document_id"]),),
        ).fetchone()
        if run["source_scope"] != "active":
            raise ValueError("实验 ChunkRun 不得批准为正式版本")
        if document is None or document["active_parse_run_id"] is None:
            raise ValueError("所属文档没有 active_parse_run_id")
        if int(document["active_parse_run_id"]) != int(run["parse_run_id"]):
            raise ValueError("active_parse_run_id 已变化，请基于新解析版本重新生成 Chunk")
        if int(run["unmapped_node_count"] or 0) > 0:
            raise ValueError("仍有未映射合格 Node，不能批准")

        now = utc_now()
        snapshot = {"status": "succeeded", "review_status": "approved"}
        with self.db.transaction():
            self.db.connection.execute(
                """
                UPDATE chunk_run
                SET status='succeeded', review_status='approved',
                    reviewed_by=?, reviewed_at=?
                WHERE id=?
                """,
                (reviewed_by, now, chunk_run_id),
            )
            self.db.connection.execute(
                "UPDATE policy_document SET active_chunk_run_id=?, updated_at=? WHERE id=?",
                (chunk_run_id, now, int(run["document_id"])),
            )
            self.db.connection.execute(
                """
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (?, 'chunk_run', ?, 'approve', ?, ?, ?, ?, ?)
                """,
                (
                    int(run["parse_run_id"]),
                    chunk_run_id,
                    json.dumps(run, ensure_ascii=False),
                    json.dumps(snapshot, ensure_ascii=False),
                    comment,
                    reviewed_by,
                    now,
                ),
            )
        return {
            "chunk_run_id": chunk_run_id,
            **snapshot,
            "active_chunk_run_id": chunk_run_id,
        }
