"""文件说明：LibreOffice UNO 直接 DOCX→PDF 转换的最小验证工具（人工验收用，不是后端运行依赖）。

流程：加载 DOCX → 读取原文 word/settings.xml 的 characterSpacingControl 声明 →
仅当声明为 compressPunctuation 时设置文档属性 CharacterCompressionType=1 → 直接导出 PDF。
不经过 FODT 中转，不修改输入 DOCX。

必须用 LibreOffice 自带的 Python 运行（其中带 uno 模块），例如容器内：
    /opt/libreoffice26.8/program/python manual_uno_render.py --input-dir /work/docx \
        --output-dir /work/pdf --mode auto --suffix -uno-auto --report /work/uno-auto.json
--mode off 时只走同一 UNO 路径但不改任何属性，用于证明 UNO 路径本身不改变排版。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.connection import NoConnectException

# 转换配置版本：配置语义变化时必须同步修改，供环境追溯区分同版本转换器下的不同处理。
RENDER_PROFILE = "lo-uno-compress-v1"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# Word 声明值到 LibreOffice CharacterCompressionType 的映射；只启用已验证的 compressPunctuation。
COMPRESSION_MAP = {"compressPunctuation": 1}


def _props(**values) -> tuple:
    return tuple(PropertyValue(Name=name, Value=value) for name, value in values.items())


def read_declaration(docx: Path) -> str | None:
    """读取原文压缩声明；无 settings.xml 或无该节点时返回 None。"""

    with zipfile.ZipFile(docx) as package:
        try:
            xml = package.read("word/settings.xml")
        except KeyError:
            return None
    node = ElementTree.fromstring(xml).find(
        f"{{{W_NS}}}characterSpacingControl")
    return None if node is None else node.get(f"{{{W_NS}}}val")


def start_office(soffice: str, profile: Path) -> tuple[subprocess.Popen, object]:
    """以独立配置目录启动无界面 LibreOffice，并通过命名管道连接。"""

    pipe = f"policy-uno-{uuid.uuid4().hex[:8]}"
    process = subprocess.Popen(
        [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--invisible",
         "--nologo", "--norestore", "--nodefault", f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    deadline = time.monotonic() + 60
    while True:
        try:
            context = resolver.resolve(
                f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
            break
        except NoConnectException:
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                raise RuntimeError("LibreOffice UNO 连接失败")
            time.sleep(0.5)
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context)
    return process, desktop


def convert(desktop, docx: Path, pdf: Path, mode: str) -> dict:
    """转换单个文件，返回声明、设置前后值与 PDF 哈希。"""

    declaration = read_declaration(docx)
    document = desktop.loadComponentFromURL(
        uno.systemPathToFileUrl(str(docx)), "_blank", 0, _props(Hidden=True))
    try:
        settings = document.createInstance(
            "com.sun.star.text.DocumentSettings")
        before = settings.getPropertyValue("CharacterCompressionType")
        target = COMPRESSION_MAP.get(declaration) if mode == "auto" else None
        if target is not None and before != target:
            settings.setPropertyValue("CharacterCompressionType", target)
        after = settings.getPropertyValue("CharacterCompressionType")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        document.storeToURL(uno.systemPathToFileUrl(
            str(pdf)), _props(FilterName="writer_pdf_Export"))
    finally:
        document.close(True)
    return {"file": docx.name, "declaration": declaration, "mode": mode, "before": before, "after": after,
            "applied": after != before, "pdf": pdf.name,
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="*.docx")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("auto", "off"), default="auto")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--soffice", default="soffice")
    parser.add_argument("--profile", type=Path,
                        default=Path("/tmp/uno-profile"))
    args = parser.parse_args()

    version = subprocess.run([args.soffice, "--version"],
                             capture_output=True, text=True, check=False).stdout.strip()
    process, desktop = start_office(args.soffice, args.profile)
    results = []
    try:
        for docx in sorted(args.input_dir.glob(args.pattern)):
            started = time.perf_counter()
            item = convert(desktop, docx, args.output_dir /
                           f"{docx.stem}{args.suffix}.pdf", args.mode)
            item["seconds"] = round(time.perf_counter() - started, 2)
            results.append(item)
            print(json.dumps(item, ensure_ascii=False))
    finally:
        try:
            desktop.terminate()
        except Exception:
            pass  # terminate 会断开桥接，抛出 DisposedException 属正常现象。
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
    args.report.write_text(json.dumps({"converter_version": version, "render_profile": RENDER_PROFILE,
                                       "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
