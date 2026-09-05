"""制度元数据、Node 树和结构校验规则。

该文件只对 accepted_final 的 Source Block 做确定性分析；模糊结果保留候选、
置信度和审核原因，不使用大模型改写任何制度文字。
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any


CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3,
                  "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUMBER_TOKEN = r"[零〇一二三四五六七八九十百千万两\d]+"

PATTERNS = {
    "chapter": re.compile(rf"^(第{NUMBER_TOKEN}章)\s*(.*)$"),
    "section": re.compile(rf"^(第{NUMBER_TOKEN}节)\s*(.*)$"),
    "article": re.compile(rf"^(第{NUMBER_TOKEN}条)\s*(.*)$"),
    "attachment": re.compile(rf"^(附件\s*{NUMBER_TOKEN}?[：:]?)\s*(.*)$"),
    "heading": re.compile(rf"^({NUMBER_TOKEN}[、])\s*(.*)$"),
    "item_chinese": re.compile(rf"^([（(]{NUMBER_TOKEN}[）)])\s*(.*)$"),
    "item_decimal": re.compile(r"^(\d+[\.．、])\s*(.*)$"),
    "item_paren_decimal": re.compile(r"^([（(]\d+[）)])\s*(.*)$"),
    "item_circled": re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)$"),
}

NORMATIVE_WORDS = ("应当", "必须", "不得", "严禁", "可以", "负责", "按照", "依照", "由", "为")
ARTICLE_TITLE_HEURISTIC_MAX_LENGTH = 40
ARTICLE_TITLE_STRONG_MAX_LENGTH = 80
ARTICLE_SENTENCE_PUNCTUATION = re.compile(r"[。；;！？!?]")
ARTICLE_NORMATIVE_CLAUSE = re.compile(
    r"(?:应当|必须|不得|严禁|可以|负责|按照|依照|予以|由.{0,16}(?:负责|办理|实施))"
)
ARTICLE_LEAD_IN_CLAUSE = re.compile(
    r"(?:有下列|包括下列|符合下列|按照下列|具体如下|规定如下|要求如下|事项如下)"
)
DOCUMENT_TYPES = ("办法", "细则", "规定", "规程", "规范", "通知",
                  "方案", "意见", "计划", "报告", "标准", "制度")
ADDRESSEE_TOKENS = ("单位", "部门", "机关", "公司", "学会", "站", "局")
FULL_DATE_PATTERN = re.compile(r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日")
SIGNATURE_ORG_TOKENS = ("局", "公司", "委员会", "工会", "学会",
                        "鉴定站", "办公室", "中心", "处", "部门")
COMPLETE_DOCUMENT_CODE_PATTERN = re.compile(
    r"[\u4e00-\u9fa5A-Za-z]{1,12}[〔\[]\d{4}[〕\]]\s*\d+\s*号"
)
INCOMPLETE_DOCUMENT_CODE_PATTERN = re.compile(
    r"[\u4e00-\u9fa5A-Za-z]{1,12}[〔\[]\d{4}[〕\]]\s*号(?:\s*[\u4e00-\u9fa5])?"
)
DATE_CONTEXT_EXCLUSION_KEYWORDS = (
    "生效",
    "施行",
    "实施日期",
    "印发",
    "截至",
    "截止",
    "有效期",
    "前完成",
)


def _looks_like_signature_org(text: str) -> bool:
    """判断短文本是否像落款中的发文机关名称。"""

    return (
        2 <= len(text) <= 80
        and not text.endswith(("：", ":", "。", "；", ";"))
        and "印发" not in text
        and any(token in text for token in SIGNATURE_ORG_TOKENS)
    )


def chinese_to_int(value: str) -> int | None:
    """解析常见中文条款编号，超出简单规则时返回 None。"""

    if value.isdigit():
        return int(value)
    value = value.replace("两", "二")
    if all(char in CHINESE_DIGITS for char in value):
        number = 0
        for char in value:
            number = number * 10 + CHINESE_DIGITS[char]
        return number
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if not all(char in CHINESE_DIGITS or char in units for char in value):
        return None
    total = 0
    section = 0
    current = 0
    for char in value:
        if char in CHINESE_DIGITS:
            current = CHINESE_DIGITS[char]
        elif char == "万":
            section = (section + current) * 10000
            total += section
            section = 0
            current = 0
        else:
            unit = units[char]
            if current == 0:
                current = 1
            section += current * unit
            current = 0
    return total + section + current


def _main_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in blocks
        if block["part_type"] == "document"
        and block["excluded_role"] == "none"
        and block["block_type"] in {"paragraph", "table"}
        and block["clean_text"]
    ]


def classify_article_remainder(rest: str, next_text: str) -> dict[str, Any]:
    """判定“第X条”后的文字是条标题还是条文正文。

    冒号与紧随子项构成强结构证据；普通短文本只作为待人工确认的启发式标题。
    长正文、完整句子和规范性领起句始终按正文处理，避免结构证据误吞条文内容。
    """

    normalized = rest.strip()
    next_is_item = any(
        pattern.match(next_text)
        for name, pattern in PATTERNS.items()
        if name.startswith("item_")
    )
    has_sentence_punctuation = bool(
        ARTICLE_SENTENCE_PUNCTUATION.search(normalized.rstrip("：:"))
    )
    has_normative_clause = bool(ARTICLE_NORMATIVE_CLAUSE.search(normalized))
    has_lead_in_clause = bool(ARTICLE_LEAD_IN_CLAUSE.search(normalized))
    if (
        not next_is_item
        or len(normalized) > ARTICLE_TITLE_STRONG_MAX_LENGTH
        or has_sentence_punctuation
        or has_normative_clause
        or has_lead_in_clause
    ):
        return {"kind": "content", "title": None, "needs_review": False}
    if normalized.endswith(("：", ":")):
        return {
            "kind": "strong",
            "title": normalized.rstrip("：:").rstrip(),
            "needs_review": False,
        }
    if (
        len(normalized) <= ARTICLE_TITLE_HEURISTIC_MAX_LENGTH
        and not any(word in normalized for word in NORMATIVE_WORDS)
    ):
        return {"kind": "heuristic", "title": normalized, "needs_review": True}
    return {"kind": "content", "title": None, "needs_review": False}


def extract_metadata(
    blocks: list[dict[str, Any]], file_name: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """提取文档级字段候选，并返回可直接确认的高置信度值。"""

    main = _main_blocks(blocks)
    candidates: list[dict[str, Any]] = []
    confirmed: dict[str, Any] = {}

    def add(
        name: str,
        value: str,
        block: dict[str, Any] | None,
        confidence: float,
        rule_id: str,
        *,
        normalized: str | None = None,
    ) -> None:
        if not value:
            return
        review = "confirmed" if confidence >= 0.9 else "pending"
        candidates.append(
            {
                "field_name": name,
                "raw_value": value,
                "normalized_value": normalized if normalized is not None else value.strip(),
                "source_block_key": block["temp_key"] if block else None,
                "confidence": confidence,
                "decision_method": "rule",
                "rule_id": rule_id,
                "review_status": review,
            }
        )
        if confidence >= 0.9 and name not in confirmed:
            confirmed[name] = normalized if normalized is not None else value.strip()

    title_block: dict[str, Any] | None = None
    title_text = ""
    title_score = -1.0
    early_blocks = main[:20]
    for index, block in enumerate(early_blocks):
        if block["block_type"] != "paragraph":
            continue
        props = block.get("properties", {})
        if props.get("alignment") != "center":
            continue
        group = [block]
        group_text = block["clean_text"]
        # 标题可以被拆为 2～3 行；后续行偶尔错误标成左对齐，但字号和顺序仍一致。
        for adjacent in early_blocks[index + 1: index + 3]:
            adjacent_props = adjacent.get("properties", {})
            if (
                adjacent["block_type"] == "paragraph"
                and adjacent_props.get("font_size_half_points") == props.get("font_size_half_points")
                and adjacent["order_no"] - group[-1]["order_no"] <= 3
                and adjacent_props.get("alignment") in {"center", "left"}
                and len(group_text + adjacent["clean_text"]) <= 180
            ):
                group.append(adjacent)
                group_text += adjacent["clean_text"]
            else:
                break
        if not 4 <= len(group_text) <= 180 or group_text.endswith("："):
            continue
        score = 3.0
        if props.get("bold"):
            score += 1.5
        if (props.get("font_size_half_points") or 0) >= 40:
            score += 2.0
        if any(kind in group_text for kind in DOCUMENT_TYPES):
            score += 3.0
        if "关于" in group_text or "印发" in group_text:
            score += 2.0
        if index <= 8:
            score += 1.0
        if group_text.endswith("文件") and not any(kind in group_text for kind in DOCUMENT_TYPES):
            score -= 3.0
        if re.search(r"〔\d{4}〕", group_text) or re.search(r"\d{4}年\d{1,2}月", group_text):
            score -= 5.0
        if score > title_score:
            title_score, title_block, title_text = score, block, group_text

    if title_block and title_score >= 3.0:
        confidence = min(0.99, 0.65 + title_score * 0.05)
        add("title", title_text, title_block, confidence, "META_TITLE_STYLE_V2")
    else:
        fallback = Path(file_name).stem
        candidates.append(
            {
                "field_name": "title",
                "raw_value": fallback,
                "normalized_value": fallback,
                "source_block_key": None,
                "confidence": 0.4,
                "decision_method": "rule",
                "rule_id": "META_TITLE_FILENAME_FALLBACK_V1",
                "review_status": "pending",
            }
        )

    date_pattern = re.compile(r"((?:19|20)\d{2})年(\d{1,2})月(\d{1,2})日")
    for block in main:
        text = block["clean_text"]
        if match := COMPLETE_DOCUMENT_CODE_PATTERN.search(text):
            add("document_code", match.group(0),
                block, 0.98, "META_DOC_CODE_REGEX_V1")
            break
        if match := INCOMPLETE_DOCUMENT_CODE_PATTERN.search(text):
            # 不补造缺失的发文序号，只保存原文候选并要求人工确认。
            add(
                "document_code",
                match.group(0),
                block,
                0.80,
                "META_DOC_CODE_INCOMPLETE_V1",
                normalized=re.sub(r"\s+", " ", match.group(0)).strip(),
            )
            break

    date_matches: list[tuple[int, dict[str, Any], re.Match[str], bool]] = []
    for index, block in enumerate(main):
        for match in date_pattern.finditer(block["clean_text"]):
            has_exclusion_keyword = any(
                keyword in block["clean_text"] for keyword in DATE_CONTEXT_EXCLUSION_KEYWORDS
            )
            date_matches.append((index, block, match, has_exclusion_keyword))
    if date_matches:
        signature_dates: list[tuple[int,
                                    dict[str, Any], re.Match[str], bool]] = []
        for item in date_matches:
            index, block, match, has_exclusion_keyword = item
            if has_exclusion_keyword:
                continue
            previous_texts = [
                candidate["clean_text"] for candidate in main[max(0, index - 2): index]
            ]
            same_block_without_date = date_pattern.sub(
                "", block["clean_text"]).strip(" ，,。；;：:\t")
            if _looks_like_signature_org(same_block_without_date) or any(
                _looks_like_signature_org(value) for value in previous_texts
            ):
                signature_dates.append(item)

        if signature_dates:
            # 正文首次出现的明确落款优先于后续附件落款或版记日期。
            _, block, match, _ = signature_dates[0]
            confidence = 0.95
            rule_id = "META_DATE_SIGNATURE_CONTEXT_V2"
        elif len(date_matches) == 1 and not date_matches[0][3]:
            _, block, match, _ = date_matches[0]
            confidence = 0.92
            rule_id = "META_DATE_SINGLE_UNAMBIGUOUS_V2"
        else:
            plausible = [item for item in date_matches if not item[3]]
            _, block, match, _ = (
                plausible[-1] if plausible else date_matches[-1])
            confidence = 0.84 if plausible else 0.80
            rule_id = (
                "META_DATE_MULTIPLE_AMBIGUOUS_V2"
                if plausible
                else "META_DATE_KEYWORD_AMBIGUOUS_V2"
            )
        iso_date = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        add("publish_date", match.group(0), block,
            confidence, rule_id, normalized=iso_date)

    for block in main[:20]:
        text = block["clean_text"]
        if text.endswith(("：", ":")) and any(token in text for token in ADDRESSEE_TOKENS):
            add("addressee_text", text, block, 0.9, "META_ADDRESSEE_PREFIX_V1")
            break

    title_value = next((item["normalized_value"]
                       for item in candidates if item["field_name"] == "title"), "")
    type_positions = [(title_value.rfind(kind), kind)
                      for kind in DOCUMENT_TYPES if kind in title_value]
    document_type = max(type_positions)[1] if type_positions else None
    if document_type:
        add("document_type", document_type, title_block,
            0.95, "META_DOCUMENT_TYPE_TITLE_V1")

    if "关于" in title_value:
        organization = title_value.split("关于", 1)[0].strip()
        if 2 <= len(organization) <= 60:
            add("issuing_org", organization, title_block,
                0.82, "META_ORG_TITLE_PREFIX_V1")

    # 归口部门只在正文存在明确归口/解释责任表述时提取，不能直接等同于发文机关。
    owner_patterns = (
        (re.compile(
            r"(?:归口管理部门|归口部门|责任部门|牵头部门)[：:]\s*([^。；;\n]{2,50})"), 0.96, "META_OWNER_DEPARTMENT_LABEL_V1"),
        (re.compile(
            r"本(?:办法|规定|细则|制度|方案)[^。；;]{0,80}?由([^，。；;]{2,50}?)(?:负责解释|归口管理)"), 0.92, "META_OWNER_DEPARTMENT_CLAUSE_V1"),
    )
    owner_found = False
    for block in main:
        for pattern, confidence, rule_id in owner_patterns:
            if match := pattern.search(block["clean_text"]):
                add("owner_department", match.group(
                    1).strip(), block, confidence, rule_id)
                owner_found = True
                break
        if owner_found:
            break

    profile = "generic"
    all_text = "\n".join(block["clean_text"] for block in main[:80])
    if re.search(rf"第{NUMBER_TOKEN}条", all_text):
        profile = "article_based"
    elif re.search(rf"^{NUMBER_TOKEN}、", all_text, re.MULTILINE):
        profile = "heading_based"
    if any(block["block_type"] == "table" for block in main):
        profile = "mixed" if profile != "generic" else "form_based"
    candidates.append(
        {
            "field_name": "parser_profile",
            "raw_value": profile,
            "normalized_value": profile,
            "source_block_key": None,
            "confidence": 0.9,
            "decision_method": "rule",
            "rule_id": "PARSER_PROFILE_STRUCTURE_V1",
            "review_status": "confirmed",
        }
    )
    confirmed["parser_profile"] = profile
    return candidates, confirmed


def _classify(
    block: dict[str, Any], index: int, main: list[dict[str, Any]], stack: list[dict[str, Any]]
) -> dict[str, Any]:
    text = block["clean_text"]
    props = block.get("properties", {})
    if block["block_type"] == "table":
        return {"type": "table", "number": None, "rest": text, "confidence": 1.0, "method": "ooxml", "rule": "NODE_TABLE_XML_V1", "rank": None}

    if COMPLETE_DOCUMENT_CODE_PATTERN.fullmatch(text):
        return {"type": "document_code", "number": None, "rest": text, "confidence": 0.99, "method": "rule", "rule": "NODE_DOCUMENT_CODE_COMPLETE_V1", "rank": None}
    if INCOMPLETE_DOCUMENT_CODE_PATTERN.fullmatch(text):
        return {"type": "document_code", "number": None, "rest": text, "confidence": 0.80, "method": "score", "rule": "NODE_DOCUMENT_CODE_INCOMPLETE_V1", "rank": None, "candidates": ["document_code", "paragraph"]}

    for node_type in ("chapter", "section", "article", "attachment"):
        match = PATTERNS[node_type].match(text)
        if match:
            rank = {"chapter": 1, "section": 2,
                    "article": 3, "attachment": 1}[node_type]
            return {"type": node_type, "number": match.group(1), "rest": match.group(2).strip(), "confidence": 0.99, "method": "rule", "rule": f"NODE_{node_type.upper()}_REGEX_V1", "rank": rank}

    if re.match(r"^(送|分送|抄送|印发)[：:]", text):
        return {"type": "distribution", "number": None, "rest": text, "confidence": 0.98, "method": "rule", "rule": "NODE_DISTRIBUTION_V1", "rank": None}
    if "办公室" in text and "印发" in text and FULL_DATE_PATTERN.search(text):
        return {"type": "distribution", "number": None, "rest": text, "confidence": 0.98, "method": "context_rule", "rule": "NODE_DISTRIBUTION_IMPRINT_V1", "rank": None}

    # 公文落款后面可能继续出现附件，不能只依赖“全文最后几段”判断。
    looks_like_org = _looks_like_signature_org(text)
    following_texts = [item["clean_text"]
                       for item in main[index + 1: index + 3]]
    previous_texts = [item["clean_text"]
                      for item in main[max(0, index - 2): index]]
    if looks_like_org and any(FULL_DATE_PATTERN.search(value) for value in following_texts):
        return {"type": "signature", "number": None, "rest": text, "confidence": 0.95, "method": "context_rule", "rule": "NODE_SIGNATURE_ORG_BEFORE_DATE_V1", "rank": None}
    if FULL_DATE_PATTERN.fullmatch(text.strip()) and any(
        _looks_like_signature_org(value)
        for value in previous_texts
    ):
        return {"type": "signature", "number": None, "rest": text, "confidence": 0.95, "method": "context_rule", "rule": "NODE_SIGNATURE_DATE_AFTER_ORG_V1", "rank": None}

    if index < 12 and text.endswith(("：", ":")) and any(token in text for token in ADDRESSEE_TOKENS):
        return {"type": "addressee", "number": None, "rest": text, "confidence": 0.88, "method": "rule", "rule": "NODE_ADDRESSEE_V1", "rank": None}

    if index >= max(0, len(main) - 8) and FULL_DATE_PATTERN.search(text):
        return {"type": "signature", "number": None, "rest": text, "confidence": 0.85, "method": "rule", "rule": "NODE_SIGNATURE_DATE_V1", "rank": None}

    current_types = {item["node_type"] for item in stack}
    if match := PATTERNS["heading"].match(text):
        rest = match.group(2).strip()
        looks_like_numbered_paragraph = len(
            rest) > 30 or bool(re.search(r"[。；;]$", rest))
        if "article" in current_types or looks_like_numbered_paragraph:
            return {"type": "item", "number": match.group(1), "rest": rest, "confidence": 0.88, "method": "score", "rule": "NODE_HEADING_OR_ITEM_CONTEXT_V2", "rank": 5, "candidates": ["heading", "item"]}
        outline = props.get("outline_level")
        rank = min(3, int(
            outline) + 1) if outline is not None else (2 if "chapter" in current_types else 1)
        return {"type": "heading", "number": match.group(1), "rest": rest, "confidence": 0.9, "method": "score", "rule": "NODE_HEADING_CONTEXT_V1", "rank": rank}

    for pattern_name, depth in (("item_chinese", 1), ("item_decimal", 2), ("item_paren_decimal", 3), ("item_circled", 4)):
        if match := PATTERNS[pattern_name].match(text):
            return {"type": "item", "number": match.group(1), "rest": match.group(2).strip(), "confidence": 0.96, "method": "rule", "rule": f"NODE_{pattern_name.upper()}_V1", "rank": 4 + depth}

    if block.get("display_number"):
        outline = props.get("outline_level")
        if outline is not None and int(outline) <= 2:
            return {"type": "heading", "number": block["display_number"], "rest": text, "confidence": 0.92, "method": "numbering", "rule": "NODE_NATIVE_NUMBER_HEADING_V1", "rank": int(outline) + 1}
        depth = int(block.get("numbering_level") or 0)
        return {"type": "item", "number": block["display_number"], "rest": text, "confidence": 0.95, "method": "numbering", "rule": "NODE_NATIVE_NUMBER_ITEM_V1", "rank": 5 + depth}

    if index < 20 and not stack and text.startswith(("为", "根据", "按照")):
        return {"type": "preamble", "number": None, "rest": text, "confidence": 0.86, "method": "rule", "rule": "NODE_PREAMBLE_PREFIX_V1", "rank": None}

    return {"type": "paragraph", "number": None, "rest": text, "confidence": 0.88, "method": "rule", "rule": "NODE_PARAGRAPH_FALLBACK_V2", "rank": None}


def build_nodes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """使用规则和层级栈构建 Node Tree。"""

    main = _main_blocks(blocks)
    nodes: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    node_by_key: dict[str, dict[str, Any]] = {}

    for index, block in enumerate(main):
        decision = _classify(block, index, main, stack)
        rank = decision.get("rank")
        parent: dict[str, Any] | None = None
        if rank is not None:
            while stack and stack[-1]["rank"] >= rank:
                stack.pop()
            parent = stack[-1] if stack else None
        elif decision["type"] in {"paragraph", "table"}:
            parent = stack[-1] if stack else None

        node_key = f"node-{index + 1}"
        level = (parent["level"] + 1) if parent else 1
        rest = decision["rest"]
        title: str | None = None
        content: str | None = rest or None
        if decision["type"] in {"chapter", "section", "heading", "attachment"}:
            title, content = rest or None, None
        article_title_decision: dict[str, Any] | None = None
        if decision["type"] == "article" and rest:
            next_text = main[index + 1]["clean_text"] if index + \
                1 < len(main) else ""
            article_title_decision = classify_article_remainder(rest, next_text)
            if article_title_decision["title"]:
                title, content = article_title_decision["title"], None
                decision["rule"] = f"NODE_ARTICLE_TITLE_{article_title_decision['kind'].upper()}_V2"

        parent_path = parent["path"] if parent else ""
        path = f"{parent_path}/{decision['type']}_{index + 1}" if parent_path else f"{decision['type']}_{index + 1}"
        label = title or decision.get("number") or (
            content[:32] if content else decision["type"])
        parent_path_text = parent["path_text"] if parent else ""
        path_text = f"{parent_path_text} > {label}" if parent_path_text else label
        node = {
            "temp_key": node_key,
            "parent_temp_key": parent["temp_key"] if parent else None,
            "source_block_key": block["temp_key"],
            "node_type": decision["type"],
            "node_number": decision.get("number"),
            "title": title,
            "raw_text": block["raw_text"],
            "content": content,
            "normalized_content": block["clean_text"],
            "level": level,
            "path": path,
            "path_text": path_text,
            "order_no": index + 1,
            "parser_confidence": decision["confidence"],
            "decision_method": decision["method"],
            "rule_id": decision["rule"],
            "candidate_types": decision.get("candidates", []),
            "review_status": "pending" if (
                decision["confidence"] < 0.85
                or bool(article_title_decision and article_title_decision["needs_review"])
            ) else "confirmed",
            "review_reason": (
                "条标题由结构启发式识别，请确认标题或改为条文正文"
                if article_title_decision and article_title_decision["needs_review"]
                else ("节点类型存在歧义" if decision["confidence"] < 0.85 else None)
            ),
            "rank": rank,
        }
        nodes.append(node)
        node_by_key[node_key] = node
        if rank is not None:
            stack.append(node)

    return nodes


def validate_structure(
    blocks: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    statistics: dict[str, Any],
    *,
    image_issue_severity: str = "review",
    character_error_threshold: float = 0.95,
    character_review_threshold: float = 0.98,
) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    """校验结构连续性、来源覆盖率和不支持对象。"""

    issues: list[dict[str, Any]] = []
    mapped_block_keys = {node["source_block_key"] for node in nodes}
    eligible = _main_blocks(blocks)

    for node in nodes:
        if not node["raw_text"] and node["node_type"] != "table":
            issues.append({"stage": "structure_validation", "issue_code": "EMPTY_NODE",
                          "severity": "error", "message": "Node 没有原文", "node_key": node["temp_key"]})
        if node["node_type"] == "paragraph" and node["raw_text"].strip() in {"。", ".", "；", ";"}:
            issues.append({"stage": "structure_validation", "issue_code": "ABNORMAL_SHORT_NODE",
                          "severity": "error", "message": "发现只有标点的异常段落", "node_key": node["temp_key"]})
        if len(node["raw_text"]) > 5000:
            issues.append({"stage": "structure_validation", "issue_code": "OVERSIZED_NODE", "severity": "warning",
                          "message": "单个 Node 超过 5000 字符", "node_key": node["temp_key"], "details": {"length": len(node["raw_text"])}})
        if node["parser_confidence"] < 0.85:
            issues.append({"stage": "structure_validation", "issue_code": "LOW_STRUCTURE_CONFIDENCE", "severity": "review", "message": "节点类型需要人工确认",
                          "node_key": node["temp_key"], "details": {"confidence": node["parser_confidence"], "candidates": node["candidate_types"]}})
        if node.get("rule_id") == "NODE_ARTICLE_TITLE_HEURISTIC_V2":
            issues.append({
                "stage": "structure_validation",
                "issue_code": "NODE_ARTICLE_TITLE_HEURISTIC",
                "severity": "review",
                "message": "条标题由结构启发式识别，请人工确认标题或改为条文正文",
                "node_key": node["temp_key"],
                "details": {"title": node.get("title"), "node_number": node.get("node_number")},
            })

    groups: dict[str | None, list[int]] = defaultdict(list)
    for node in nodes:
        if node["node_type"] != "article" or not node.get("node_number"):
            continue
        token_match = re.search(NUMBER_TOKEN, node["node_number"])
        number = chinese_to_int(token_match.group(0)) if token_match else None
        if number is not None:
            groups[node.get("parent_temp_key")].append(number)
    for parent, numbers in groups.items():
        for previous, current in zip(numbers, numbers[1:]):
            if current != previous + 1:
                issues.append({"stage": "structure_validation", "issue_code": "ARTICLE_SEQUENCE_GAP", "severity": "warning",
                              "message": f"条款编号不连续：第{previous}条后为第{current}条", "node_key": parent, "details": {"previous": previous, "current": current}})

    for block in eligible:
        if block["temp_key"] not in mapped_block_keys:
            issues.append({"stage": "coverage_validation", "issue_code": "UNMAPPED_BLOCK", "severity": "error",
                          "message": "有效 Source Block 未映射到 Node", "source_block_key": block["temp_key"]})

    denominator_chars = sum(len(block["raw_text"]) for block in eligible)
    mapped_chars = sum(len(block["raw_text"])
                       for block in eligible if block["temp_key"] in mapped_block_keys)
    character_coverage = mapped_chars / \
        denominator_chars if denominator_chars else 1.0
    block_coverage = sum(
        block["temp_key"] in mapped_block_keys for block in eligible) / len(eligible) if eligible else 1.0
    table_blocks = [
        block for block in eligible if block["block_type"] == "table"]
    table_cell_coverage = sum(
        block["temp_key"] in mapped_block_keys for block in table_blocks) / len(table_blocks) if table_blocks else 1.0

    if statistics.get("comments"):
        issues.append({"stage": "source_extraction", "issue_code": "COMMENTS_DETECTED", "severity": "review",
                      "message": "DOCX 包含批注，批注未并入制度正文", "details": {"count": statistics["comments"]}})
    for textbox in (
        block for block in blocks if block.get("excluded_role") == "textbox_review"
    ):
        issues.append(
            {
                "stage": "source_extraction",
                "issue_code": "TEXTBOX_DETECTED",
                "severity": "review",
                "message": "DOCX 正文包含文本框，需要人工确认其内容和层级",
                "source_block_key": textbox["temp_key"],
                "details": {
                    "part_type": textbox["part_type"],
                    "source_locator": textbox.get("source_locator", {}),
                    "raw_text": textbox["raw_text"],
                    "excluded_role": "textbox_review",
                    "suggested_action": "确认进入正文、保持排除或调整层级",
                },
            }
        )
    for image in (
        block for block in blocks if block.get("excluded_role") == "image_review"
    ):
        image_issue_code = (
            "BODY_IMAGE_NOT_OCR" if image_issue_severity == "warning" else "BODY_IMAGE_REQUIRES_REVIEW"
        )
        issues.append(
            {
                "stage": "source_extraction",
                "issue_code": image_issue_code,
                "severity": image_issue_severity,
                "message": "DOCX 图片已保留来源关系但未做 OCR；当前按上游人工筛选策略放行"
                if image_issue_severity == "warning"
                else "DOCX 正文包含未 OCR 的图片，需要确认是否承载制度内容",
                "source_block_key": image["temp_key"],
                "details": {
                    "part_type": image["part_type"],
                    "source_locator": image.get("source_locator", {}),
                    "relationship": image.get("properties", {}),
                    "suggested_action": "上游过滤实质图片资料；如图片承载正文，转成文本/表格后重新解析",
                },
            }
        )
    if character_coverage < character_error_threshold:
        issues.append({"stage": "coverage_validation", "issue_code": "LOW_CHARACTER_COVERAGE",
                      "severity": "error", "message": f"正文字符覆盖率低于 {character_error_threshold:.1%}",
                      "details": {"coverage": character_coverage, "threshold": character_error_threshold}})
    elif character_coverage < character_review_threshold:
        issues.append({"stage": "coverage_validation", "issue_code": "REVIEW_CHARACTER_COVERAGE",
                      "severity": "review", "message": f"正文字符覆盖率低于 {character_review_threshold:.1%}",
                      "details": {"coverage": character_coverage, "threshold": character_review_threshold}})

    metrics: dict[str, float | int] = {
        "character_coverage": character_coverage,
        "block_coverage": block_coverage,
        "table_cell_coverage": table_cell_coverage,
        "unmapped_block_count": len(eligible) - len(mapped_block_keys & {block["temp_key"] for block in eligible}),
    }
    return issues, metrics
