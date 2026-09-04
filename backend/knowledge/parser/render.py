"""文件说明：提供可配置的无界面 DOCX PDF 渲染与页码对齐。

默认 ``auto_headless`` 优先调用 LibreOffice Headless，未安装时才回退到隐藏的
Microsoft Word。生产服务器可将引擎固定为 ``libreoffice``，避免启动桌面应用。
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .ooxml import sha256_file


@dataclass(slots=True)
class RenderResult:
    pdf_path: Path
    engine: str
    engine_version: str
    operating_system: str
    page_count: int
    pdf_checksum: str


@dataclass(slots=True)
class PageMappingResult:
    mappings: dict[int, tuple[int | None, int | None, float]]
    mapped_count: int
    unmapped_count: int
    coverage: float
    issues: list[dict[str, Any]]


def render_docx_to_pdf(
    docx_path: Path,
    pdf_path: Path,
    *,
    engine: str = "auto_headless",
    libreoffice_path: str | None = None,
) -> RenderResult:
    """按明确配置选择渲染器；自动模式始终优先无界面 LibreOffice。"""

    docx_path = docx_path.resolve()
    pdf_path = pdf_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()

    selected = engine.strip().lower()
    if selected not in {"auto_headless", "libreoffice", "word"}:
        raise ValueError("DOCX渲染引擎只允许 auto_headless/libreoffice/word")

    soffice = _resolve_libreoffice(libreoffice_path)
    if selected in {"auto_headless", "libreoffice"} and soffice:
        engine_version = _render_with_libreoffice(soffice, docx_path, pdf_path)
        engine_name = "libreoffice_headless"
    elif selected == "libreoffice":
        raise RuntimeError("已固定使用LibreOffice，但未找到soffice可执行文件")
    elif os.name == "nt" and importlib.util.find_spec("docx2pdf"):
        from docx2pdf import convert
        import pythoncom

        # docx2pdf 连续处理多个文件时不会替调用线程初始化 COM，需逐次显式管理。
        pythoncom.CoInitialize()
        try:
            convert(str(docx_path), str(pdf_path))
            engine_version = _word_version() or "unknown"
        finally:
            pythoncom.CoUninitialize()
        engine_name = "ms_word_docx2pdf"
    elif os.name == "nt" and importlib.util.find_spec("win32com.client"):
        engine_version = _render_with_word_com(docx_path, pdf_path)
        engine_name = "ms_word_com"
    else:
        raise RuntimeError("未找到可用的LibreOffice Headless或Microsoft Word渲染器")

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError("PDF 渲染完成但没有生成有效文件")
    page_count = len(PdfReader(str(pdf_path)).pages)
    return RenderResult(
        pdf_path=pdf_path,
        engine=engine_name,
        engine_version=engine_version,
        operating_system=f"{platform.system()} {platform.release()}",
        page_count=page_count,
        pdf_checksum=sha256_file(pdf_path),
    )


def _resolve_libreoffice(configured_path: str | None) -> str | None:
    """解析显式路径、PATH和Windows常见安装位置。"""

    candidates = [configured_path, shutil.which("soffice"), shutil.which("libreoffice")]
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ]
        )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def _render_with_libreoffice(soffice: str, docx_path: Path, pdf_path: Path) -> str:
    """使用独立用户配置目录执行无界面转换，避免并发锁住Office配置。"""

    profile_dir = pdf_path.parent / f".lo-profile-{os.getpid()}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_path.parent),
                str(docx_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        generated = pdf_path.parent / f"{docx_path.stem}.pdf"
        if completed.returncode != 0 or not generated.exists():
            raise RuntimeError(f"LibreOffice转换失败: {completed.stderr or completed.stdout}")
        if generated != pdf_path:
            generated.replace(pdf_path)
        version = subprocess.run([soffice, "--version"], capture_output=True, text=True, check=False)
        return (version.stdout or version.stderr).strip() or "unknown"
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


def _word_version() -> str | None:
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        try:
            return str(word.Version)
        finally:
            word.Quit()
            pythoncom.CoUninitialize()
    except Exception:
        return None


def _render_with_word_com(docx_path: Path, pdf_path: Path) -> str:
    """隐藏调用本机 Word，行为与 docx2pdf 的 Windows 实现等价。"""

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    document = None
    try:
        version = str(word.Version)
        document = word.Documents.Open(str(docx_path), ReadOnly=True, AddToRecentFiles=False)
        document.ExportAsFixedFormat(str(pdf_path), 17)
        return version
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()
        pythoncom.CoUninitialize()


def _pdf_normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("\u00a0", "")


def _ngrams(text: str, width: int = 3) -> set[str]:
    if len(text) <= width:
        return {text} if text else set()
    return {text[index : index + width] for index in range(len(text) - width + 1)}


def _candidate_pages(
    text: str, pages: list[str], current_page: int
) -> tuple[int | None, int | None, float]:
    if not text or not pages:
        return None, None, 0.0
    start_index = max(0, min(current_page, len(pages) - 1))
    search_order = list(range(start_index, min(len(pages), start_index + 5)))
    search_order.extend(index for index in range(len(pages)) if index not in search_order)

    # 优先完整精确匹配，其次允许跨相邻两页。
    exact = [index for index in search_order if text in pages[index]]
    if exact:
        chosen = min((index for index in exact if index >= start_index), default=exact[0])
        confidence = 1.0 if len(exact) == 1 else 0.92
        return chosen + 1, chosen + 1, confidence
    for index in search_order:
        if index + 1 < len(pages) and text in pages[index] + pages[index + 1]:
            return index + 1, index + 2, 0.96

    start_fragment = text[: min(24, len(text))]
    end_fragment = text[-min(24, len(text)) :]
    start_pages = [index for index in search_order if start_fragment in pages[index]]
    if start_pages:
        start = start_pages[0]
        end = next(
            (index for index in range(start, min(len(pages), start + 4)) if end_fragment in pages[index]),
            start,
        )
        return start + 1, end + 1, 0.86 if end >= start else 0.75

    # 最后使用字符三元组覆盖率；低于阈值不写页码。
    text_grams = _ngrams(text)
    if not text_grams:
        return None, None, 0.0
    best_index: int | None = None
    best_score = 0.0
    for index in search_order:
        score = len(text_grams & _ngrams(pages[index])) / len(text_grams)
        if score > best_score:
            best_index, best_score = index, score
    if best_index is not None and best_score >= 0.55:
        return best_index + 1, best_index + 1, min(0.8, best_score)
    return None, None, best_score


def map_blocks_to_pdf_pages(
    pdf_path: Path,
    blocks: list[dict[str, Any]],
    block_ids: dict[str, int],
) -> PageMappingResult:
    """将正文 Block 按原文顺序映射到 PDF 页面。"""

    reader = PdfReader(str(pdf_path))
    pages = [_pdf_normalize(page.extract_text() or "") for page in reader.pages]
    eligible = [
        block
        for block in blocks
        if block["part_type"] == "document"
        and block["excluded_role"] == "none"
        and block["block_type"] in {"paragraph", "table"}
        and block["clean_text"]
    ]
    mappings: dict[int, tuple[int | None, int | None, float]] = {}
    issues: list[dict[str, Any]] = []
    current_page = 0
    mapped = 0
    for block in eligible:
        normalized = _pdf_normalize(block["clean_text"])
        page_start, page_end, confidence = _candidate_pages(normalized, pages, current_page)
        block_id = block_ids[block["temp_key"]]
        mappings[block_id] = (page_start, page_end, confidence)
        if page_start is not None:
            mapped += 1
            current_page = max(current_page, page_start - 1)
        else:
            issues.append(
                {
                    "stage": "page_mapping",
                    "issue_code": "PAGE_MAPPING_AMBIGUOUS",
                    "severity": "review",
                    "message": "Source Block 无法可靠映射到 PDF 页码",
                    "source_block_key": block["temp_key"],
                    "details": {"confidence": round(confidence, 4), "text_preview": block["clean_text"][:80]},
                }
            )
    total = len(eligible)
    return PageMappingResult(
        mappings=mappings,
        mapped_count=mapped,
        unmapped_count=total - mapped,
        coverage=mapped / total if total else 1.0,
        issues=issues,
    )


def font_environment_hash() -> str:
    """记录一个轻量环境摘要，用于识别页码结果是否来自同一渲染环境。"""

    value = f"{platform.system()}|{platform.release()}|{platform.machine()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
