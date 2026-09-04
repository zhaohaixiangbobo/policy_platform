"""文件说明：定义制度入库任务的唯一合法状态机、终态和人工重试契约。"""

from __future__ import annotations

from dataclasses import dataclass


MAIN_FLOW = (
    "UPLOADED", "PREFLIGHTING", "PARSE_QUEUED", "PARSING", "PARSE_REVIEW",
    "METADATA_REVIEW", "CHUNK_QUEUED", "CHUNKING", "CHUNK_REVIEW", "READY_FOR_INDEX", "INDEX_QUEUED", "INDEXING",
    "READY_TO_PUBLISH", "PUBLISH_QUEUED", "PUBLISHING", "PUBLISHED",
)
TERMINAL_STATES = frozenset({"PUBLISHED", "REJECTED", "CANCELLED"})
SUPPLEMENTAL_STATES = frozenset({"FAILED", "REJECTED", "CANCEL_REQUESTED", "CANCELLED"})

TRANSITIONS: dict[str, frozenset[str]] = {
    current: frozenset({next_state, "FAILED"})
    for current, next_state in zip(MAIN_FLOW, MAIN_FLOW[1:])
}
TRANSITIONS.update({
    "UPLOADED": TRANSITIONS["UPLOADED"] | {"CANCELLED"},
    "PARSE_QUEUED": TRANSITIONS["PARSE_QUEUED"] | {"CANCELLED"},
    "PARSE_REVIEW": TRANSITIONS["PARSE_REVIEW"] | {"REJECTED", "CANCELLED"},
    "METADATA_REVIEW": TRANSITIONS["METADATA_REVIEW"] | {"REJECTED", "CANCELLED"},
    "CHUNK_QUEUED": TRANSITIONS["CHUNK_QUEUED"] | {"CANCELLED"},
    "CHUNK_REVIEW": TRANSITIONS["CHUNK_REVIEW"] | {"REJECTED", "CANCELLED"},
    "READY_FOR_INDEX": TRANSITIONS["READY_FOR_INDEX"] | {"CANCELLED"},
    "INDEX_QUEUED": TRANSITIONS["INDEX_QUEUED"] | {"CANCELLED"},
    "READY_TO_PUBLISH": TRANSITIONS["READY_TO_PUBLISH"] | {"CANCELLED"},
    "PUBLISH_QUEUED": TRANSITIONS["PUBLISH_QUEUED"] | {"CANCELLED"},
    "PREFLIGHTING": frozenset({"PARSE_QUEUED", "FAILED", "CANCEL_REQUESTED"}),
    "PARSING": frozenset({"PARSE_REVIEW", "FAILED", "CANCEL_REQUESTED"}),
    "CHUNKING": frozenset({"CHUNK_REVIEW", "FAILED", "CANCEL_REQUESTED"}),
    "INDEXING": frozenset({"READY_TO_PUBLISH", "FAILED", "CANCEL_REQUESTED"}),
    "CANCEL_REQUESTED": frozenset({"CANCELLED", "FAILED"}),
})

RETRY_TARGETS = {
    "PREFLIGHTING": "UPLOADED",
    "PARSING": "PARSE_QUEUED",
    "CHUNKING": "CHUNK_QUEUED",
    "INDEXING": "INDEX_QUEUED",
    "PUBLISHING": "READY_TO_PUBLISH",
}


class InvalidStateTransition(ValueError):
    """请求违反冻结的任务状态机。"""


def assert_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidStateTransition(f"不允许从 {current} 转换到 {target}")


def retry_target(failed_stage: str | None, retryable: bool) -> str:
    if not retryable or failed_stage not in RETRY_TARGETS:
        raise InvalidStateTransition("该失败任务不允许人工重试")
    return RETRY_TARGETS[failed_stage]
