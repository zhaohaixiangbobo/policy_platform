"""ChunkRun 人工审核、审计记录与正式激活服务。

审核结果复用现有 review_decision 表。Error 只能驳回并重新生成；Review 问题可确认
或忽略。只有来源仍是当前 active ParseRun 的正式运行才能批准并激活。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text, select, update, insert, bindparam
from knowledge.storage.schema import metadata as knowledge_metadata


import json
from pathlib import Path
from typing import Any

from ..parser.database import ParserDatabase, utc_now


ALLOWED_ACTIONS = {"confirm", "ignore", "reject"}


class ChunkReviewService:
    """提供 Chunk Issue、Chunk 和 ChunkRun 的人工审核操作。"""

    def __init__(self, database_url: str) -> None:
        self.db = ParserDatabase(database_url)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ChunkReviewService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _run(self, chunk_run_id: int) -> dict[str, Any]:
        row = self.db.repository.run(sql_text('SELECT * FROM chunk_run WHERE id=:p0'), {'p0': chunk_run_id}).mappings().fetchone()
        if row is None:
            raise ValueError(f"ChunkRun 不存在：{chunk_run_id}")
        return dict(row)

    def _target(
        self, chunk_run_id: int, target_type: str, target_id: int
    ) -> dict[str, Any]:
        if target_type == "chunk_issue":
            query = "SELECT * FROM chunk_validation_issue WHERE id=:target_id AND chunk_run_id=:chunk_run_id"
        elif target_type == "chunk":
            query = "SELECT * FROM policy_chunk WHERE id=:target_id AND chunk_run_id=:chunk_run_id"
        else:
            raise ValueError(f"不支持的 Chunk 审核对象：{target_type}")
        row = self.db.repository.run(sql_text(query), {"target_id": target_id, "chunk_run_id": chunk_run_id}).mappings().fetchone()
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
                    self.db.repository.run(sql_text("""
                        UPDATE chunk_validation_issue
                        SET resolved=1, resolved_by=:p0, resolved_at=:p1
                        WHERE id=:p2 AND chunk_run_id=:p3
                        """), {'p0': reviewed_by, 'p1': now, 'p2': target_id, 'p3': chunk_run_id})
            else:
                status = "rejected" if action == "reject" else "confirmed"
                self.db.repository.run(sql_text('UPDATE policy_chunk SET review_status=:p0 WHERE id=:p1 AND chunk_run_id=:p2'), {'p0': status, 'p1': target_id, 'p2': chunk_run_id})
            after = self._target(chunk_run_id, target_type, target_id)
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8) RETURNING id"""), {'p0': int(run["parse_run_id"]), 'p1': target_type, 'p2': target_id, 'p3': action, 'p4': json.dumps(before, ensure_ascii=False), 'p5': json.dumps(after, ensure_ascii=False), 'p6': comment, 'p7': reviewed_by, 'p8': now})
        return self.refresh_state(chunk_run_id)

    def decide_many(
        self,
        *,
        chunk_run_id: int,
        target_ids: list[int],
        reviewed_by: str,
        comment: str | None,
    ) -> dict[str, Any]:
        """原子批量接受ChunkRun普通问题；Error级问题始终留给返工流程。"""

        ids = list(dict.fromkeys(int(value) for value in target_ids))
        if not ids or len(ids) > 500:
            raise ValueError("批量审核必须包含1至500个对象")
        if not (comment or "").strip():
            raise ValueError("批量接受普通问题必须填写统一接受理由")
        run = self._run(chunk_run_id)
        before_rows = [self._target(chunk_run_id, "chunk_issue", target_id) for target_id in ids]
        for before in before_rows:
            if before["resolved"] or before["severity"] == "error":
                raise ValueError(f"问题 {before['id']} 不是可批量接受的普通待处理问题")
        now = utc_now()
        with self.db.transaction():
            for before in before_rows:
                target_id = int(before["id"])
                self.db.repository.run(sql_text('UPDATE chunk_validation_issue SET resolved=1,resolved_by=:p0,resolved_at=:p1 WHERE id=:p2 AND chunk_run_id=:p3'), {'p0': reviewed_by, 'p1': now, 'p2': target_id, 'p3': chunk_run_id})
                after = self._target(chunk_run_id, "chunk_issue", target_id)
                self.db.repository.run(sql_text("""
                    INSERT INTO review_decision (
                        parse_run_id,target_type,target_id,action,old_value_json,
                        new_value_json,comment,reviewed_by,reviewed_at
                    ) VALUES (:p0, 'chunk_issue', :p1, 'ignore', :p2, :p3, :p4, :p5, :p6) RETURNING id"""), {'p0': int(run["parse_run_id"]), 'p1': target_id, 'p2': json.dumps(before, ensure_ascii=False), 'p3': json.dumps(after, ensure_ascii=False), 'p4': comment, 'p5': reviewed_by, 'p6': now})
        return {**self.refresh_state(chunk_run_id), "processed_count": len(ids)}

    def reject_run(
        self, chunk_run_id: int, reviewed_by: str, comment: str | None = None
    ) -> dict[str, Any]:
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空")
        run = self._run(chunk_run_id)
        now = utc_now()
        snapshot = {"status": "review_required", "review_status": "rejected"}
        with self.db.transaction():
            self.db.repository.run(sql_text("""
                UPDATE chunk_run
                SET status='review_required', review_status='rejected',
                    reviewed_by=:p0, reviewed_at=:p1
                WHERE id=:p2
                """), {'p0': reviewed_by, 'p1': now, 'p2': chunk_run_id})
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (:p0, 'chunk_run', :p1, 'reject', :p2, :p3, :p4, :p5, :p6) RETURNING id"""), {'p0': int(run["parse_run_id"]), 'p1': chunk_run_id, 'p2': json.dumps(run, ensure_ascii=False), 'p3': json.dumps(snapshot, ensure_ascii=False), 'p4': comment, 'p5': reviewed_by, 'p6': now})
        return {"chunk_run_id": chunk_run_id, **snapshot}

    def refresh_state(self, chunk_run_id: int) -> dict[str, Any]:
        run = self._run(chunk_run_id)
        unresolved = int(
            self.db.repository.run(sql_text("""
                SELECT COUNT(*) FROM chunk_validation_issue
                WHERE chunk_run_id=:p0 AND resolved=0 AND severity IN ('error','review')
                """), {'p0': chunk_run_id}).scalar_one()
        )
        rejected_chunks = int(
            self.db.repository.run(sql_text("SELECT COUNT(*) FROM policy_chunk WHERE chunk_run_id=:p0 AND review_status='rejected'"), {'p0': chunk_run_id}).scalar_one()
        )
        rejected_decisions = int(
            self.db.repository.run(sql_text("""
                SELECT COUNT(*) FROM review_decision
                WHERE parse_run_id=:p0 AND action='reject' AND (
                    (target_type='chunk_issue' AND target_id IN (
                        SELECT id FROM chunk_validation_issue WHERE chunk_run_id=:p1
                    )) OR
                    (target_type='chunk' AND target_id IN (
                        SELECT id FROM policy_chunk WHERE chunk_run_id=:p2
                    )) OR
                    (target_type='chunk_run' AND target_id=:p3)
                  )
                """), {'p0': int(run["parse_run_id"]), 'p1': chunk_run_id, 'p2': chunk_run_id, 'p3': chunk_run_id}).scalar_one()
        )
        rejected = rejected_chunks + rejected_decisions > 0
        review_status = "rejected" if rejected else (
            "pending" if unresolved else "ready_for_approval"
        )
        status = "failed" if run["status"] == "failed" else (
            "review_required" if rejected or unresolved else "succeeded"
        )
        self.db.repository.run(sql_text('UPDATE chunk_run SET status=:p0, review_status=:p1 WHERE id=:p2'), {'p0': status, 'p1': review_status, 'p2': chunk_run_id})
        self.db.repository.save()
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
        document = self.db.repository.run(sql_text('SELECT active_parse_run_id FROM policy_document WHERE id=:p0'), {'p0': int(run["document_id"])}).mappings().fetchone()
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
            self.db.repository.run(sql_text("""
                UPDATE chunk_run
                SET status='succeeded', review_status='approved',
                    reviewed_by=:p0, reviewed_at=:p1
                WHERE id=:p2
                """), {'p0': reviewed_by, 'p1': now, 'p2': chunk_run_id})
            self.db.repository.run(sql_text('UPDATE policy_document SET active_chunk_run_id=:p0, updated_at=:p1 WHERE id=:p2'), {'p0': chunk_run_id, 'p1': now, 'p2': int(run["document_id"])})
            self.db.repository.run(sql_text("""
                INSERT INTO review_decision (
                    parse_run_id, target_type, target_id, action,
                    old_value_json, new_value_json, comment, reviewed_by, reviewed_at
                ) VALUES (:p0, 'chunk_run', :p1, 'approve', :p2, :p3, :p4, :p5, :p6) RETURNING id"""), {'p0': int(run["parse_run_id"]), 'p1': chunk_run_id, 'p2': json.dumps(run, ensure_ascii=False), 'p3': json.dumps(snapshot, ensure_ascii=False), 'p4': comment, 'p5': reviewed_by, 'p6': now})
        return {
            "chunk_run_id": chunk_run_id,
            **snapshot,
            "active_chunk_run_id": chunk_run_id,
        }
