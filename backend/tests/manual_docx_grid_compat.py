"""文件说明：DOCX文本网格/行距兼容性隔离实验（人工验收工具，不是后端运行依赖）。

只读取`var/font-review/adapted-20261011`中已登记哈希的样本副本，在新的工作目录下生成
临时变体；不修改原始制度文件、不访问数据库、不覆盖任何已发布PDF。

子命令：
- prepare：校验样本哈希，生成DOCX变体（取消网格对齐/取消文档网格/调整网格/精确行距不对齐）。
- patch-fodt：对LibreOffice导出的FODT修改文档级兼容设置（标点压缩），生成FODT变体。
- measure：用PyMuPDF比较各变体PDF与Word基准PDF的页数、行距、标题、分页和文本完整性。
- prepare-decl：只改word/settings.xml的标点压缩声明，生成“无声明/不压缩”对照DOCX（UNO验证用）。
- compare：逐页比较两份PDF的文本是否完全一致，用于判断两条转换路径的排版是否等价。
PDF转换由隔离容器内的soffice完成，命令见docs/testing中的排查报告。
"""

from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import re
import shutil
import statistics
import zipfile
from pathlib import Path

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
# 两份样本的正文字号（pt），用于从PDF中筛选正文行。
BODY_SIZE = {1: 16.0, 2: 14.0}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_snap(ppr: etree._Element) -> None:
    """在段落属性中写入snapToGrid=0；按OOXML顺序放在spacing之前。"""

    node = ppr.find("w:snapToGrid", NS)
    if node is None:
        node = etree.Element(W + "snapToGrid")
        anchor = ppr.find("w:spacing", NS)
        if anchor is not None:
            anchor.addprevious(node)
        else:
            ppr.append(node)
    node.set(W + "val", "0")


def _ensure_ppr(paragraph: etree._Element) -> etree._Element:
    ppr = paragraph.find("w:pPr", NS)
    if ppr is None:
        ppr = etree.Element(W + "pPr")
        paragraph.insert(0, ppr)
    return ppr


def _exact_paragraph(paragraph: etree._Element) -> bool:
    """判断段落直接格式是否为精确行距；两份样本均无段落样式行距，直接格式即生效值。"""

    spacing = paragraph.find("w:pPr/w:spacing", NS)
    return spacing is not None and spacing.get(W + "lineRule") == "exact"


def transform(xml: bytes, variant: str) -> tuple[bytes, int]:
    """按变体修改document.xml，返回新XML与修改节点数。"""

    root = etree.fromstring(xml)
    changed = 0
    if variant == "v1-nosnap-all":
        for paragraph in root.iter(W + "p"):
            _set_snap(_ensure_ppr(paragraph))
            changed += 1
    elif variant == "v2-nogrid":
        for grid in root.iter(W + "docGrid"):
            grid.set(W + "type", "default")
            changed += 1
    elif variant == "v3-pitch420":
        # 网格行高调整为与精确行距相同的21pt（420 twips）。
        for grid in root.iter(W + "docGrid"):
            grid.set(W + "linePitch", "420")
            changed += 1
    elif variant == "v4-exact-nosnap":
        # 模拟Word语义：仅精确行距段落不对齐网格，单倍/多倍行距保持网格对齐。
        for paragraph in root.iter(W + "p"):
            if _exact_paragraph(paragraph):
                _set_snap(paragraph.find("w:pPr", NS))
                changed += 1
    elif variant != "v0-baseline":
        raise ValueError(variant)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), changed


def prepare(args: argparse.Namespace) -> None:
    source_dir, work = args.source.resolve(), args.work.resolve()
    report = json.loads(
        (source_dir / "font-report.json").read_text(encoding="utf-8"))
    docx_dir = work / "docx"
    docx_dir.mkdir(parents=True, exist_ok=False)
    manifest = []
    for number, sample in enumerate(report["samples"], 1):
        source = source_dir / f"sample-{number}.docx"
        digest = sha256(source)
        if digest != sample["sha256"]:
            raise ValueError(f"样本{number}哈希与登记不一致")
        variants = ["v0-baseline", "v1-nosnap-all",
                    "v2-nogrid", "v4-exact-nosnap"]
        if number == 2:
            variants.insert(3, "v3-pitch420")
        for variant in variants:
            target = docx_dir / f"s{number}-{variant}.docx"
            with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
                changed = 0
                for item in src.infolist():
                    data = src.read(item.filename)
                    if item.filename == "word/document.xml":
                        data, changed = transform(data, variant)
                    dst.writestr(item, data)
            manifest.append({"sample": number, "variant": variant, "file": target.name,
                             "changed_nodes": changed, "sha256": sha256(target)})
        # 再次确认原副本未被改动。
        assert sha256(source) == digest
    (work / "manifest.json").write_text(json.dumps(manifest,
                                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{k: m[k] for k in ("file", "changed_nodes")}
          for m in manifest], ensure_ascii=False))


# FODT变体：(来源变体, 目标变体, 需修改的文档级兼容设置)。
# CharacterCompressionType=1 对应Word的compressPunctuation（仅压缩标点）；
# JustifyLinesWithShrinking、MsWordCompGridMetrics仅新版LibreOffice存在，旧版缺失时跳过。
FODT_VARIANTS = (
    ("v0-baseline", "v5-compress", {"CharacterCompressionType": "1"}),
    ("v4-exact-nosnap", "v6-exact-nosnap-compress",
     {"CharacterCompressionType": "1"}),
    ("v2-nogrid", "v7-nogrid-compress", {"CharacterCompressionType": "1"}),
    ("v0-baseline", "v8-shrink", {"JustifyLinesWithShrinking": "true"}),
    ("v4-exact-nosnap", "v9-exact-nosnap-compress-shrink",
     {"CharacterCompressionType": "1", "JustifyLinesWithShrinking": "true"}),
    ("v0-baseline", "v10-gridmetrics-off", {"MsWordCompGridMetrics": "false"}),
)


def patch_fodt(args: argparse.Namespace) -> None:
    """按FODT_VARIANTS修改文档级兼容设置，生成FODT变体。"""

    fodt_dir = args.work.resolve() / "fodt"
    for name, target, settings in FODT_VARIANTS:
        for source in sorted(fodt_dir.glob(f"s*-{name}.fodt")):
            patched = source.read_text(encoding="utf-8")
            missing = False
            for key, value in settings.items():
                pattern = re.compile(
                    rf'(<config:config-item config:name="{key}" config:type="\w+">)[^<]*(<)')
                patched, count = pattern.subn(rf"\g<1>{value}\2", patched)
                missing = missing or count != 1
            if missing:
                print(f"{source.name}: 当前版本缺少{list(settings)}之一，跳过{target}")
                continue
            output = fodt_dir / source.name.replace(name, target)
            output.write_text(patched, encoding="utf-8")
            print(f"{source.name} -> {output.name}")
        # 未改设置的往返副本作为对照，用于识别FODT往返本身的影响。
        if name == "v0-baseline":
            for source in sorted(fodt_dir.glob("s*-v0-baseline.fodt")):
                shutil.copyfile(source, fodt_dir /
                                source.name.replace(name, "v0r-roundtrip"))


# 声明变体：v0保持原文compressPunctuation；v13删除声明；v14改为doNotCompress。
DECL_VARIANTS = ("v0-baseline", "v13-nodecl", "v14-donotcompress")


def _transform_settings(xml: bytes, variant: str) -> tuple[bytes, int]:
    root = etree.fromstring(xml)
    nodes = root.findall("w:characterSpacingControl", NS)
    if variant == "v13-nodecl":
        for node in nodes:
            root.remove(node)
    elif variant == "v14-donotcompress":
        for node in nodes:
            node.set(W + "val", "doNotCompress")
    else:
        return xml, 0
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), len(nodes)


def prepare_decl(args: argparse.Namespace) -> None:
    source_dir, work = args.source.resolve(), args.work.resolve()
    report = json.loads(
        (source_dir / "font-report.json").read_text(encoding="utf-8"))
    docx_dir = work / "docx"
    docx_dir.mkdir(parents=True, exist_ok=False)
    manifest = []
    for number, sample in enumerate(report["samples"], 1):
        source = source_dir / f"sample-{number}.docx"
        digest = sha256(source)
        if digest != sample["sha256"]:
            raise ValueError(f"样本{number}哈希与登记不一致")
        for variant in DECL_VARIANTS:
            target = docx_dir / f"s{number}-{variant}.docx"
            with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
                changed = 0
                for item in src.infolist():
                    data = src.read(item.filename)
                    if item.filename == "word/settings.xml":
                        data, changed = _transform_settings(data, variant)
                    dst.writestr(item, data)
            if variant != "v0-baseline" and changed != 1:
                raise ValueError(f"{target.name}未命中唯一的characterSpacingControl")
            manifest.append({"sample": number, "variant": variant, "file": target.name,
                             "changed_nodes": changed, "sha256": sha256(target)})
        assert sha256(source) == digest
    (work / "manifest.json").write_text(json.dumps(manifest,
                                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{k: m[k] for k in ("file", "changed_nodes")}
          for m in manifest], ensure_ascii=False))


def _page_texts(pdf: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(pdf) as document:
        return [re.sub(r"\s+", "", page.get_text()) for page in document]


def compare(args: argparse.Namespace) -> None:
    """逐页文本对比；参数为若干“A.pdf=B.pdf”对。"""

    results = []
    for pair in args.pairs:
        left, right = (Path(p).resolve() for p in pair.split("=", 1))
        a, b = _page_texts(left), _page_texts(right)
        same = sum(1 for x, y in zip(a, b) if x == y)
        first = next(
            (i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
        item = {"a": left.name, "b": right.name, "pages": [len(a), len(b)],
                "identical_pages": same, "first_diff_page": first,
                "equivalent": len(a) == len(b) == same}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))
    if args.report:
        args.report.write_text(json.dumps(
            results, ensure_ascii=False, indent=2), encoding="utf-8")


def _lines(document) -> list[dict]:
    """提取每行首个文本span的基线、字体、字号和文本，排除页脚页码。"""

    rows = []
    for number, page in enumerate(document, 1):
        height = page.rect.height
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                # Word导出把全角空格写成普通空格，比较前统一去掉空白。
                text = re.sub(
                    r"\s+", "", "".join(span["text"] for span in line["spans"]))
                if not text:
                    continue
                span = line["spans"][0]
                baseline = span["origin"][1]
                if baseline > height - 70 and re.fullmatch(r"\d+", text):
                    continue
                rows.append({"page": number, "y": round(baseline, 2), "x1": round(line["bbox"][2], 1),
                             "font": span["font"], "size": round(span["size"], 1), "text": text})
    return rows


def _metrics(pdf: Path, sample: int) -> dict:
    import pymupdf

    with pymupdf.open(pdf) as document:
        rows = _lines(document)
        pages = len(document)
    body = BODY_SIZE[sample]
    gaps, title_gaps = [], []
    for a, b in zip(rows, rows[1:]):
        if a["page"] != b["page"]:
            continue
        gap = round(b["y"] - a["y"], 2)
        if a["size"] == b["size"] == body and "FangSong" in a["font"] and "FangSong" in b["font"]:
            gaps.append(gap)
        if "FZXBS" in a["font"] and "FZXBS" in b["font"]:
            title_gaps.append(gap)
    body_rows = [r for r in rows if r["size"] == body]
    right = max((r["x1"] for r in body_rows), default=0)
    full = [len(r["text"]) for r in body_rows if r["x1"] >= right - 3]
    lengths = collections.Counter(len(r["text"]) for r in body_rows)
    heading_pages = [(r["page"], r["text"][:12])
                     for r in rows if "SimHei" in r["font"] and r["size"] == body]
    page_starts = [next((r["text"][:10] for r in rows if r["page"] == p), "")
                   for p in range(1, pages + 1)]
    return {"pages": pages, "lines": len(rows), "body_line_gap_median_pt": statistics.median(gaps) if gaps else None,
            "body_line_gap_modes": collections.Counter(gaps).most_common(3), "title_gaps_pt": title_gaps,
            "full_line_chars_median": statistics.median(full) if full else None,
            "body_line_chars_mode": lengths.most_common(1)[0][0] if lengths else None,
            "lines_per_page_max": max(collections.Counter(r["page"] for r in rows).values()),
            "text": re.sub(r"\s+", "", "".join(r["text"] for r in rows)), "heading_pages": heading_pages,
            "page_starts": page_starts, "fonts": sorted({r["font"] for r in rows})}


def measure(args: argparse.Namespace) -> None:
    work, word_dir = args.work.resolve(), args.word.resolve()
    results = []
    for sample in (1, 2):
        word = _metrics(word_dir / f"sample-{sample}-word.pdf", sample)
        candidates = [("word-16.0", word_dir / f"sample-{sample}-word.pdf")]
        candidates += [(p.stem.split("-", 1)[1], p)
                       for p in sorted((work / "pdf").glob(f"s{sample}-*.pdf"))]
        candidates += [(p.stem.split("-", 1)[1] + "@" + p.parent.parent.name, p)
                       for p in sorted(work.glob(f"lo-*/pdf/s{sample}-*.pdf"))]
        for label, pdf in candidates:
            item = word if label.startswith("word") else _metrics(pdf, sample)
            same_starts = sum(
                1 for s in item["page_starts"] if s in word["page_starts"])
            matcher = difflib.SequenceMatcher(
                None, item["text"], word["text"], autojunk=False)
            missing = collections.Counter(
                word["text"]) - collections.Counter(item["text"])
            extra = collections.Counter(
                item["text"]) - collections.Counter(word["text"])
            results.append({
                "sample": sample, "variant": label, "pages": item["pages"], "lines": item["lines"],
                "lines_per_page_max": item["lines_per_page_max"],
                "body_line_gap_median_pt": item["body_line_gap_median_pt"],
                "body_line_gap_modes": item["body_line_gap_modes"], "title_gaps_pt": item["title_gaps_pt"],
                "full_line_chars_median": item["full_line_chars_median"],
                "body_line_chars_mode": item["body_line_chars_mode"],
                "page2_start": item["page_starts"][1] if item["pages"] > 1 else None,
                "page_starts_matching_word": f"{same_starts}/{word['pages']}",
                "heading_page_matches": sum(1 for h in item["heading_pages"] if h in word["heading_pages"]),
                "headings": len(item["heading_pages"]),
                "text_chars": len(item["text"]), "text_ratio_vs_word": round(matcher.ratio(), 5),
                "chars_missing_vs_word": dict(missing.most_common(8)), "chars_extra_vs_word": dict(extra.most_common(8)),
                "fonts": item["fonts"], "pdf": str(pdf)})
    (work / "measure-report.json").write_text(json.dumps(results,
                                                         ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(f"s{r['sample']} {r['variant']:<34} pages={r['pages']:>2} gap={r['body_line_gap_median_pt']} "
              f"title={r['title_gaps_pt'][:3]} chars/line={r['body_line_chars_mode']} "
              f"lines/page={r['lines_per_page_max']} starts={r['page_starts_matching_word']} "
              f"headings={r['heading_page_matches']}/{r['headings']} text={r['text_chars']} ratio={r['text_ratio_vs_word']} "
              f"missing={r['chars_missing_vs_word']} extra={r['chars_extra_vs_word']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.set_defaults(func=prepare)
    p = sub.add_parser("patch-fodt")
    p.add_argument("--work", type=Path, required=True)
    p.set_defaults(func=patch_fodt)
    p = sub.add_parser("measure")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--word", type=Path, required=True)
    p.set_defaults(func=measure)
    p = sub.add_parser("prepare-decl")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.set_defaults(func=prepare_decl)
    p = sub.add_parser("compare")
    p.add_argument("pairs", nargs="+")
    p.add_argument("--report", type=Path)
    p.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
