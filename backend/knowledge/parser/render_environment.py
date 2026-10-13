"""文件说明：校验公文字体实际匹配并记录受控 Linux 转换环境的完整内容指纹。"""

import hashlib
import json
import platform
import subprocess
from pathlib import Path


REQUIRED_FONTS = {
    "宋体": "SimSun", "黑体": "SimHei", "仿宋": "FangSong",
    "仿宋_GB2312": "FangSong_GB2312", "楷体": "KaiTi",
    "楷体_GB2312": "KaiTi", "方正小标宋简体": "FZXiaoBiaoSong-B05S",
    "Times New Roman": "Times New Roman",
}


def _command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          encoding="utf-8", timeout=15).stdout.strip()


def inspect_environment() -> dict:
    """在每次转换前检查，外置字体更新不会被进程缓存掩盖；失败仅阻止本次转换。"""
    matches = {}
    for requested, expected in REQUIRED_FONTS.items():
        value = _command("fc-match", "--format", "%{family}\t%{file}", requested)
        family, filename = value.split("\t", 1)
        if expected not in family.split(",") or not Path(filename).is_file():
            raise RuntimeError(f"字体检查失败：{requested} 预期 {expected}，实际 {family}")
        matches[requested] = {"family": family, "file": filename}
    # 枚举 fontconfig 实际加载的配置，包括用户配置和递归 include。
    config_files = []
    for line in _command("fc-conflist").splitlines():
        if line.startswith("+ "):
            filename = line[2:].split(": ", 1)[0]
            if Path(filename).is_file():
                config_files.append(Path(filename))
    if not config_files:
        raise RuntimeError("无法枚举 fontconfig 生效配置")
    files = {Path(p) for p in _command("fc-list", "--format", "%{file}\n").splitlines()}
    fonts = hashlib.sha256("\n".join(sorted(
        hashlib.sha256(p.read_bytes()).hexdigest() for p in files)).encode()).hexdigest()
    configs = hashlib.sha256(b"\0".join(p.read_bytes() for p in config_files)).hexdigest()
    details = {"version": "font_environment_v2", "arch": platform.machine(),
               "fonts_sha256": fonts, "fontconfig_sha256": configs, "matches": matches}
    # 路径用于诊断，环境身份只包含字体内容、配置内容和架构。
    identity = {k: v for k, v in details.items() if k != "matches"}
    details["fingerprint"] = "fe2:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return details
