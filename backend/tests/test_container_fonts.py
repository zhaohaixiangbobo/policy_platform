"""文件说明：验证字体部署边界和GB2312别名，不安装字体、不连接业务环境。"""

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]


def test_font_aliases_keep_gb2312_distinct():
    config = ElementTree.parse(ROOT / "deploy/fonts/99-policy-fonts.conf")
    aliases = {item.findtext("family"): item.findtext("prefer/family") for item in config.findall("alias")}
    assert aliases["仿宋_GB2312"] == "FangSong_GB2312"
    assert aliases["仿宋"] == "FangSong"
    assert aliases["楷体_GB2312"] == aliases["KaiTi_GB2312"] == "KaiTi"
    assert aliases["方正小标宋简体"] == "FZXiaoBiaoSong-B05S"


def test_fonts_are_external_and_script_preserves_command():
    compose = (ROOT / "deploy/compose.fonts.yaml").read_text(encoding="utf-8")
    assert "POLICY_FONT_DIR:?" in compose
    assert "command: [python, -m, uvicorn, app.main:app" in compose
    assert "read_only: true" in compose and "create_host_path: false" in compose
    script = (ROOT / "deploy/fonts/entrypoint.sh").read_bytes()
    assert b'fc-cache -f' in script and b'exec "$@"' in script and b'\r' not in script
    for file in (".gitignore", ".dockerignore"):
        content = (ROOT / file).read_text(encoding="utf-8")
        for extension in ("*.ttf", "*.TTF", "*.ttc", "*.otf"):
            assert extension in content
