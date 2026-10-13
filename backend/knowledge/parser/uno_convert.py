"""文件说明：由 LibreOffice 自带 Python 执行的独立 UNO 转换子进程，不导入业务依赖。"""

import argparse
import json
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def declaration(path):
    with zipfile.ZipFile(path) as package:
        try:
            xml = package.read("word/settings.xml")
        except KeyError:
            return None
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    node = ElementTree.fromstring(xml).find("{" + ns + "}characterSpacingControl")
    return None if node is None else node.get("{" + ns + "}val")


def main():
    import uno
    from com.sun.star.beans import PropertyValue
    from com.sun.star.connection import NoConnectException

    parser = argparse.ArgumentParser()
    for name in ("source", "output", "profile", "report", "soffice"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    def props(**values):
        return tuple(PropertyValue(Name=k, Value=v) for k, v in values.items())

    pipe = "policy-" + uuid.uuid4().hex
    office = subprocess.Popen([args.soffice,
        "-env:UserInstallation=" + Path(args.profile).as_uri(), "--headless", "--invisible",
        "--nologo", "--norestore", "--nodefault",
        "--accept=pipe,name=" + pipe + ";urp;StarOffice.ComponentContext"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    document = desktop = None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        deadline = time.monotonic() + 30
        while True:
            try:
                context = resolver.resolve("uno:pipe,name=" + pipe + ";urp;StarOffice.ComponentContext")
                break
            except NoConnectException:
                if office.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("UNO 启动失败或连接超时")
                time.sleep(0.1)
        desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
        # 禁用宏与外部链接更新，源文件只读加载。
        document = desktop.loadComponentFromURL(Path(args.source).as_uri(), "_blank", 0,
            props(Hidden=True, ReadOnly=True,
                  MacroExecutionMode=uno.getConstantByName("com.sun.star.document.MacroExecMode.NEVER_EXECUTE"),
                  UpdateDocMode=uno.getConstantByName("com.sun.star.document.UpdateDocMode.NO_UPDATE")))
        if document is None:
            raise RuntimeError("UNO 无法加载 DOCX")
        declared = declaration(args.source)
        settings = document.createInstance("com.sun.star.text.DocumentSettings")
        before = settings.getPropertyValue("CharacterCompressionType")
        if declared == "compressPunctuation":
            settings.setPropertyValue("CharacterCompressionType", 1)
        after = settings.getPropertyValue("CharacterCompressionType")
        if declared == "compressPunctuation" and after != 1:
            raise RuntimeError("标点压缩属性未生效")
        document.storeToURL(Path(args.output).as_uri(), props(FilterName="writer_pdf_Export"))
        Path(args.report).write_text(json.dumps({"profile": "lo-uno-compress-v1",
            "declaration": declared, "compression_before": before, "compression_after": after,
            "compression_enabled": declared == "compressPunctuation"}, ensure_ascii=False), encoding="utf-8")
    finally:
        if document is not None:
            document.close(True)
        if desktop is not None:
            try:
                desktop.terminate()
            except Exception:
                pass  # 正常退出也会断开 UNO 桥。
        try:
            office.wait(timeout=5)
        except subprocess.TimeoutExpired:
            office.kill()
            office.wait()


if __name__ == "__main__":
    main()
