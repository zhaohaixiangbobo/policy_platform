# Platform API v1

> 文件说明：记录当前对浏览器公开的接口和迁移后的知识访问边界；机器可读契约见 `openapi.json`。

## 健康检查

- `GET /api/v1/health/live`：Platform API 进程存活。
- `GET /api/v1/health/ready`：Platform 业务数据库可用。

## 制度目录

- `GET /api/v1/documents`：active 制度列表、搜索和筛选。
- `GET /api/v1/documents/facets`：筛选项。
- `GET /api/v1/documents/{document_id}`：active 制度详情。
- `GET /api/v1/documents/{document_id}/nodes`：active ParseRun 的结构化正文；返回只读
  `node_number`。Reading View 的 `article` 目录项使用该字段显示真实条款号，正文标题保持完整。
- `GET /api/v1/documents/{document_id}/pdf`：当前有效 PDF。

目录数据通过 `KnowledgeCatalogService` 只读访问 `policy_parser.db` 的 active 视图，不再维护 Platform 制度投影。

## 会话问答

- `GET/POST /api/v1/chat/sessions`
- `PATCH/DELETE /api/v1/chat/sessions/{session_id}`
- `GET/POST /api/v1/chat/sessions/{session_id}/messages`
- `GET /api/v1/chat/query-capabilities`：返回当前用户在 active IndexRun 中可查询的
  现行、历史制度数量，前端据此决定是否开放历史制度选项。

发送消息的请求体包含 `content`、`query_scope` 和显式 `document_selection`：

```json
{
  "content": "奖金标准是什么？",
  "query_scope": "CURRENT",
  "document_selection": {"mode": "SELECTED", "document_ids": [2, 8]}
}
```

- `query_scope` 只允许 `CURRENT` 或 `HISTORICAL`，默认 `CURRENT`；
- `document_selection.mode=ALL` 表示全部可访问制度，不携带 `document_ids`；
- `document_selection.mode=SELECTED` 必须携带 1～20 个具体 `document_id`；
- `QueryScopeResolver` 统一计算“用户可访问 ∩ 用户选择 ∩ 状态范围 ∩ active IndexRun”；
- 指定制度不可查询时直接返回业务错误，绝不自动扩大到全库；
- 当前 `DocumentAccessResolver` 为开放实现，未来可替换为 4A 身份映射与 Platform ACL，
  进程内 `RagRuntime` 不感知用户和权限。

`ChatService` 通过进程内 `KnowledgeService` 调用 `RagRuntime`，并把最终解析出的制度范围转换为
`SearchFilters.document_ids` 和 `SearchFilters.document_statuses`。返回语义保持 `rag_api_v1_1`，支持 `ANSWER`、
`INSUFFICIENT_EVIDENCE` 和 `CONFLICT`。Platform 会再次校验 Citation 的制度状态和
`document_id` 是否落在本轮已解析范围内，并确认响应与 Citation 的 `index_run_id` 均等于
本轮解析时的 active IndexRun；查询期间发生 Alias 切换时提示按原范围重试。Citation 快照保存公开版本字段、`document_id`、
`primary_node_id`、各类 run ID 与证据快照；`quality_gate.version` 按实际响应保存。平台不依赖
受控 debug 字段。

每条问答消息还保存用户选择模式、选择的具体制度、最终 RAG 范围模式、active IndexRun、
权限策略版本、范围哈希和范围数量，用于历史会话解释与审计。

## 反馈与诊断

- `POST /api/v1/chat/messages/{message_id}/feedback`：结构化反馈及候选评测案例。
- `GET /api/v1/diagnostics/requests`：默认关闭的本机诊断列表。
- `GET /api/v1/diagnostics/requests/{request_id}`：公开响应快照详情。

会话、消息、Citation、反馈和诊断只写入 `platform.db`；知识模块运行数据只写入 `policy_parser.db`。

## 制度生命周期治理

`POST /api/v1/admin/knowledge/documents/{document_id}/metadata/drafts` 使用明确的
`request_type=CORRECTION|REPEAL|EXPIRY`：

- `CORRECTION` 只修订普通元数据，不允许改变制度效力状态；
- `REPEAL` 自动固定 `status=repealed`，废止日期默认为创建草稿当天（可调整），并要求废止日期、原因和依据；
- `EXPIRY` 自动固定 `status=expired`，并要求失效日期和失效说明；
- 废止和失效都只允许从当前 active 元数据为 `effective` 的正式制度创建；
- 保存、提交、审核及 IndexRun 冻结均执行状态一致性校验。只有 Alias 切换成功后，新的制度状态
  才成为制度库和问答检索的正式事实。

管理页的三个入口不直接调用草稿接口：页面先进入本地编辑态，只有发生人工修改并点击保存或提交时才创建草稿。
