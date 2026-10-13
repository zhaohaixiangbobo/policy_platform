"""文件说明：资料搜索与问答推荐共用的轻量匹配；不调用模型，不维护业务大词典。"""
import re
import unicodedata

# 泛化词只支持独立搜索，不能作为推荐主题；提问词和资料标签两侧共用同一份。
# “其他”“未明确”是兜底领域值，条款中常见“其他部门/其他来源”，作为强主题会批量误推荐。
GENERIC_TERMS = frozenset(
    {"处理", "处分", "党纪", "行规", "法律法规", "监督", "管理", "纪检监督", "违反党纪", "违反行规", "其他", "未明确"})


def normalize(value):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", unicodedata.normalize("NFKC", value).lower())


def topic(value):
    # 仅移除问句/类型表达，避免把不同业务主题强制归并。
    for word in ("请问", "应该", "如何", "怎么", "有哪些", "有没有", "典型案例", "流程图", "办理流程", "流程", "案例"):
        value = value.replace(word, "")
    value = normalize(value)
    for source, target in (("违反中央八项规定精神", "八项规定"), ("中央八项规定精神", "八项规定"), ("举报办理", "信访举报")):
        value = value.replace(source, target)
    value = re.sub(r"^(?:有|关于|违反了|违反|找一下|查一下|请提供|提供|还有)+", "", value)
    return re.sub(r"(?:的吗|吗|的|会处理|怎么处理|相关|有哪些|有没有)+$", "", value)


def material_intent(query):
    """只分流明确找资料请求；解释、处分和结合案例分析仍由制度问答处理。"""
    if re.search(r"结合|解释|分析|如何处理|怎么处理|处分|处罚|依据|规定是什么", query):
        return None
    if "案例" in query:
        return "CASE"
    if "流程图" in query:
        return "IMAGE"
    return None


class SupportMaterialSearchService:
    """单一字段评分入口；搜索允许原文召回，推荐要求明确主题命中。"""
    version = "material_search_v3"
    threshold = 6

    def match(self, query, fields, kind):
        """字段提供主题，原文只提供佐证；同主题不重复累计标题与标签分。"""
        q = topic(query)
        terms = [topic(t) for t in query.split()[:10]] + [q]
        labels = fields.get("tags", []) + fields.get("problem_types", [])
        hits = [t for t in labels if topic(t) not in GENERIC_TERMS and len(topic(t)) >= 2
                and any(len(v) >= 2 and v not in GENERIC_TERMS and (topic(t) in v or v in topic(t)) for v in terms)]
        title = topic(fields.get("title", ""))
        title_hit = any(len(t) >= 2 and t not in GENERIC_TERMS and (t in title or title in t) for t in terms) if len(title) >= 2 and title not in GENERIC_TERMS else False
        if not hits and not title_hit:
            return {"score": 0, "match_reason": "", "match_excerpt": ""}
        source = fields.get("original", "") if kind == "CASE" else fields.get("summary", "")
        # 仅展示原文连续句段；不生成摘要，不拼接不同人员的行为。
        def supported(sentence):
            normalized = topic(sentence)
            for term in terms:
                if len(term) < 2 or term in GENERIC_TERMS:
                    continue
                if term in normalized:
                    return True
                # 允许“收受可能影响……的礼品礼金”这一连续句中的间隔修饰，不把不同句拼接。
                if term.startswith("收受") and len(term) > 4 and "收受" in normalized and term[2:] in normalized:
                    return True
            return False
        sentence = next((s for s in re.split(r"(?<=[。！？\n])", source) if supported(s)), "")
        excerpt = sentence if len(sentence) <= 240 else ""
        domain_hit = any(topic(d) not in GENERIC_TERMS and len(topic(d)) >= 2 and topic(d) in q for d in fields.get("domains", []))
        return {"score": (10 if hits else 8) + (2 if excerpt else 0) + int(domain_hit),
                "match_reason": ("问题性质 / 关键词匹配：" + "、".join(hits[:3])) if hits else "标题主题匹配",
                "match_excerpt": excerpt}

    @staticmethod
    def search_text(fields):
        return "\n".join("；".join(fields.get(k, [])) if isinstance(fields.get(k), list)
                         else str(fields.get(k, "")) for k in
                         ("title", "tags", "domains", "problem_types", "summary", "original"))

    def score(self, query, fields, kind, *, recommend=False):
        if recommend:
            return self.match(query, fields, kind)["score"]
        terms = [normalize(t) for t in query.split()[:10]]
        terms = [t for t in terms if t]
        if not terms:
            return 0
        title = topic(fields.get("title", ""))
        labels = [topic(t) for k in ("tags", "domains", "problem_types")
                  for t in fields.get(k, [])]
        summary = normalize(fields.get("summary", "") if kind ==
                            "IMAGE" else fields.get("original", ""))
        haystack = normalize(self.search_text(fields))
        extra = normalize(" ".join(str(v) for v in fields.values()))
        score = 0
        for term in terms:
            title_hit = len(title) >= 2 and (term in title or title in term)
            label_hit = any(len(t) >= 2 and t not in GENERIC_TERMS
                            and (t in term or (len(term) >= 4 and term in t)) for t in labels)
            score += 8 if title_hit else 0
            score += 6 if label_hit else 0
            score += 2 if term in summary else 0
            if term not in haystack and term not in extra and not title_hit and not label_hit:
                return 0
        return max(score, 1)
