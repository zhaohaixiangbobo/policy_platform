"""文件说明：验证解析阈值、Worker与审核服务失败运行守卫的最小契约。"""


import pytest

from knowledge.parser.analyzer import build_nodes, classify_article_remainder, validate_structure
from knowledge.parser.pipeline import ParserConfig
from worker import KnowledgeRunFailedError, ensure_knowledge_run_succeeded


def _coverage_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    blocks = [
        {"temp_key": "mapped", "raw_text": "甲" * 96, "clean_text": "甲" * 96, "part_type": "document", "block_type": "paragraph", "excluded_role": "none"},
        {"temp_key": "unmapped", "raw_text": "乙" * 4, "clean_text": "乙" * 4, "part_type": "document", "block_type": "paragraph", "excluded_role": "none"},
    ]
    nodes = [
        {"source_block_key": "mapped", "raw_text": "甲" * 96, "node_type": "paragraph", "node_number": None, "parser_confidence": 1.0},
    ]
    return blocks, nodes


def test_character_coverage_uses_parser_configuration() -> None:
    blocks, nodes = _coverage_fixture()
    issues, _metrics = validate_structure(
        blocks,
        nodes,
        {},
        character_error_threshold=0.90,
        character_review_threshold=0.97,
    )

    coverage_issue = next(issue for issue in issues if issue["issue_code"] == "REVIEW_CHARACTER_COVERAGE")
    assert coverage_issue["details"]["threshold"] == 0.97
    assert "97.0%" in coverage_issue["message"]


def test_parser_configuration_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="error <= review"):
        ParserConfig(character_error_threshold=0.99, character_review_threshold=0.98)


def test_parser_configuration_rejects_automatic_activation() -> None:
    with pytest.raises(ValueError, match="自动激活已禁用"):
        ParserConfig(auto_activate=True)


def test_article_title_rules_prioritize_structure_and_expose_heuristic_review() -> None:
    """长条标题可由冒号强证据识别，模糊短标题必须进入人工复核。"""

    strong = classify_article_remainder(
        "关于专业技能竞赛表彰奖励范围和标准的具体规定：", "（一）国家级竞赛"
    )
    normative = classify_article_remainder(
        "有下列情形之一的，应当予以奖励：", "（一）获得一等奖"
    )
    assert strong == {
        "kind": "strong", "title": "关于专业技能竞赛表彰奖励范围和标准的具体规定", "needs_review": False,
    }
    assert normative["kind"] == "content"

    def block(key: str, text: str) -> dict[str, object]:
        return {
            "temp_key": key, "raw_text": text, "clean_text": text,
            "part_type": "document", "block_type": "paragraph",
            "excluded_role": "none", "properties": {},
        }

    blocks = [block("b1", "第四条 奖励发放"), block("b2", "（一）按月发放")]
    nodes = build_nodes(blocks)
    issues, _metrics = validate_structure(blocks, nodes, {})
    assert nodes[0]["title"] == "奖励发放"
    assert nodes[0]["review_status"] == "pending"
    assert nodes[0]["rule_id"] == "NODE_ARTICLE_TITLE_HEURISTIC_V2"
    assert any(item["issue_code"] == "NODE_ARTICLE_TITLE_HEURISTIC" for item in issues)


def test_worker_rejects_failed_run_result() -> None:
    with pytest.raises(KnowledgeRunFailedError) as captured:
        ensure_knowledge_run_succeeded(
            "PARSE_RUN",
            {"id": 12, "status": "failed", "error_code": "PIPELINE_EXCEPTION", "error_message": "解析异常"},
        )

    assert captured.value.run_id == 12
    assert captured.value.retryable is True


def test_worker_accepts_reviewable_run_result() -> None:
    ensure_knowledge_run_succeeded("CHUNK_RUN", {"id": 13, "status": "review_required"})
