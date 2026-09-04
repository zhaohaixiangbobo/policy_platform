"""文件说明：将旧RAG知识数据库和active文档闭包迁入统一项目。

脚本使用SQLite backup API复制完整运行数据库，仅复制active制度引用的原始DOCX、
accepted DOCX和PDF；目标数据库只保存相对路径，未迁移的历史运行文件路径会清空，
但历史Run、Node、Chunk、审核和索引记录保持不变。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_single(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"文件匹配数量异常：directory={directory}, pattern={pattern}, count={len(matches)}"
        )
    return matches[0]


def copy_verified(source: Path, destination: Path, expected_hash: str) -> dict[str, Any]:
    actual_source_hash = sha256_file(source)
    if actual_source_hash.lower() != expected_hash.lower():
        raise RuntimeError(f"源文件checksum不一致：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    actual_target_hash = sha256_file(destination)
    if actual_target_hash != actual_source_hash:
        raise RuntimeError(f"复制后checksum不一致：{destination}")
    return {
        "source": str(source),
        "target": destination.as_posix(),
        "size": destination.stat().st_size,
        "sha256": actual_target_hash,
    }


def backup_database(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(".db.migrating")
    if temporary.exists():
        temporary.unlink()
    source_connection = sqlite3.connect(
        f"file:{source.resolve().as_posix()}?mode=ro", uri=True
    )
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    os.replace(temporary, destination)


def migrate(source_root: Path, target_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    if source_root == target_root:
        raise ValueError("源目录和目标目录不能相同")

    source_output = source_root / ".policy_parser_output"
    source_database = source_output / "policy_parser.db"
    target_root.mkdir(parents=True, exist_ok=True)
    for name in ("source_documents", "accepted", "pdf"):
        (target_root / name).mkdir(parents=True, exist_ok=True)

    target_database = target_root / "policy_parser.db"
    backup_database(source_database, target_database)

    connection = sqlite3.connect(target_database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    active_rows = connection.execute(
        """
        SELECT d.id AS document_id,d.file_name,d.checksum,d.source_file,
               d.active_parse_run_id,pr.accepted_checksum,pr.pdf_checksum
        FROM policy_document d
        JOIN parse_run pr ON pr.id=d.active_parse_run_id
        WHERE d.active_parse_run_id IS NOT NULL
        ORDER BY d.id
        """
    ).fetchall()
    if not active_rows:
        connection.close()
        raise RuntimeError("知识数据库没有active制度")

    # 历史运行记录继续保留，但目标工程不伪装拥有未迁移的历史文件。
    connection.execute("UPDATE parse_run SET accepted_docx_path=NULL,pdf_path=NULL")
    files: list[dict[str, Any]] = []
    try:
        for row in active_rows:
            document_id = int(row["document_id"])
            checksum = str(row["checksum"])
            accepted_checksum = str(row["accepted_checksum"])
            pdf_checksum = str(row["pdf_checksum"])

            configured_source = Path(str(row["source_file"]))
            if not configured_source.is_file():
                configured_source = locate_single(
                    source_root / "source_documents", str(row["file_name"])
                )
            accepted_source = locate_single(
                source_output / "accepted",
                f"*__{checksum[:12]}__accepted.docx",
            )
            pdf_source = locate_single(
                source_output / "pdf", f"*__{checksum[:12]}.pdf"
            )

            source_relative = Path("source_documents") / configured_source.name
            accepted_relative = Path("accepted") / accepted_source.name
            pdf_relative = Path("pdf") / pdf_source.name
            files.extend(
                (
                    copy_verified(
                        configured_source, target_root / source_relative, checksum
                    ),
                    copy_verified(
                        accepted_source,
                        target_root / accepted_relative,
                        accepted_checksum,
                    ),
                    copy_verified(
                        pdf_source, target_root / pdf_relative, pdf_checksum
                    ),
                )
            )
            connection.execute(
                "UPDATE policy_document SET source_file=? WHERE id=?",
                (source_relative.as_posix(), document_id),
            )
            connection.execute(
                """
                UPDATE parse_run SET accepted_docx_path=?,pdf_path=?
                WHERE id=? AND document_id=?
                """,
                (
                    accepted_relative.as_posix(),
                    pdf_relative.as_posix(),
                    int(row["active_parse_run_id"]),
                    document_id,
                ),
            )
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        active_documents = int(
            connection.execute(
                "SELECT COUNT(*) FROM policy_document WHERE active_parse_run_id IS NOT NULL"
            ).fetchone()[0]
        )
        active_nodes = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM policy_node n
                JOIN policy_document d ON d.active_parse_run_id=n.parse_run_id
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()

    manifest = {
        "source_root": str(source_root),
        "target_root": str(target_root),
        "database": {
            "path": str(target_database),
            "sha256": sha256_file(target_database),
            "integrity_check": integrity,
            "foreign_key_error_count": foreign_key_errors,
        },
        "active_document_count": active_documents,
        "active_node_count": active_nodes,
        "file_count": len(files),
        "files": files,
    }
    (target_root / "migration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移active制度知识数据")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args()
    result = migrate(args.source_root, args.target_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
