"""文件说明：学习自测短期槽位、公开投影和确定性评分；知识取材通过只读服务完成。"""

import json
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.infrastructure.db.models import LearningAssessmentSlot, utc_now


def encode(data):
    return json.dumps(data, ensure_ascii=False)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def clean_slot(row, timeout_seconds: int):
    """读取和Worker扫描均执行过期判定；过期立即不可见，不依赖物理清理时机。"""
    now = utc_now()
    if row.expires_at and aware(row.expires_at) <= now:
        row.current_id = row.current_json = row.expires_at = None
        if row.task_state == "READY":
            row.task_state, row.progress = "EXPIRED", "最近一次检测已过期，请重新生成"
    if row.task_state == "GENERATING" and aware(row.task_created_at) + timedelta(seconds=timeout_seconds) <= now:
        row.task_state, row.progress = "FAILED", "生成超时，请重试"
        row.error_message = "生成未在任务有效期内完成，原检测不受影响"
        row.pending_json = None


def score_questions(questions: list[dict], answers: dict) -> dict:
    ids = {question["question_id"] for question in questions}
    if not set(answers) <= ids:
        raise ValueError("答案包含不属于本次检测的题目")
    groups, details = {}, []
    for question in questions:
        answer = answers.get(question["question_id"], [])
        if len(set(answer)) != len(answer) or any(type(i) is not int or i < 0 or i >= len(question["options"]) for i in answer):
            raise ValueError("作答选项非法")
        if question["question_type"] != "MULTIPLE" and len(answer) > 1:
            raise ValueError("单选或判断题只能选择一个答案")
        correct = bool(answer) and set(answer) == set(question["correct_answer"])
        details.append({"question_id": question["question_id"], "correct": correct, "unanswered": not answer})
        group = groups.setdefault(question["primary_node_id"], {
            "primary_node_id": question["primary_node_id"], "knowledge_point": question["knowledge_point"],
            "total": 0, "wrong": 0, "unanswered": 0})
        group["total"] += 1
        group["wrong"] += int(not correct and bool(answer))
        group["unanswered"] += int(not answer)
    correct_count = sum(item["correct"] for item in details)
    return {"score": round(correct_count * 100 / len(questions), 1), "correct": correct_count,
            "total": len(questions), "unanswered": sum(item["unanswered"] for item in details),
            "details": details, "weak_points": sorted(
                [item for item in groups.values() if item["wrong"] or item["unanswered"]],
                key=lambda item: -(item["wrong"] + item["unanswered"]) / item["total"])}


def public_current(data: dict) -> dict:
    """以白名单输出答题内容；提交前绝不下发答案、解析、证据或知识点标签。"""
    result = {key: value for key, value in data.items() if key != "questions"}
    if data["status"] == "SUBMITTED":
        result["questions"] = data["questions"]
    else:
        keys = {"question_id", "question_type", "question", "options"}
        result["questions"] = [{key: value for key, value in item.items() if key in keys} for item in data["questions"]]
    return result


class LearningService:
    def __init__(self, session: Session, user_id: str, settings):
        self.session, self.user_id, self.settings = session, user_id, settings

    def slot(self):
        row = self.session.get(LearningAssessmentSlot, self.user_id)
        if row:
            clean_slot(row, self.settings.learning_assessment_task_timeout_seconds)
        return row

    def start(self, source: dict, counts: dict, request_id: str):
        row = self.slot()
        if row is None:
            row = LearningAssessmentSlot(user_id=self.user_id)
            self.session.add(row)
        if row.task_id == request_id:
            return row
        if row.task_state == "GENERATING":
            raise ValueError("已有生成任务，请等待完成")
        row.task_id, row.task_state = request_id, "GENERATING"
        row.task_created_at, row.claimed_at = utc_now(), None
        row.pending_json = encode({"source": source, "counts": counts})
        row.progress, row.error_message = "等待自测Worker领取", None
        self.session.commit()
        return row

    def submit(self, assessment_id: str, answers: dict, *, draft: bool = False):
        row = self.slot()
        if row is None or row.current_id != assessment_id or not row.current_json:
            raise ValueError("本次检测已过期或被新检测替换")
        data = json.loads(row.current_json)
        if data["status"] == "SUBMITTED":
            return data
        result = score_questions(data["questions"], answers)
        data["user_answers"] = answers
        if not draft:
            data.update(status="SUBMITTED", result=result, submitted_at=utc_now().isoformat())
        row.current_json = encode(data)
        self.session.commit()
        return data
