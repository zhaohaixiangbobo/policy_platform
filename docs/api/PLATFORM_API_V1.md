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

发送消息的请求体包含 `content` 与 `query_scope`。`query_scope` 只允许 `CURRENT` 或 `HISTORICAL`，默认 `CURRENT`。`ChatService` 通过 `RagApiClient` 调用 8010 的 `POST /v1/rag/query`。返回语义保持 `rag_api_v1_1`，支持 `ANSWER`、`INSUFFICIENT_EVIDENCE` 和 `CONFLICT`。Citation 快照保存公开版本字段、`document_id`、`primary_node_id`、各类 run ID 与证据快照；`quality_gate.version` 按实际响应保存。平台不依赖受控 debug 字段。

## 反馈与诊断

- `POST /api/v1/chat/messages/{message_id}/feedback`：结构化反馈及候选评测案例。
- `GET /api/v1/diagnostics/requests`：默认关闭的本机诊断列表。
- `GET /api/v1/diagnostics/requests/{request_id}`：公开响应快照详情。

会话、消息、Citation、反馈和诊断只写入 `platform.db`；知识模块运行数据只写入 `policy_parser.db`。
