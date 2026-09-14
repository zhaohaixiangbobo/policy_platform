"""文件说明：集中定义元数据生命周期动作与制度状态之间的强制对应关系。"""

from __future__ import annotations


STATUS_BY_LIFECYCLE_SOURCE = {
    "REPEAL": "repealed",
    "EXPIRY": "expired",
}

LIFECYCLE_LABELS = {
    "REPEAL": "登记废止",
    "EXPIRY": "登记失效",
}


def required_status_for_source(source_type: str) -> str | None:
    """返回生命周期动作必须写入的制度状态；普通元数据修订返回None。"""

    return STATUS_BY_LIFECYCLE_SOURCE.get(str(source_type or "").upper())


def status_transition_error(source_type: str, status: str | None) -> str | None:
    """返回流程与状态不一致的稳定错误信息。"""

    normalized_source = str(source_type or "").upper()
    expected = required_status_for_source(normalized_source)
    normalized_status = str(status or "unknown").strip().lower()
    if expected is None or normalized_status == expected:
        return None
    label = LIFECYCLE_LABELS[normalized_source]
    status_label = "已废止" if expected == "repealed" else "已失效"
    return f"{label}流程的制度状态必须为{status_label}"
