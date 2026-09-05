"""文件说明：制度DOCX解析流水线。

该文件串联安全校验、accepted_final、Source Block、Node、元数据、PDF 页码
映射和校验落库，并持续输出阶段进度，便于批量任务观察。
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .analyzer import build_nodes, extract_metadata, validate_structure
from .database import ParserDatabase, utc_now
from .ooxml import (
    ImageReviewRequiredError,
    create_accepted_final,
    extract_source_blocks,
    validate_docx,
)
from .render import font_environment_hash, map_blocks_to_pdf_pages, render_docx_to_pdf


ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class ParserConfig:
    """解析规则和输出配置。"""

    # 0.1.4：条标题采用强结构证据和可人工确认的启发式规则。
    parser_version: str = "0.1.4"
    article_title_rule_version: str = "article_title_v2"
    render_pdf: bool = True
    render_engine: str = "auto_headless"
    libreoffice_path: str | None = None
    allow_images: bool = True
    max_zip_entries: int = 5000
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_compression_ratio: float = 200.0
    character_error_threshold: float = 0.95
    character_review_threshold: float = 0.98
    auto_activate: bool = False

    def __post_init__(self) -> None:
        """保证错误阈值不高于人工复核阈值，避免产生反向判定区间。"""

        if not 0 <= self.character_error_threshold <= self.character_review_threshold <= 1:
            raise ValueError("字符覆盖率阈值必须满足 0 <= error <= review <= 1")
        if self.auto_activate:
            raise ValueError("ParseRun自动激活已禁用，请使用review-parse完成显式人工批准")

    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PolicyParserPipeline:
    """单文件可审计解析器。"""

    def __init__(
        self,
        database_path: Path,
        output_root: Path,
        config: ParserConfig | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.config = config or ParserConfig()
        self.output_root = output_root.resolve()
        self.accepted_dir = self.output_root / "accepted"
        self.pdf_dir = self.output_root / "pdf"
        for directory in (self.accepted_dir, self.pdf_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.db = ParserDatabase(database_path)
        self.progress = progress or print

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "PolicyParserPipeline":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _stage(self, run_id: int, stage: str, message: str) -> None:
        self.db.update_run(run_id, current_stage=stage)
        self.progress(f"    [{stage}] {message}")

    def parse(self, source_path: Path) -> dict[str, Any]:
        """解析一个 DOCX，并返回数据库运行摘要。"""

        source_path = source_path.resolve()
        started = time.perf_counter()
        validation = validate_docx(
            source_path,
            max_entries=self.config.max_zip_entries,
            max_uncompressed_bytes=self.config.max_uncompressed_bytes,
            max_compression_ratio=self.config.max_compression_ratio,
        )
        if validation.image_entries and not self.config.allow_images:
            raise ImageReviewRequiredError(source_path, validation.image_entries)
        document_id = self.db.get_or_create_document(
            {
                "source_file": self._stored_path(source_path),
                "file_name": source_path.name,
                "file_size": validation.file_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "checksum": validation.checksum,
            }
        )
        run_id = self.db.create_parse_run(document_id, self.config.parser_version, self.config.config_hash())
        all_issues: list[dict[str, Any]] = []
        block_ids: dict[str, int] = {}
        node_ids: dict[str, int] = {}
        try:
            self._stage(run_id, "file_validation", "DOCX ZIP、关键 XML、大小和外部关系校验完成")
            for relation in validation.external_relationships:
                all_issues.append(
                    {
                        "stage": "file_validation",
                        "issue_code": "EXTERNAL_RELATIONSHIP_DETECTED",
                        "severity": "warning",
                        "message": "DOCX 包含外部关系，解析器未访问远程目标",
                        "details": relation,
                    }
                )

            self._stage(run_id, "revision_acceptance", "检测修订并生成 accepted_final 副本")
            accepted_name = f"{source_path.stem}__{validation.checksum[:12]}__accepted.docx"
            revision = create_accepted_final(source_path, self.accepted_dir / accepted_name)
            self.db.update_run(
                run_id,
                tracked_change_count=revision.original_revision_count,
                revision_view="accepted_final",
                accepted_docx_path=self._stored_path(revision.accepted_path),
                accepted_checksum=revision.accepted_checksum,
                acceptance_engine=revision.engine,
                acceptance_engine_version=revision.engine_version,
            )
            self.db.update_document(document_id, accepted_checksum=revision.accepted_checksum)
            if revision.original_revision_count:
                all_issues.append(
                    {
                        "stage": "revision_acceptance",
                        "issue_code": "TRACKED_CHANGES_DETECTED",
                        "severity": "review",
                        "message": "原始 DOCX 含修订；解析使用接受全部修订后的最终版，仍需人工确认",
                        "details": {"count": revision.original_revision_count, "revision_view": "accepted_final"},
                    }
                )

            self._stage(run_id, "source_extraction", "按 OOXML 原始顺序提取段落、表格、编号和页眉页脚")
            blocks, statistics = extract_source_blocks(revision.accepted_path)
            block_ids = self.db.insert_blocks(run_id, blocks)

            self._stage(run_id, "structure_analysis", f"基于 {len(blocks)} 个 Source Block 构建 Node Tree")
            nodes = build_nodes(blocks)
            node_ids, block_to_node = self.db.insert_nodes(document_id, run_id, nodes, block_ids)

            self._stage(run_id, "metadata_extraction", "提取标题、文号、日期、文种和收文对象候选")
            fields, confirmed = extract_metadata(blocks, source_path.name)
            self.db.insert_fields(run_id, fields, block_ids, block_to_node)
            document_updates = {
                key: value
                for key, value in confirmed.items()
                if key
                in {
                    "title",
                    "document_code",
                    "document_type",
                    "issuing_org",
                    "addressee_text",
                    "publish_date",
                    "effective_date",
                    "expiry_date",
                    "status",
                    "owner_department",
                    "authority_level",
                    "version",
                    "confidentiality_level",
                }
            }
            if document_updates:
                self.db.update_document(document_id, **document_updates)

            self._stage(run_id, "structure_validation", "计算结构连续性和来源覆盖率")
            structure_issues, metrics = validate_structure(
                blocks,
                nodes,
                statistics,
                # 默认准入表示图片只告警留痕，不应仅因公章使 ParseRun 卡在待审核。
                image_issue_severity="warning" if self.config.allow_images else "review",
                character_error_threshold=self.config.character_error_threshold,
                character_review_threshold=self.config.character_review_threshold,
            )
            all_issues.extend(structure_issues)

            mapped_count = 0
            unmapped_count = 0
            page_mapping_coverage: float | None = None
            if self.config.render_pdf:
                self._stage(run_id, "pdf_render", "调用本地 Word/docx2pdf 或服务器 LibreOffice 生成 PDF")
                pdf_name = f"{source_path.stem}__{validation.checksum[:12]}.pdf"
                try:
                    render = render_docx_to_pdf(
                        revision.accepted_path,
                        self.pdf_dir / pdf_name,
                        engine=self.config.render_engine,
                        libreoffice_path=self.config.libreoffice_path,
                    )
                    self.db.update_run(
                        run_id,
                        render_engine=render.engine,
                        render_engine_version=render.engine_version,
                        render_os=render.operating_system,
                        page_count=render.page_count,
                        pdf_path=self._stored_path(render.pdf_path),
                        pdf_checksum=render.pdf_checksum,
                        render_source_checksum=revision.accepted_checksum,
                        font_environment_hash=font_environment_hash(),
                    )
                    self._stage(run_id, "page_mapping", f"对齐 {render.page_count} 页 PDF 与 Source Block")
                    page_mapping = map_blocks_to_pdf_pages(render.pdf_path, blocks, block_ids)
                    self.db.update_block_pages(page_mapping.mappings)
                    self.db.inherit_child_block_pages(run_id)
                    self.db.update_node_pages(run_id)
                    all_issues.extend(page_mapping.issues)
                    mapped_count = page_mapping.mapped_count
                    unmapped_count = page_mapping.unmapped_count
                    page_mapping_coverage = page_mapping.coverage
                except Exception as exc:
                    all_issues.append(
                        {
                            "stage": "pdf_render",
                            "issue_code": "PDF_RENDER_OR_MAPPING_FAILED",
                            "severity": "review",
                            "message": "PDF 渲染或页码映射失败，Node 页码保持为空",
                            "details": {"error": str(exc)},
                        }
                    )
            else:
                all_issues.append(
                    {
                        "stage": "pdf_render",
                        "issue_code": "PDF_RENDER_SKIPPED",
                        "severity": "warning",
                        "message": "本次运行关闭 PDF 渲染，Node 页码保持为空",
                    }
                )

            self.db.insert_issues(run_id, all_issues, block_ids, node_ids)
            has_error = any(issue["severity"] == "error" for issue in all_issues)
            pending_fields = [field for field in fields if field.get("review_status") != "confirmed"]
            pending_nodes = [node for node in nodes if node.get("review_status") != "confirmed"]
            needs_review = (
                any(issue["severity"] == "review" for issue in all_issues)
                or bool(pending_fields)
                or bool(pending_nodes)
            )
            status = "failed" if has_error else ("review_required" if needs_review else "succeeded")
            # 无质量问题只代表可以提交，不等于已经完成人工批准。
            review_status = "required"
            run_review_status = "pending" if needs_review or has_error else "ready_for_approval"
            elapsed = time.perf_counter() - started
            self.db.update_run(
                run_id,
                status=status,
                current_stage="completed",
                mapped_block_count=mapped_count,
                unmapped_block_count=unmapped_count or int(metrics["unmapped_block_count"]),
                page_mapping_coverage=page_mapping_coverage,
                character_coverage=metrics["character_coverage"],
                block_coverage=metrics["block_coverage"],
                table_cell_coverage=metrics["table_cell_coverage"],
                review_status=run_review_status,
                finished_at=utc_now(),
                elapsed_seconds=elapsed,
            )
            document_state = {
                "parser_status": status,
                "review_status": review_status,
                "current_parse_run_id": run_id,
                "latest_parse_run_id": run_id,
            }
            self.db.update_document(document_id, **document_state)
            summary = self.db.run_summary(run_id)
            return summary
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.db.update_run(
                run_id,
                status="failed",
                current_stage="exception",
                finished_at=utc_now(),
                elapsed_seconds=elapsed,
                error_code="PIPELINE_EXCEPTION",
                error_message=str(exc),
                review_status="pending",
            )
            self.db.update_document(
                document_id,
                parser_status="failed",
                review_status="required",
                current_parse_run_id=run_id,
                latest_parse_run_id=run_id,
            )
            issue = {
                "stage": "exception",
                "issue_code": "PIPELINE_EXCEPTION",
                "severity": "error",
                "message": "解析流水线发生未处理异常",
                "details": {"error": str(exc), "traceback": traceback.format_exc(limit=8)},
            }
            self.db.insert_issues(run_id, [issue], block_ids, node_ids)
            summary = self.db.run_summary(run_id)
            return summary

    def _stored_path(self, path: Path) -> str:
        """只允许数据库保存知识数据根目录内的相对路径。"""

        resolved = path.resolve()
        try:
            return resolved.relative_to(self.output_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"文件不在知识数据根目录内：{resolved}") from exc
