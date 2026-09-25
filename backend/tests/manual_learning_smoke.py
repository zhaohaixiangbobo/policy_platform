"""文件说明：手动执行最多3题的真实模型自测冒烟；只读知识库，不保存答题记录。"""

import argparse

from app.config import get_settings
from knowledge.catalog import KnowledgeCatalogService
from knowledge.config import KnowledgePaths
from knowledge.learning_source import freeze_learning_source
from knowledge.learning_generator import generate_assessment, model_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=int, required=True)
    parser.add_argument("--questions", type=int, choices=[1, 3], default=1)
    args = parser.parse_args()
    catalog = KnowledgeCatalogService(KnowledgePaths(get_settings().knowledge_data_root))
    source = freeze_learning_source(catalog, args.document_id, "FULL", [])
    counts = {"SINGLE": 1, "MULTIPLE": int(args.questions == 3), "TRUE_FALSE": int(args.questions == 3)}
    with model_client() as client:
        questions = generate_assessment(source, counts, client, lambda value: print(value, flush=True))
    # 控制台只输出结构统计，完整题目在正式页面内人工核对。
    print(f"生成通过：{len(questions)}题；题型={[q['question_type'] for q in questions]}；IndexRun={source['index_run_id']}")


if __name__ == "__main__":
    main()
