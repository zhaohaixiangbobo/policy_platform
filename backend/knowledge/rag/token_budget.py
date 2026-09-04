"""文件说明：提供无新增依赖的保守Token估算和硬预算计数器。

Tokenizer revision尚未冻结，因此第一版不声称精确计数。估算器对中文采用较保守
的字符/token比例，并通过版本号进入Context配置哈希，未来可替换为精确Tokenizer。
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass


class ConservativeTokenEstimator:
    """面向中英文混合制度文本的保守估算器。"""

    version = "conservative_mixed_v1"

    @staticmethod
    def _is_cjk(char: str) -> bool:
        code = ord(char)
        return (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
        )

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        cjk = sum(self._is_cjk(char) for char in text)
        whitespace = sum(char.isspace() for char in text)
        non_cjk = len(text) - cjk - whitespace
        # 实测中文约1.66字符/token；使用1.3作保守预算，并给标点/英文留余量。
        estimated = cjk / 1.3 + non_cjk / 3.0 + whitespace / 8.0
        structural_margin = 4 + max(1, unicodedata.normalize("NFKC", text).count("\n"))
        return max(1, math.ceil(estimated) + structural_margin)


@dataclass
class TokenBudget:
    """只接受完整证据块的硬预算计数器。"""

    limit: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("Token预算必须大于0")

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def try_add(self, estimated_tokens: int) -> bool:
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens不能小于0")
        if self.used + estimated_tokens > self.limit:
            return False
        self.used += estimated_tokens
        return True
