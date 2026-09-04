"""文件说明：受控协调已上线失败任务，并清理未使用的运行时BACKFILL草稿。

默认只输出计划；显式传入 ``--apply`` 才会修改数据。脚本不调用Embedding、Qdrant或Alias。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.application.ingestion_service import IngestionService  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.infrastructure.db.models import (  # noqa: E402
    IndexPublicationSource,
    IndexPublicationRequest,
    IngestionJob,
    MetadataChangeRequest,
)
from app.infrastructure.db.session import get_session_factory  # noqa: E402
from knowledge.config import KnowledgePaths  # noqa: E402
from knowledge.parser.database import ParserDatabase  # noqa: E402


def collect_plan(session, database: ParserDatabase) -> dict[str, object]:
    """只读收集能够由精确版本证据证明的协调和清理对象。"""

    profile = database.connection.execute(
        "SELECT active_index_run_id FROM index_profile WHERE active_index_run_id IS NOT NULL LIMIT 1"
    ).fetchone()
    active_index_run_id = int(profile["active_index_run_id"]) if profile else None
    reconciliations: list[dict[str, object]] = []
    if active_index_run_id is not None:
        failed_jobs = list(session.scalars(select(IngestionJob).where(
            IngestionJob.state == "FAILED",
            IngestionJob.failed_stage.in_(["INDEXING", "PUBLISHING"]),
        )).all())
        publications = list(session.scalars(select(IndexPublicationRequest).where(
            IndexPublicationRequest.status == "PUBLISHED",
            IndexPublicationRequest.index_run_id == active_index_run_id,
        ).order_by(IndexPublicationRequest.published_at.desc())).all())
        for job in failed_jobs:
            source = database.connection.execute(
                """
                SELECT document_id,parse_run_id,chunk_run_id,metadata_revision_id
                FROM index_run_source WHERE index_run_id=? AND document_id=?
                """,
                (active_index_run_id, job.document_id),
            ).fetchone()
            if source is None or job.parse_run_id != source["parse_run_id"] or job.chunk_run_id != source["chunk_run_id"]:
                continue
            request = session.scalar(select(MetadataChangeRequest).where(
                MetadataChangeRequest.job_id == job.id,
                MetadataChangeRequest.metadata_revision_id == int(source["metadata_revision_id"]),
                MetadataChangeRequest.status.in_(["APPROVED", "PUBLISHED"]),
            ))
            publication = next(
                (
                    item for item in publications
                    if int(job.document_id) in {int(value) for value in json.loads(item.source_document_ids_json)}
                ),
                None,
            )
            if request is None or publication is None:
                continue
            reconciliations.append({
                "job_id": job.id,
                "document_id": int(job.document_id),
                "parse_run_id": int(source["parse_run_id"]),
                "chunk_run_id": int(source["chunk_run_id"]),
                "metadata_revision_id": int(source["metadata_revision_id"]),
                "metadata_change_request_id": request.id,
                "index_run_id": active_index_run_id,
                "publication_request_id": publication.id,
            })

    request_revision_ids = {
        int(value) for value in session.scalars(select(MetadataChangeRequest.metadata_revision_id)).all()
    }
    rows = database.connection.execute(
        """
        SELECT mr.id AS revision_id,mr.document_id
        FROM document_metadata_revision mr
        JOIN policy_document d ON d.id=mr.document_id
        WHERE mr.source_type='BACKFILL' AND mr.lifecycle_status='DRAFT'
          AND mr.parse_run_id IS NULL
          AND d.latest_metadata_revision_id=mr.id
          AND d.approved_metadata_revision_id IS NULL
          AND d.active_metadata_revision_id IS NULL
        ORDER BY mr.id
        """
    ).fetchall()
    cleanups = [
        {"revision_id": int(row["revision_id"]), "document_id": int(row["document_id"])}
        for row in rows if int(row["revision_id"]) not in request_revision_ids
    ]
    return {
        "active_index_run_id": active_index_run_id,
        "reconciliations": reconciliations,
        "backfill_draft_cleanups": cleanups,
    }


def apply_plan(session, database: ParserDatabase, paths: KnowledgePaths, plan: dict[str, object]) -> None:
    """只执行collect_plan已证明安全的精确变更。"""

    ingestion = IngestionService(session, paths)
    for item in plan["reconciliations"]:
        values = dict(item)
        job = session.get(IngestionJob, values["job_id"])
        publication_id = str(values["publication_request_id"])
        existing = session.scalar(select(IndexPublicationSource).where(
            IndexPublicationSource.publication_request_id == publication_id,
            IndexPublicationSource.document_id == int(values["document_id"]),
        ))
        if existing is None:
            session.add(IndexPublicationSource(
                publication_request_id=publication_id,
                job_id=job.id,
                document_id=int(values["document_id"]),
                parse_run_id=int(values["parse_run_id"]),
                chunk_run_id=int(values["chunk_run_id"]),
                metadata_revision_id=int(values["metadata_revision_id"]),
                index_run_id=int(values["index_run_id"]),
            ))
        metadata_request = session.get(
            MetadataChangeRequest, str(values["metadata_change_request_id"])
        )
        if metadata_request is None:
            raise RuntimeError("协调计划引用的元数据审核请求不存在")
        metadata_request.status = "PUBLISHED"
        ingestion.reconcile_published_job(
            job,
            index_run_id=int(values["index_run_id"]),
            parse_run_id=int(values["parse_run_id"]),
            chunk_run_id=int(values["chunk_run_id"]),
            reason="知识侧active IndexRun已证明该任务版本正式上线，执行受控状态协调",
        )

    cleanup_items = [dict(item) for item in plan["backfill_draft_cleanups"]]
    with database.transaction():
        for item in cleanup_items:
            database.connection.execute(
                "UPDATE policy_document SET latest_metadata_revision_id=NULL WHERE id=? AND latest_metadata_revision_id=?",
                (int(item["document_id"]), int(item["revision_id"])),
            )
            database.connection.execute(
                "DELETE FROM document_metadata_revision WHERE id=?",
                (int(item["revision_id"]),),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="检查或修复第二期任务与元数据一致性")
    parser.add_argument("--apply", action="store_true", help="执行已经过精确校验的修复")
    args = parser.parse_args()
    settings = get_settings()
    paths = KnowledgePaths(settings.knowledge_data_root)
    with get_session_factory()() as session, ParserDatabase(paths.database_path) as database:
        plan = collect_plan(session, database)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **plan}, ensure_ascii=False, indent=2))
        if args.apply:
            apply_plan(session, database, paths, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
