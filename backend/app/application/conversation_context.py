"""文件说明：按用户明确的短回复补全澄清问题，保留字段来源，不调用模型或继承答案事实。"""

import json
import re
from datetime import date

STRATEGY_VERSION = "clarification_rewrite_v1"
LABELS = {
    "competition_category": "竞赛类别", "award_level": "获奖等级",
    "recipient_type": "获奖对象", "department": "适用部门",
    "applicable_date": "适用日期", "business_scenario": "业务情形",
}


def explicit_values(text: str) -> dict[str, str]:
    """仅接受完整可消费的短回复；一类与一等奖采用独立模式，歧义整体回退。"""
    if len(text) > 200:
        return {}
    remaining = re.sub(r"^补充信息[:：]\s*", "", text.strip())
    remaining = re.sub(r"^(?:不对，|改为|更正为|是|属于)", "", remaining)
    values: dict[str, str] = {}
    patterns = {
        "competition_category": r"(?:行业)?(?:省级)?([一二])类(?:竞赛)?",
        "award_level": r"([一二三])等奖",
        "recipient_type": r"个人|团队|团体",
    }
    for field, pattern in patterns.items():
        matches = list(re.finditer(pattern, remaining))
        if len(matches) > 1:
            return {}
        if matches:
            match = matches[0]
            raw = match.group(0)
            values[field] = raw if field != "recipient_type" else {"团体": "团队"}.get(raw, raw)
            remaining = remaining[:match.start()] + remaining[match.end():]
    # 通用字段必须带标签，避免把“财务制度怎么报销”误当成部门确认。
    for piece in re.split(r"[，,；;\n]", remaining):
        piece = piece.strip(" 。！!、")
        if not piece:
            continue
        match = re.fullmatch(r"(部门|适用部门|日期|适用日期|业务情形)[:：]\s*(.{1,80})", piece)
        if not match:
            return {}
        field = {"部门": "department", "适用部门": "department", "日期": "applicable_date", "适用日期": "applicable_date", "业务情形": "business_scenario"}[match[1]]
        if field in values:
            return {}
        value = match[2].strip()
        if field == "applicable_date":
            try:
                value = date.fromisoformat(value).isoformat()
            except ValueError:
                return {}
        values[field] = value
    return values


def resolve_context(content, message_id, previous, question, scope, selected_ids):
    """以最近一次完整问答和同范围快照为边界；返回检索问题与可审计用户条件快照。"""
    fresh = {"root_question": content, "root_message_id": message_id, "confirmed": {}}
    if previous is None or question is None:
        return content, fresh
    same_scope = (
        previous.query_scope == scope.query_scope
        and previous.query_index_run_id == scope.index_run_id
        and previous.access_scope_hash == scope.scope_hash
        and previous.access_scope_version == scope.access_policy_version
        and previous.document_selection_mode == scope.user_selection_mode
        and sorted(json.loads(previous.selected_document_ids_json)) == sorted(set(selected_ids))
    )
    if not same_scope:
        return content, fresh
    pending = set(json.loads(previous.missing_fields_json or "[]")) if previous.reason_code == "MISSING_USER_CONTEXT" else set()
    old = json.loads(previous.conversation_context_json or "null")
    confirmed = dict(old.get("confirmed", {})) if old else {}
    values = explicit_values(content)
    # 仅在存在待澄清项或可纠正的用户确认项时承接，其他输入开始独立问题。
    if not values or not (set(values) & (pending | set(confirmed))):
        return content, fresh
    context = old or {"root_question": question.content, "root_message_id": question.id, "confirmed": {}}
    for field, value in values.items():
        confirmed[field] = {"value": value, "source_message_id": message_id}
    context = {**context, "confirmed": confirmed}
    conditions = "；".join(f"{LABELS[key]}：{confirmed[key]['value']}" for key in LABELS if key in confirmed)
    query = f"原始问题：{context['root_question']}\n用户已明确确认的条件（替代原问题同名条件）：{conditions}\n请根据上述条件回答原始问题；未确认的条件仍需澄清。"
    if len(query) > 4000:
        return content, fresh
    return query, context
