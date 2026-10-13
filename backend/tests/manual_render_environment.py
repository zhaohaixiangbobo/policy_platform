"""文件说明：DOCX→PDF 转换环境追溯探针（人工验收用，不是后端运行依赖）。

在转换容器内用业务 Python 运行，输出四项可分别追溯的环境字段，并与现有
font_environment_hash()（只含系统名/内核/架构）对照：
- converter_version：soffice --version 原文（含构建号）；
- render_profile：转换配置版本（由调用方传入，对应转换脚本中的 RENDER_PROFILE）；
- font_files_hash：fontconfig 可见字体文件的内容哈希（与路径无关）；
- fontconfig_hash：/etc/fonts/fonts.conf 与 conf.d 下生效配置的内容哈希（含文件名，顺序有意义）。
用法：python3 manual_render_environment.py --profile lo-uno-compress-v1 --label <场景名> --report <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

# 公文常用字体，记录其 fontconfig 实际匹配结果，便于定位映射变化。
DOCUMENT_FONTS = ("宋体", "仿宋_GB2312", "楷体_GB2312",
                  "黑体", "方正小标宋简体", "Times New Roman")


def legacy_hash() -> str:
    """与 backend/knowledge/parser/render.py 的 font_environment_hash() 相同算法。"""

    value = f"{platform.system()}|{platform.release()}|{platform.machine()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font_files() -> tuple[str, int, int]:
    """返回字体内容哈希、文件数和总字节数；只按内容排序，挂载路径变化不影响结果。"""

    listing = subprocess.run(
        ["fc-list", "--format", "%{file}\n"], capture_output=True, text=True, check=True)
    files = sorted({Path(line)
                   for line in listing.stdout.splitlines() if line.strip()})
    digests = sorted(_file_sha256(path) for path in files)
    combined = hashlib.sha256("\n".join(digests).encode("ascii")).hexdigest()
    return combined, len(files), sum(path.stat().st_size for path in files)


def fontconfig() -> tuple[str, list[str]]:
    """哈希主配置与 conf.d 中按文件名排序的生效配置（符号链接取目标内容）。"""

    root = Path("/etc/fonts")
    entries = [root / "fonts.conf"] + sorted((root / "conf.d").glob("*.conf"))
    digest = hashlib.sha256()
    names = []
    for entry in entries:
        if not entry.exists():
            continue
        names.append(entry.name)
        digest.update(entry.name.encode("utf-8") + b"\0" +
                      entry.resolve().read_bytes() + b"\0")
    return digest.hexdigest(), names


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--soffice", default="soffice")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    version = subprocess.run(
        [args.soffice, "--version"], capture_output=True, text=True, check=False)
    started = time.perf_counter()
    fonts_hash, font_count, font_bytes = font_files()
    font_seconds = round(time.perf_counter() - started, 2)
    fc_hash, fc_files = fontconfig()
    matches = {name: subprocess.run(["fc-match", name], capture_output=True, text=True).stdout.strip()
               for name in DOCUMENT_FONTS}
    result = {
        "label": args.label,
        "legacy_font_environment_hash": legacy_hash(),
        "platform": f"{platform.system()}|{platform.release()}|{platform.machine()}",
        "converter_version": (version.stdout or version.stderr).strip(),
        "render_profile": args.profile,
        "font_files_hash": fonts_hash, "font_file_count": font_count, "font_bytes": font_bytes,
        "font_hash_seconds": font_seconds,
        "fontconfig_hash": fc_hash, "fontconfig_file_count": len(fc_files),
        "font_matches": matches,
        # 复用现有 font_environment_hash 文本列的候选写法：带版本前缀，便于与旧值区分。
        "proposed_font_environment_hash": f"fe2;arch={platform.machine()};fonts={fonts_hash[:16]};fc={fc_hash[:16]}",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(
        result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
