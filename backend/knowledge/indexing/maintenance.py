"""文件说明：按明确清单退役旧向量存储，保留知识运行和证据历史。

仅支持当前 SQLite 维护窗口；持有双库写锁并拒绝未完成发布，避免与平台发布并行。
DELETING 标记先于外部删除持久化，故障后使用相同清单可安全继续。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from .database import IndexDatabase, utc_now
from .qdrant_store import QdrantVectorStore


def validate_targets(connection, store, run_ids: Sequence[int], keep_ids: Sequence[int]) -> list[dict[str, Any]]:
    """将明确的运行ID解析为物理名称，保护所有profile和Alias的引用。"""
    targets, keep = set(run_ids), set(keep_ids)
    if not targets or targets & keep:
        raise ValueError("清理清单必须非空且与保留清单互斥")
    protected = set(keep)
    for row in connection.execute("SELECT active_index_run_id, latest_index_run_id FROM index_profile"):
        protected.update(value for value in row if value is not None)
    aliases = store.alias_targets()
    result = []
    for run_id in sorted(targets):
        row = connection.execute("SELECT * FROM index_run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"IndexRun {run_id} 不存在")
        run = dict(row)
        if run_id in protected or run["collection_name"] in aliases:
            raise ValueError(f"IndexRun {run_id} 仍被保留指针或Alias引用")
        if run["status"] not in {"succeeded", "failed"} or run["activation_status"] in {"active", "switching"}:
            raise ValueError(f"IndexRun {run_id} 正在使用或构建")
        result.append({"index_run_id": run_id, "collection_name": run["collection_name"],
                       "exists": store.collection_exists(run["collection_name"])})
    return result


def retire_collections(knowledge_path: Path, platform_path: Path, store: QdrantVectorStore,
                      run_ids: Sequence[int], keep_ids: Sequence[int], *, execute: bool = False) -> list[dict[str, Any]]:
    """默认仅预览；执行时仅删除清单中的collection，保留全部关系数据库业务记录。"""
    platform = sqlite3.connect(platform_path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        with IndexDatabase(knowledge_path) as db:
            platform.execute("BEGIN IMMEDIATE")
            db.connection.execute("BEGIN IMMEDIATE")
            pending = platform.execute(
                "SELECT id, status FROM index_publication_request WHERE status NOT IN ('PUBLISHED','FAILED','CANCELLED')"
            ).fetchall()
            if pending:
                raise ValueError(f"存在未完成发布请求，结束后再维护：{pending}")
            targets = validate_targets(db.connection, store, run_ids, keep_ids)
            if not execute:
                return targets
            for target in targets:
                run_id, name = target["index_run_id"], target["collection_name"]
                # 写入持久化墓碑；历史 succeeded 仍代表当时构建成功。
                db.connection.execute(
                    "INSERT INTO index_storage_retirement VALUES (?,?,'DELETING',?,NULL,?) "
                    "ON CONFLICT(index_run_id) DO NOTHING",
                    (run_id, name, utc_now(), "管理员按明确清单退役旧索引"),
                )
                db.connection.commit()
                db.connection.execute("BEGIN IMMEDIATE")
                validate_targets(db.connection, store, [run_id], keep_ids)
                if store.collection_exists(name):
                    store.delete_collection(name)
                if store.collection_exists(name):
                    raise RuntimeError(f"删除后仍存在：{name}")
                db.connection.execute(
                    "UPDATE index_storage_retirement SET state='DELETED', deleted_at=COALESCE(deleted_at,?) WHERE index_run_id=?",
                    (utc_now(), run_id),
                )
                db.connection.commit()
                db.connection.execute("BEGIN IMMEDIATE")
                target["result"] = "DELETED"
                print(f"event=index_storage_deleted index_run_id={run_id} collection={name}", flush=True)
            return targets
    finally:
        platform.rollback()
        platform.close()
