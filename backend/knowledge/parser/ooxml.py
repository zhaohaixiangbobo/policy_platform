"""DOCX/OOXML 读取与修订最终版处理。

该文件直接读取 DOCX ZIP/XML，以保留段落、表格、编号、页眉页脚和来源定位；
原始文件始终只读，接受修订时生成新的 accepted_final 副本。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, is_zipfile

from lxml import etree


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
}
W = f"{{{NS['w']}}}"
R = f"{{{NS['r']}}}"

REVISION_TAGS = {
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "pPrChange",
    "rPrChange",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "sectPrChange",
    "numberingChange",
}


@dataclass(slots=True)
class DocxValidation:
    """DOCX 安全校验结果。"""

    checksum: str
    file_size: int
    entry_count: int
    uncompressed_size: int
    image_entries: list[str] = field(default_factory=list)
    external_relationships: list[dict[str, str]] = field(default_factory=list)


class ImageReviewRequiredError(ValueError):
    """DOCX 含图片且尚未获得人工放行。"""

    def __init__(self, path: Path, image_entries: list[str]) -> None:
        self.path = path
        self.image_entries = image_entries
        super().__init__(
            f"DOCX 含 {len(image_entries)} 个图片媒体文件，当前 --no-allow-images 严格模式已拦截：{path.name}"
        )


@dataclass(slots=True)
class RevisionResult:
    """接受修订后的输出信息。"""

    accepted_path: Path
    original_revision_count: int
    accepted_checksum: str
    engine: str = "ooxml_transform"
    engine_version: str = "1"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_docx(
    path: Path,
    *,
    max_entries: int = 5000,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
    max_compression_ratio: float = 200.0,
) -> DocxValidation:
    """执行格式、结构和压缩包安全校验。"""

    path = path.resolve()
    if path.suffix.lower() != ".docx":
        raise ValueError("当前解析器只允许 .docx 文件")
    if not path.is_file() or not is_zipfile(path):
        raise ValueError("文件不是有效的 DOCX ZIP 包")

    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            image_entries = sorted(
                name
                for name in names
                if name.startswith("word/media/") and not name.endswith("/")
            )
            required = {"[Content_Types].xml", "word/document.xml"}
            missing = sorted(required - names)
            if missing:
                raise ValueError(f"DOCX 缺少关键部件: {', '.join(missing)}")
            if len(infos) > max_entries:
                raise ValueError(f"DOCX 条目数超过限制: {len(infos)} > {max_entries}")

            total_uncompressed = sum(item.file_size for item in infos)
            total_compressed = sum(max(item.compress_size, 1) for item in infos)
            if total_uncompressed > max_uncompressed_bytes:
                raise ValueError("DOCX 解压后大小超过安全限制")
            if total_uncompressed / total_compressed > max_compression_ratio:
                raise ValueError("DOCX 压缩比异常，疑似压缩炸弹")

            external: list[dict[str, str]] = []
            for name in names:
                if not name.endswith(".rels"):
                    continue
                root = etree.fromstring(archive.read(name))
                for relation in root.findall("rel:Relationship", NS):
                    if relation.get("TargetMode") == "External":
                        external.append(
                            {
                                "part": name,
                                "id": relation.get("Id", ""),
                                "target": relation.get("Target", ""),
                            }
                        )
    except BadZipFile as exc:
        raise ValueError("DOCX ZIP 结构损坏") from exc

    return DocxValidation(
        checksum=sha256_file(path),
        file_size=path.stat().st_size,
        entry_count=len(infos),
        uncompressed_size=total_uncompressed,
        image_entries=image_entries,
        external_relationships=external,
    )


def _xml_word_parts(archive: ZipFile) -> Iterable[str]:
    for name in archive.namelist():
        if name.startswith("word/") and name.endswith(".xml"):
            yield name


def count_revisions(path: Path) -> int:
    """统计所有 Word XML 部件中的修订包装和属性修订。"""

    count = 0
    with ZipFile(path) as archive:
        for name in _xml_word_parts(archive):
            root = etree.fromstring(archive.read(name))
            count += sum(
                1
                for element in root.iter()
                if etree.QName(element).namespace == NS["w"]
                and etree.QName(element).localname in REVISION_TAGS
            )
    return count


def _accept_revisions_in_root(root: etree._Element) -> None:
    """在一个 XML 树中应用 accepted_final 视图。"""

    # 删除内容和移动来源不属于最终版。
    for tag in ("del", "moveFrom"):
        for element in list(root.findall(f".//w:{tag}", NS)):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

    # 插入内容和移动目标保留，去掉修订包装层。
    for tag in ("ins", "moveTo"):
        for element in list(root.findall(f".//w:{tag}", NS)):
            parent = element.getparent()
            if parent is None:
                continue
            position = parent.index(element)
            for child in list(element):
                element.remove(child)
                parent.insert(position, child)
                position += 1
            parent.remove(element)

    # 属性修订的 *Change 元素保存的是旧属性；最终版只需移除历史快照。
    for element in list(root.iter()):
        qname = etree.QName(element)
        if qname.namespace == NS["w"] and qname.localname in REVISION_TAGS:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)


def create_accepted_final(original: Path, output: Path) -> RevisionResult:
    """生成接受全部修订后的 DOCX 副本，不覆盖原文件。"""

    original = original.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    revision_count = count_revisions(original)

    if revision_count == 0:
        shutil.copy2(original, output)
    else:
        temporary = output.with_suffix(output.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        with ZipFile(original) as source, ZipFile(temporary, "w", ZIP_DEFLATED) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    root = etree.fromstring(payload)
                    _accept_revisions_in_root(root)
                    payload = etree.tostring(
                        root,
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
                target.writestr(info, payload)
        temporary.replace(output)

    # 二次检查确保 accepted_final 中不再含未处理修订。
    remaining = count_revisions(output)
    if remaining:
        raise ValueError(f"接受修订后仍有 {remaining} 个未处理修订元素")
    return RevisionResult(
        accepted_path=output,
        original_revision_count=revision_count,
        accepted_checksum=sha256_file(output),
    )


def _safe_clean_text(text: str) -> tuple[str, list[str]]:
    """执行不会覆盖 raw_text 的保守空白清理。"""

    actions: list[str] = []
    clean = text.replace("\u00a0", " ").replace("\u3000", " ")
    if clean != text:
        actions.append("normalize_non_breaking_space")
    normalized = unicodedata.normalize("NFC", clean)
    if normalized != clean:
        actions.append("unicode_nfc")
    clean = normalized
    collapsed = re.sub(r"[ \t]+", " ", clean).strip()
    if collapsed != clean:
        actions.append("collapse_horizontal_whitespace")
    return collapsed, actions


def _inside_textbox(element: etree._Element) -> bool:
    """判断节点是否位于 Word 文本框内容中。"""

    return any(ancestor.tag == f"{W}txbxContent" for ancestor in element.iterancestors())


def _text_of(element: etree._Element, *, exclude_textboxes: bool = False) -> str:
    """提取最终版可见文字，保留制表符和换行语义。

    文本框会被单独保存为 Source Block；提取宿主段落或表格时应排除文本框，
    避免同一段文字既出现在宿主 Block 又出现在 textbox Block。
    """

    fragments: list[str] = []
    for child in element.iter():
        if exclude_textboxes and _inside_textbox(child):
            continue
        qname = etree.QName(child)
        if qname.namespace != NS["w"]:
            continue
        if qname.localname == "t" and child.text:
            fragments.append(child.text)
        elif qname.localname == "tab":
            fragments.append("\t")
        elif qname.localname in {"br", "cr"}:
            fragments.append("\n")
    return "".join(fragments)


def _textbox_payloads(element: etree._Element) -> list[dict[str, Any]]:
    """提取宿主对象中的文本框文字和页码域特征。"""

    payloads: list[dict[str, Any]] = []
    for index, textbox in enumerate(element.findall(".//w:txbxContent", NS), start=1):
        text = _text_of(textbox)
        field_codes = [
            value.strip()
            for item in textbox.findall(".//w:instrText", NS)
            if (value := (item.text or "").strip())
        ]
        normalized = re.sub(r"\s+", "", text)
        field_text = " ".join(field_codes).upper()
        is_page_number = bool(
            re.fullmatch(r"[-—–]?\d+[-—–]?", normalized)
            or re.search(r"\b(?:PAGE|NUMPAGES)\b", field_text)
        )
        payloads.append(
            {
                "textbox_index": index,
                "text": text,
                "field_codes": field_codes,
                "is_page_number": is_page_number,
            }
        )
    return payloads


def _is_masthead_textbox(text: str, part_order: int) -> bool:
    """识别公文首页版头文本框，避免把装饰性机关名称写入正文树。

    规则刻意保持保守：仅检查正文前 12 个结构位置；除“文件”二字外，机构名称
    必须是短文本、以常见机构后缀结尾，且不能出现正文语义词或句末标点。
    """

    if part_order > 12:
        return False
    normalized = re.sub(r"\s+", "", text)
    if normalized == "文件":
        return True
    if not normalized or len(normalized) > 80:
        return False
    if re.search(r"[。！？；：]", normalized):
        return False
    if re.search(r"本办法|本规定|负责|解释|执行|通知|附件|关于|印发|由", normalized):
        return False
    return bool(
        re.search(
            r"(?:专卖局|总公司|分公司|公司|办公室|委员会|人民政府|中心|工会|协会|学会)$",
            normalized,
        )
    )


def _is_masthead_paragraph(text: str, part_order: int) -> bool:
    """识别“某某机关文件”形式的普通段落版头。"""

    normalized = re.sub(r"\s+", "", text)
    if not normalized.endswith("文件"):
        return False
    return _is_masthead_textbox(normalized[: -len("文件")], part_order)


def _textbox_exclusion(
    part_type: str,
    is_page_number: bool,
    text: str,
    part_order: int,
) -> tuple[str, str, str]:
    """返回文本框的排除角色、原因和统计分类。"""

    if part_type == "footer" and is_page_number:
        return "page_number", "页脚数字或页码域文本框", "page_number_textboxes"
    if part_type == "document":
        if _is_masthead_textbox(text, part_order):
            return (
                "masthead",
                "公文首页装饰性版头不进入制度正文、Chunk 或检索",
                "masthead_textboxes",
            )
        return (
            "textbox_review",
            "正文文本框需人工确认后决定是否进入正文树",
            "body_textboxes",
        )
    return part_type, f"{part_type} 文本框单独保留，不进入制度正文", "auxiliary_textboxes"


def _style_map(archive: ZipFile) -> dict[str, dict[str, Any]]:
    if "word/styles.xml" not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read("word/styles.xml"))
    result: dict[str, dict[str, Any]] = {}
    for style in root.findall("w:style", NS):
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name = style.find("w:name", NS)
        ppr = style.find("w:pPr", NS)
        rpr = style.find("w:rPr", NS)
        size = rpr.find("w:sz", NS) if rpr is not None else None
        outline = ppr.find("w:outlineLvl", NS) if ppr is not None else None
        result[style_id] = {
            "name": name.get(f"{W}val") if name is not None else style_id,
            "font_size_half_points": int(size.get(f"{W}val")) if size is not None else None,
            "bold": rpr.find("w:b", NS) is not None if rpr is not None else False,
            "outline_level": int(outline.get(f"{W}val")) if outline is not None else None,
        }
    return result


class NumberingResolver:
    """读取 numbering.xml，并为原生列表生成可审计的显示编号。"""

    def __init__(self, archive: ZipFile) -> None:
        self.num_to_abstract: dict[str, str] = {}
        self.levels: dict[tuple[str, int], dict[str, Any]] = {}
        self.counters: dict[tuple[str, int], int] = defaultdict(int)
        if "word/numbering.xml" not in archive.namelist():
            return
        root = etree.fromstring(archive.read("word/numbering.xml"))
        for num in root.findall("w:num", NS):
            num_id = num.get(f"{W}numId")
            abstract = num.find("w:abstractNumId", NS)
            if num_id and abstract is not None:
                self.num_to_abstract[num_id] = abstract.get(f"{W}val", "")
        for abstract in root.findall("w:abstractNum", NS):
            abstract_id = abstract.get(f"{W}abstractNumId", "")
            for level in abstract.findall("w:lvl", NS):
                ilvl = int(level.get(f"{W}ilvl", "0"))
                start = level.find("w:start", NS)
                fmt = level.find("w:numFmt", NS)
                text = level.find("w:lvlText", NS)
                self.levels[(abstract_id, ilvl)] = {
                    "start": int(start.get(f"{W}val", "1")) if start is not None else 1,
                    "format": fmt.get(f"{W}val", "decimal") if fmt is not None else "decimal",
                    "text": text.get(f"{W}val", f"%{ilvl + 1}.") if text is not None else f"%{ilvl + 1}.",
                }

    def next(self, num_id: str | None, ilvl: int | None) -> str | None:
        if num_id is None or ilvl is None:
            return None
        abstract = self.num_to_abstract.get(num_id)
        if abstract is None:
            return None
        definition = self.levels.get((abstract, ilvl), {"start": 1, "format": "decimal", "text": f"%{ilvl + 1}."})
        key = (num_id, ilvl)
        if self.counters[key] == 0:
            self.counters[key] = int(definition["start"])
        else:
            self.counters[key] += 1
        for deeper in range(ilvl + 1, 9):
            self.counters.pop((num_id, deeper), None)

        rendered = str(definition["text"])
        for level_index in range(9):
            placeholder = f"%{level_index + 1}"
            if placeholder not in rendered:
                continue
            value = self.counters.get((num_id, level_index), 0)
            level_definition = self.levels.get((abstract, level_index), {"format": "decimal"})
            rendered = rendered.replace(placeholder, _format_number(value, level_definition["format"]))
        return rendered


def _format_number(value: int, fmt: str) -> str:
    if value <= 0:
        return "0"
    if fmt in {"chineseCounting", "chineseCountingThousand", "ideographTraditional"}:
        return _chinese_number(value)
    if fmt == "upperLetter" and value <= 26:
        return chr(64 + value)
    if fmt == "lowerLetter" and value <= 26:
        return chr(96 + value)
    if fmt in {"upperRoman", "lowerRoman"}:
        roman = _roman_number(value)
        return roman if fmt == "upperRoman" else roman.lower()
    return str(value)


def _roman_number(value: int) -> str:
    pairs = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    result: list[str] = []
    for number, symbol in pairs:
        while value >= number:
            result.append(symbol)
            value -= number
    return "".join(result)


def _chinese_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    if value < 20:
        return "十" + (digits[value % 10] if value % 10 else "")
    if value < 100:
        return digits[value // 10] + "十" + (digits[value % 10] if value % 10 else "")
    return str(value)


def _paragraph_properties(
    paragraph: etree._Element,
    styles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ppr = paragraph.find("w:pPr", NS)
    style_id: str | None = None
    num_id: str | None = None
    ilvl: int | None = None
    alignment: str | None = None
    indent: dict[str, str] = {}
    outline_level: int | None = None
    if ppr is not None:
        pstyle = ppr.find("w:pStyle", NS)
        style_id = pstyle.get(f"{W}val") if pstyle is not None else None
        numpr = ppr.find("w:numPr", NS)
        if numpr is not None:
            num = numpr.find("w:numId", NS)
            level = numpr.find("w:ilvl", NS)
            num_id = num.get(f"{W}val") if num is not None else None
            ilvl = int(level.get(f"{W}val", "0")) if level is not None else 0
        jc = ppr.find("w:jc", NS)
        alignment = jc.get(f"{W}val") if jc is not None else None
        ind = ppr.find("w:ind", NS)
        if ind is not None:
            indent = {etree.QName(key).localname: value for key, value in ind.attrib.items()}
        outline = ppr.find("w:outlineLvl", NS)
        outline_level = int(outline.get(f"{W}val")) if outline is not None else None

    run_sizes: list[int] = []
    run_bold = False
    fonts: set[str] = set()
    for run in paragraph.findall(".//w:r", NS):
        rpr = run.find("w:rPr", NS)
        if rpr is None:
            continue
        size = rpr.find("w:sz", NS)
        if size is not None and size.get(f"{W}val", "").isdigit():
            run_sizes.append(int(size.get(f"{W}val")))
        if rpr.find("w:b", NS) is not None:
            run_bold = True
        run_fonts = rpr.find("w:rFonts", NS)
        if run_fonts is not None:
            fonts.update(value for value in run_fonts.attrib.values() if value)

    style = styles.get(style_id or "", {})
    drawing_ids = [
        item.get(f"{R}embed")
        for item in paragraph.findall(".//a:blip", NS)
        if item.get(f"{R}embed")
    ]
    vml_ids = [
        item.get(f"{R}id")
        for item in paragraph.findall(".//v:imagedata", NS)
        if item.get(f"{R}id")
    ]
    # 同一图片可能同时保留兼容性标记，按出现顺序去重。
    image_relationship_ids = list(dict.fromkeys([*drawing_ids, *vml_ids]))

    return {
        "style_id": style_id,
        "style_name": style.get("name", style_id),
        "numbering_id": num_id,
        "numbering_level": ilvl,
        "alignment": alignment,
        "indent": indent,
        "outline_level": outline_level if outline_level is not None else style.get("outline_level"),
        "font_size_half_points": max(run_sizes) if run_sizes else style.get("font_size_half_points"),
        "bold": run_bold or bool(style.get("bold")),
        "fonts": sorted(fonts),
        "manual_page_break": bool(paragraph.findall(".//w:br[@w:type='page']", NS)),
        "last_rendered_page_break": bool(paragraph.findall(".//w:lastRenderedPageBreak", NS)),
        "image_relationship_ids": image_relationship_ids,
        "textbox_count": len(paragraph.findall(".//w:txbxContent", NS)),
    }


def _table_data(table: etree._Element) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    for row_index, row in enumerate(table.findall("w:tr", NS)):
        cells: list[dict[str, Any]] = []
        for column_index, cell in enumerate(row.findall("w:tc", NS)):
            tcpr = cell.find("w:tcPr", NS)
            grid_span = tcpr.find("w:gridSpan", NS) if tcpr is not None else None
            vmerge = tcpr.find("w:vMerge", NS) if tcpr is not None else None
            text = "\n".join(
                value
                for paragraph in cell.findall(".//w:p", NS)
                if (value := _text_of(paragraph, exclude_textboxes=True).strip())
            )
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "text": text,
                    "grid_span": int(grid_span.get(f"{W}val", "1")) if grid_span is not None else 1,
                    "vertical_merge": vmerge.get(f"{W}val", "continue") if vmerge is not None else None,
                }
            )
        rows.append(cells)
    return {"rows": rows, "row_count": len(rows), "cell_count": sum(len(row) for row in rows)}


def _part_relationships(archive: ZipFile, part_name: str) -> dict[str, dict[str, str]]:
    part_path = Path(part_name)
    rels_name = str(part_path.parent / "_rels" / f"{part_path.name}.rels").replace("\\", "/")
    if rels_name not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(rels_name))
    return {
        relation.get("Id", ""): {
            "target": relation.get("Target", ""),
            "target_mode": relation.get("TargetMode", "Internal"),
            "type": relation.get("Type", ""),
        }
        for relation in root.findall("rel:Relationship", NS)
    }


def _iter_part_blocks(root: etree._Element) -> Iterable[etree._Element]:
    """按 XML 顺序展开正文、内容控件等容器中的段落和表格。"""

    body = root.find("w:body", NS)
    container = body if body is not None else root

    def walk(parent: etree._Element) -> Iterable[etree._Element]:
        for child in parent:
            local = etree.QName(child).localname
            namespace = etree.QName(child).namespace
            if namespace == NS["w"] and local in {"p", "tbl"}:
                yield child
            elif namespace == NS["w"] and local in {"sdt", "sdtContent", "customXml"}:
                yield from walk(child)

    yield from walk(container)


def extract_source_blocks(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从 accepted_final DOCX 提取有序 Source Block。"""

    blocks: list[dict[str, Any]] = []
    statistics: dict[str, Any] = {
        "comments": 0,
        "textboxes": 0,
        "body_textboxes": 0,
        "masthead_textboxes": 0,
        "masthead_paragraphs": 0,
        "page_number_textboxes": 0,
        "auxiliary_textboxes": 0,
        "images": 0,
        "footnotes": 0,
        "endnotes": 0,
    }
    with ZipFile(path) as archive:
        styles = _style_map(archive)
        numbering = NumberingResolver(archive)
        part_names = ["word/document.xml"]
        part_names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/header\d+\.xml", name)))
        part_names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/footer\d+\.xml", name)))
        for optional in ("word/footnotes.xml", "word/endnotes.xml"):
            if optional in archive.namelist():
                part_names.append(optional)

        if "word/comments.xml" in archive.namelist():
            comments_root = etree.fromstring(archive.read("word/comments.xml"))
            statistics["comments"] = len(comments_root.findall("w:comment", NS))

        part_counters: dict[str, int] = defaultdict(int)
        global_counter = 0
        for part_name in part_names:
            root = etree.fromstring(archive.read(part_name))
            relationships = _part_relationships(archive, part_name)
            if part_name == "word/document.xml":
                part_type = "document"
            elif "header" in part_name:
                part_type = "header"
            elif "footer" in part_name:
                part_type = "footer"
            elif "footnotes" in part_name:
                part_type = "footnote"
            else:
                part_type = "endnote"

            elements = list(_iter_part_blocks(root))
            if part_type in {"footnote", "endnote"}:
                # 脚注部件没有 body，直接按段落顺序提取并跳过内置分隔符空段。
                elements = list(root.findall(".//w:p", NS))

            for element in elements:
                global_counter += 1
                part_counters[part_type] += 1
                temp_key = f"block-{global_counter}"
                locator = {
                    "part": part_name,
                    "xml_path": element.getroottree().getpath(element),
                    "part_order": part_counters[part_type],
                }
                if etree.QName(element).localname == "p":
                    textboxes = _textbox_payloads(element)
                    raw_text = _text_of(element, exclude_textboxes=True)
                    clean_text, actions = _safe_clean_text(raw_text)
                    properties = _paragraph_properties(element, styles)
                    display_number = numbering.next(
                        properties.get("numbering_id"), properties.get("numbering_level")
                    )
                    statistics["textboxes"] += len(textboxes)
                    statistics["images"] += len(properties["image_relationship_ids"])
                    excluded_role = "none"
                    reason = None
                    if part_type == "header":
                        excluded_role, reason = "header", "页眉不进入制度正文"
                    elif part_type == "footer":
                        excluded_role, reason = "footer", "页脚不进入制度正文"
                    elif part_type in {"footnote", "endnote"}:
                        excluded_role, reason = part_type, "脚注尾注单独保留，MVP 不进入正文树"
                        statistics[f"{part_type}s"] += 1
                    elif part_type == "document" and _is_masthead_paragraph(
                        clean_text, part_counters[part_type]
                    ):
                        excluded_role, reason = (
                            "masthead",
                            "公文首页装饰性版头不进入制度正文、Chunk 或检索",
                        )
                        statistics["masthead_paragraphs"] += 1
                    elif re.fullmatch(r"[-—–]?\s*\d+\s*[-—–]?", clean_text):
                        excluded_role, reason = "page_number", "独立页码文本"

                    blocks.append(
                        {
                            "temp_key": temp_key,
                            "part_type": part_type,
                            "block_type": "paragraph",
                            "order_no": part_counters[part_type],
                            "raw_text": raw_text,
                            "clean_text": clean_text,
                            "style_name": properties.get("style_name"),
                            "numbering_id": properties.get("numbering_id"),
                            "numbering_level": properties.get("numbering_level"),
                            "display_number": display_number,
                            "properties": properties,
                            "source_locator": locator,
                            "excluded_role": excluded_role,
                            "exclusion_reason": reason,
                            "normalization_actions": actions,
                        }
                    )

                    for image_index, relation_id in enumerate(properties["image_relationship_ids"], start=1):
                        global_counter += 1
                        relation = relationships.get(relation_id, {})
                        blocks.append(
                            {
                                "temp_key": f"block-{global_counter}",
                                "parent_temp_key": temp_key,
                                "part_type": part_type,
                                "block_type": "image",
                                "order_no": part_counters[part_type],
                                "raw_text": "",
                                "clean_text": "",
                                "properties": {"relationship_id": relation_id, **relation},
                                "source_locator": {**locator, "image_index": image_index},
                                "excluded_role": "image_review" if part_type == "document" else "decorative",
                                "exclusion_reason": (
                                    "正文图片保留媒体关系，当前版本不做 OCR，需人工确认内容"
                                    if part_type == "document"
                                    else "辅助部件图片作为占位和媒体关系保留，当前版本不做 OCR"
                                ),
                                "normalization_actions": [],
                            }
                        )

                    for textbox in textboxes:
                        global_counter += 1
                        textbox_text = textbox["text"]
                        textbox_clean, textbox_actions = _safe_clean_text(textbox_text)
                        role, textbox_reason, statistic_key = _textbox_exclusion(
                            part_type,
                            bool(textbox["is_page_number"]),
                            textbox_clean,
                            part_counters[part_type],
                        )
                        statistics[statistic_key] += 1
                        blocks.append(
                            {
                                "temp_key": f"block-{global_counter}",
                                "parent_temp_key": temp_key,
                                "part_type": part_type,
                                "block_type": "textbox",
                                "order_no": part_counters[part_type],
                                "raw_text": textbox_text,
                                "clean_text": textbox_clean,
                                "properties": {
                                    "field_codes": textbox["field_codes"],
                                    "is_page_number": textbox["is_page_number"],
                                },
                                "source_locator": {
                                    **locator,
                                    "textbox_index": textbox["textbox_index"],
                                },
                                "excluded_role": role,
                                "exclusion_reason": textbox_reason,
                                "normalization_actions": textbox_actions,
                            }
                        )
                else:
                    textboxes = _textbox_payloads(element)
                    statistics["textboxes"] += len(textboxes)
                    table = _table_data(element)
                    row_texts = ["\t".join(cell["text"] for cell in row) for row in table["rows"]]
                    raw_text = "\n".join(row_texts)
                    clean_text, actions = _safe_clean_text(raw_text)
                    blocks.append(
                        {
                            "temp_key": temp_key,
                            "part_type": part_type,
                            "block_type": "table",
                            "order_no": part_counters[part_type],
                            "raw_text": raw_text,
                            "clean_text": clean_text,
                            "properties": table,
                            "source_locator": locator,
                            "excluded_role": "none" if part_type == "document" else part_type,
                            "exclusion_reason": None if part_type == "document" else f"{part_type} 不进入制度正文",
                            "normalization_actions": actions,
                        }
                    )
                    for row in table["rows"]:
                        for cell in row:
                            global_counter += 1
                            cell_text, cell_actions = _safe_clean_text(cell["text"])
                            blocks.append(
                                {
                                    "temp_key": f"block-{global_counter}",
                                    "parent_temp_key": temp_key,
                                    "part_type": part_type,
                                    "block_type": "table_cell",
                                    "order_no": part_counters[part_type],
                                    "raw_text": cell["text"],
                                    "clean_text": cell_text,
                                    "properties": cell,
                                    "source_locator": {
                                        **locator,
                                        "row": cell["row"],
                                        "column": cell["column"],
                                    },
                                    "excluded_role": "table_cell_component",
                                    "exclusion_reason": "由父级 table Block 统一映射，避免覆盖率重复计算",
                                    "normalization_actions": cell_actions,
                                }
                            )

                    for textbox in textboxes:
                        global_counter += 1
                        textbox_text = textbox["text"]
                        textbox_clean, textbox_actions = _safe_clean_text(textbox_text)
                        role, textbox_reason, statistic_key = _textbox_exclusion(
                            part_type,
                            bool(textbox["is_page_number"]),
                            textbox_clean,
                            part_counters[part_type],
                        )
                        statistics[statistic_key] += 1
                        blocks.append(
                            {
                                "temp_key": f"block-{global_counter}",
                                "parent_temp_key": temp_key,
                                "part_type": part_type,
                                "block_type": "textbox",
                                "order_no": part_counters[part_type],
                                "raw_text": textbox_text,
                                "clean_text": textbox_clean,
                                "properties": {
                                    "field_codes": textbox["field_codes"],
                                    "is_page_number": textbox["is_page_number"],
                                },
                                "source_locator": {
                                    **locator,
                                    "textbox_index": textbox["textbox_index"],
                                },
                                "excluded_role": role,
                                "exclusion_reason": textbox_reason,
                                "normalization_actions": textbox_actions,
                            }
                        )

    return blocks, statistics
