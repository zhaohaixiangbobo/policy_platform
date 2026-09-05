"""文件说明：为API与Worker进程配置彼此独立的UTF-8滚动日志。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_rotating_logger(
    logger_name: str,
    *,
    level_name: str,
    log_file: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """幂等装配控制台和文件处理器；子模块日志通过名称层级汇聚。"""

    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    level = getattr(logging, level_name.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    path = Path(log_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.setLevel(level)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger
