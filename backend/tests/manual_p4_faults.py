"""文件说明：容器隔离故障验收；只写 /tmp，不改变数据库/索引/业务文件。"""

import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from app.infrastructure.db import readiness
from knowledge.parser.render import render_docx_to_pdf


def main():
    # 使用真实只读版本查询、故意要求不存在的代码版本，验证启动门禁拒绝。
    with patch.object(readiness, "expected_head", return_value="p4_intentional_mismatch"):
        try:
            readiness.check_readiness(check_files=False)
        except RuntimeError as exc:
            assert "版本未就绪" in str(exc)
            print("PASS revision mismatch blocked; no database writes")
        else:
            raise AssertionError("版本门禁未阻断")
    readiness.check_readiness()
    print("PASS normal readiness recovered")
    with tempfile.TemporaryDirectory(prefix="p4-fault-") as directory:
        root = Path(directory)
        source = next(Path("/data/knowledge/accepted").rglob("*.docx"))
        target = root / "test.pdf"
        with patch.dict(os.environ, {"POLICY_DOCX_RENDER_TIMEOUT_SECONDS": "0.001"}):
            try:
                render_docx_to_pdf(source, target, engine="libreoffice")
            except RuntimeError as exc:
                assert "超过" in str(exc)
            else:
                raise AssertionError("超时未触发")
        assert not target.exists() and not list(root.glob(".render-*"))
        print("PASS real child timeout; no published partial PDF")
        result = render_docx_to_pdf(source, target, engine="libreoffice")
        assert result.page_count > 0 and result.metadata["profile"] == "lo-uno-compress-v1"
        print(f"PASS subsequent conversion recovered pages={result.page_count}")


if __name__ == "__main__":
    main()
