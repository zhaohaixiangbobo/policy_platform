"""文件说明：在单一只读事务中冻结已发布制度及完整条款，不使用问答TopK取材。"""

from knowledge.catalog import KnowledgeCatalogService


def freeze_learning_source(catalog: KnowledgeCatalogService, document_id: int,
                           mode: str, selected_ids: list[int]) -> dict:
    with catalog._connection() as connection:
        connection.execute("BEGIN")
        row = connection.execute("""
            SELECT src.index_run_id,src.parse_run_id,m.title,m.document_code,m.status
            FROM index_profile ip JOIN index_run ir ON ir.id=ip.active_index_run_id
            JOIN index_run_source src ON src.index_run_id=ir.id
            JOIN document_metadata_revision m ON m.id=src.metadata_revision_id
            WHERE ip.profile_name=? AND src.document_id=?
              AND ir.status='succeeded' AND ir.activation_status='active'
        """, (catalog.profile_name, document_id)).fetchone()
        if row is None or row["status"] != "effective":
            raise ValueError("只能对已正式发布的现行有效制度出题")
        nodes = [dict(item) for item in connection.execute("""
            SELECT id,parent_id,node_type,node_number,title,COALESCE(raw_text,content,'') AS text,order_no
            FROM policy_node WHERE document_id=? AND parse_run_id=? ORDER BY order_no,id
        """, (document_id, row["parse_run_id"]))]
    by_id = {node["id"]: node for node in nodes}
    children: dict[int, list] = {}
    for node in nodes:
        children.setdefault(node["parent_id"], []).append(node)

    def subtree(node):
        result = [node]
        for child in children.get(node["id"], []):
            result.extend(subtree(child))
        return result

    selectable = {node["id"] for node in nodes if node["node_type"] in {"chapter", "article"}}
    if mode == "SELECTED" and (not selected_ids or not set(selected_ids) <= selectable):
        raise ValueError("所选章节或条款不属于本次发布版本，请刷新后重新选择")
    allowed = {node["id"] for node in nodes} if mode == "FULL" else {
        child["id"] for node_id in selected_ids for child in subtree(by_id[node_id])}
    articles = [node for node in nodes if node["node_type"] == "article"]
    roots = articles or [node for node in nodes if node["node_type"] == "paragraph" and node["text"].strip()]
    units = []
    for node in roots:
        if node["id"] not in allowed:
            continue
        parts = [child["text"].strip() for child in subtree(node) if child["text"].strip()]
        text = "\n".join(parts)
        if len(text) < 15:
            continue
        # 完整条款过大时明确拒绝；不能截断限制条件后冒充完整依据。
        if len(text) > 16000:
            raise ValueError("存在过长条款，请缩小范围或先整理制度结构")
        label = " ".join(str(node.get(key) or "") for key in ("node_number", "title")).strip()
        units.append({"primary_node_id": node["id"], "knowledge_point": label or f"正文条款 {node['id']}",
                      "source_text_snapshot": text})
    if not units:
        raise ValueError("所选范围没有可用于出题的完整条款")
    if sum(len(unit["source_text_snapshot"]) for unit in units) > 2_000_000:
        raise ValueError("所选范围过大，请按章节出题")
    return {"document_id": document_id, "document_title": row["title"],
            "document_code": row["document_code"], "index_run_id": row["index_run_id"],
            "parse_run_id": row["parse_run_id"], "scope": {"mode": mode, "node_ids": selected_ids}, "units": units}
