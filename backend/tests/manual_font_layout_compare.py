"""文件说明：比较隔离的Word/LibreOffice PDF分页及几何信息，生成可复查记录和抽样图。"""

import argparse
import json
from pathlib import Path
import re
import statistics
import pymupdf


def describe(document):
    pages = []
    for page in document:
        lines = [line for block in page.get_text("dict")["blocks"] if block["type"] == 0 for line in block["lines"]]
        origins = sorted({round(line["spans"][0]["origin"][1], 2) for line in lines if line["spans"]})
        gaps = [round(b-a, 2) for a,b in zip(origins, origins[1:]) if 10 < b-a < 50]
        pages.append({"text": re.sub(r"\s+", "", page.get_text()),
                      "fonts": sorted({span["font"] for line in lines for span in line["spans"]}),
                      "median_line_gap_pt": statistics.median(gaps) if gaps else None,
                      "first_baseline_y": origins[0] if origins else None})
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = []
    for n in (1, 2):
        with pymupdf.open(args.directory / f"sample-{n}.pdf") as lo, pymupdf.open(args.directory / f"sample-{n}-word.pdf") as word:
            a, b = describe(lo), describe(word)
            equal = [i+1 for i in range(min(len(a),len(b))) if a[i]["text"] == b[i]["text"]]
            kai_pages = [i for i,p in enumerate(a) if any("Kai" in font for font in p["fonts"])]
            selected = sorted({0, 1, *(kai_pages[:1])})
            for i in selected:
                for label, doc in (("lo",lo),("word",word)):
                    if i < len(doc):
                        doc[i].get_pixmap(matrix=pymupdf.Matrix(1.2,1.2)).save(args.directory / f"sample-{n}-{label}-page-{i+1}.png")
            report.append({"sample": n, "lo_pages": len(a), "word_pages": len(b), "same_page_text": equal,
                           "selected_pages": [i+1 for i in selected], "lo": a, "word": b})
    (args.directory / "layout-comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{k:v for k,v in item.items() if k not in {"lo","word"}} for item in report], ensure_ascii=False))


if __name__ == "__main__":
    main()
