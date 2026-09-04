"""文件说明：定义知识模块可迁移的数据根目录。

知识数据库只保存相对文件路径，所有DOCX和PDF路径统一从data_root解析，避免依赖
启动命令的当前工作目录或旧工程绝对路径。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KnowledgePaths:
    """知识数据库和受控文档目录。"""

    data_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", self.data_root.resolve())

    @property
    def database_path(self) -> Path:
        return self.data_root / "policy_parser.db"

    @property
    def source_documents(self) -> Path:
        return self.data_root / "source_documents"

    @property
    def accepted_documents(self) -> Path:
        return self.data_root / "accepted"

    @property
    def pdf_documents(self) -> Path:
        return self.data_root / "pdf"

    @property
    def pending_documents(self) -> Path:
        return self.data_root / "pending"

    @property
    def temp_directory(self) -> Path:
        return self.data_root / "temp"
