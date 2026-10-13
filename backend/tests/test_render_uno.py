"""文件说明：转换安全边界最小测试，不访问数据库、模型或实际 Office。"""

import subprocess
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from knowledge.parser import render, render_environment, uno_convert


@pytest.mark.parametrize("value", [None, "doNotCompress", "compressPunctuation", "compressPunctuationAndJapaneseKana"])
def test_declaration(tmp_path, value):
    source = tmp_path / "test.docx"
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(source, "w") as package:
        node = f'<w:characterSpacingControl w:val="{value}"/>' if value else ""
        package.writestr("word/settings.xml", f'<w:settings xmlns:w="{ns}">{node}</w:settings>')
    assert uno_convert.declaration(source) == value


def test_atomic_output_and_existing_pdf(tmp_path, monkeypatch):
    target = tmp_path / "run.pdf"
    def fake(source, output, **kwargs):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        return render.RenderResult(output, "test", "1", "test", 1, "hash")
    monkeypatch.setattr(render, "_render_docx_to_pdf", fake)
    result = render.render_docx_to_pdf(tmp_path / "source.docx", target)
    original = target.read_bytes()
    assert result.pdf_path == target
    with pytest.raises(FileExistsError):
        render.render_docx_to_pdf(tmp_path / "source.docx", target)
    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".render-*"))


def test_failed_output_is_not_published(tmp_path, monkeypatch):
    def fail(source, output, **kwargs):
        output.write_bytes(b"partial")
        raise RuntimeError("conversion failed")
    monkeypatch.setattr(render, "_render_docx_to_pdf", fail)
    target = tmp_path / "run.pdf"
    with pytest.raises(RuntimeError):
        render.render_docx_to_pdf(tmp_path / "source.docx", target)
    assert not target.exists()
    assert not list(tmp_path.glob(".render-*"))


def test_font_substitution_blocks_conversion(monkeypatch):
    monkeypatch.setattr(render_environment, "_command", lambda *args: "DejaVu Sans\t/missing.ttf")
    with pytest.raises(RuntimeError, match="字体检查失败"):
        render_environment.inspect_environment()


def test_invalid_pdf_never_reaches_destination(tmp_path, monkeypatch):
    monkeypatch.delenv("POLICY_LIBREOFFICE_UNO_PYTHON", raising=False)
    monkeypatch.setattr(render, "_resolve_libreoffice", lambda path: "soffice")
    def invalid(soffice, source, output):
        output.write_bytes(b"invalid PDF")
        return "test"
    monkeypatch.setattr(render, "_render_with_libreoffice", invalid)
    target = tmp_path / "invalid.pdf"
    with pytest.raises(Exception):
        render.render_docx_to_pdf(tmp_path / "source.docx", target)
    assert not target.exists()


def test_environment_uses_active_config_and_full_hash(tmp_path, monkeypatch):
    font = tmp_path / "font.ttf"
    config = tmp_path / "fonts.conf"
    font.write_bytes(b"font")
    config.write_text("config", encoding="utf-8")
    monkeypatch.setattr(render_environment, "REQUIRED_FONTS", {"宋体": "SimSun"})
    def command(*args):
        if args[0] == "fc-match":
            return f"SimSun,宋体\t{font}"
        if args[0] == "fc-conflist":
            return f"+ {config}: active\n- /unused.conf: inactive"
        return str(font)
    monkeypatch.setattr(render_environment, "_command", command)
    before = render_environment.inspect_environment()
    assert len(before["fonts_sha256"]) == 64
    assert before == render_environment.inspect_environment()
    font.write_bytes(b"changed")
    assert before["fingerprint"] != render_environment.inspect_environment()["fingerprint"]


@pytest.mark.parametrize("failure", ["timeout", "crash"])
def test_child_failure_cleans_process_group(monkeypatch, failure):
    calls = []
    class Process:
        pid = 12345
        returncode = 1
        def communicate(self, timeout=None):
            if timeout is not None and failure == "timeout":
                raise subprocess.TimeoutExpired("uno", timeout)
            return "", "failed"
    monkeypatch.setattr(render.os, "name", "posix")
    monkeypatch.setattr(render.os, "killpg", lambda *args: calls.append(args), raising=False)
    monkeypatch.setattr(render.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(render.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(RuntimeError):
        render._run_isolated(["test"], 1)
    assert calls == [(12345, 9)]
