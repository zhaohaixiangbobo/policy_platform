"""文件说明：隔离字体与DOCX转换验收；只读样本，结果写到指定空目录，不访问数据库。"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from lxml import etree
from pypdf import PdfReader
from knowledge.parser.render import render_docx_to_pdf

FONTS = {
    "宋体": "simsun.ttc", "黑体": "simhei.ttf", "仿宋": "simfang.ttf",
    "仿宋_GB2312": "fangsong_GB2312.ttf", "FangSong_GB2312": "fangsong_GB2312.ttf",
    "楷体": "simkai.ttf", "楷体_GB2312": "simkai.ttf", "KaiTi_GB2312": "simkai.ttf",
    "方正小标宋简体": "FZXBSJW.TTF",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / "font-report.json"
    if report_file.exists():
        raise ValueError("验收目录已有记录，请选择新的空目录")
    subprocess.run(["fc-cache", "-f", "/usr/local/share/fonts/policy"], check=True)
    matches = {}
    for family, filename in FONTS.items():
        match = subprocess.check_output(["fc-match", "--format=%{family}|%{file}", family], text=True).strip()
        if Path(match.split("|")[-1]).name != filename:
            raise ValueError(f"字体匹配失败：{family} -> {match}")
        matches[family] = match
    results = []
    # 两份代表样本覆盖标题、正文及GB2312楷体；不批量重转全部制度。
    for number, pattern in enumerate(("*_19_*accepted.docx", "*_175_*accepted.docx"), 1):
        candidates = sorted(args.source.glob(pattern))
        if len(candidates) != 1:
            raise ValueError(f"样本应唯一：{pattern}")
        source = candidates[0]
        print(f"event=font_review stage=render completed={number-1} total=2", flush=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        copy = output / f"sample-{number}.docx"
        shutil.copyfile(source, copy)
        result = render_docx_to_pdf(copy, output / f"sample-{number}.pdf", engine="libreoffice")
        reader = PdfReader(result.pdf_path)
        pdf_fonts = sorted({str(font.get_object().get("/BaseFont")) for page in reader.pages
                            for font in page.get("/Resources", {}).get("/Font", {}).values()})
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with zipfile.ZipFile(copy) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
            spacings = [dict(e.attrib) for e in root.findall(".//w:spacing", ns)]
            declared = sorted({v for e in root.findall(".//w:rFonts", ns) for k,v in e.attrib.items()
                               if k.split("}")[-1] in {"ascii", "eastAsia", "hAnsi", "cs"}})
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        results.append({"source": source.name, "sha256": digest, "pages": len(reader.pages),
                        "declared_fonts": declared, "pdf_fonts": pdf_fonts,
                        "paragraph_spacing_declarations": spacings, "render_engine": result.engine_version})
    report = {"font_matches": matches, "samples": results, "note": "楷体_GB2312使用KaiTi替代，不宣称原字体完全一致"}
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"completed": 2, "pages": [item["pages"] for item in results], "report": str(report_file)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
