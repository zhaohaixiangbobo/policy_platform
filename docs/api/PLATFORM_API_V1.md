# Platform API v1

> 文件说明：记录当前对浏览器公开的接口和迁移后的知识访问边界；机器可读契约见 `openapi.json`。

## 学习成效检测（learning_assessment_v1）

- `GET /api/v1/features`：登录后读取可见功能开关和题量/有效期配置。
- `POST /api/v1/learning-assessments`：创建个人生成任务，202返回task_id；request_id UUID用于去重。
- `GET /api/v1/learning-assessments/current`：本用户任务和未过期检测；提交前仅返回题干、选项及本人暂存答案。
- `PUT /api/v1/learning-assessments/{assessment_id}/answers`：暂存答案。
- `POST /api/v1/learning-assessments/{assessment_id}/submit`：确定性评分，提交后公开答案、解析和原文快照；重复提交保持首次结果。

模块开关关闭时业务接口404；写接口校验CSRF，所有请求校验身份与制度访问权限。
最多15题，单用户最近一次24小时；后端不接受客户端传入标准答案。详细字段、示例与错误码见[功能文档](../LEARNING_ASSESSMENT.md#6-api)。

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
`SearchFilters.document_ids` 和 `SearchFilters.document_statuses`。新回答契约为 `rag_api_v1_2`（兼容v1_1历史），支持 `ANSWER`、
`INSUFFICIENT_EVIDENCE` 和 `CONFLICT`。Platform 会再次校验 Citation 的制度状态和
`document_id` 是否落在本轮已解析范围内，并确认响应与 Citation 的 `index_run_id` 均等于
本轮解析时的 active IndexRun；查询期间发生 Alias 切换时提示按原范围重试。Citation 快照保存公开版本字段、`document_id`、
`primary_node_id`、各类 run ID 与证据快照；`quality_gate.version` 按实际响应保存。平台不依赖
受控 debug 字段。

每条问答消息还保存用户选择模式、选择的具体制度、最终 RAG 范围模式、active IndexRun、
权限策略版本、范围哈希和范围数量，用于历史会话解释与审计。

## 反馈与诊断

### S2回答字段（2026-09-19）

ChatMessageResponse新增answerability（SUFFICIENT/PARTIAL/NONE）、reason_code、missing_fields（字符串数组）、clarification_question。旧回答和用户消息字段为null；新回答无需追问时missing_fields=[]、clarification_question=null。
ANSWER+PARTIAL代表有用的条件或部分答案，不应隐藏正文。MISSING_USER_CONTEXT附带字段及追问，POLICY_LIMIT_ONLY表达制度只规定上限，NO_RELEVANT_EVIDENCE表达当前无依据。
详细合法组合和原因码见 [方案第3节](../RAG_QUALITY_EVOLUTION_PLAN.md#3-答案契约)。answerable为兼容布尔值，继续按status派生，不用于推断SUFFICIENT。
S3已接入确定性多轮补全。引用和权限校验保持强制；语义门禁默认关闭。

### S3多轮快照（2026-09-19）

ChatMessageResponse增加可空rewrite_used、retrieval_query、rewrite_strategy_version和conversation_context。context含root_question、root_message_id和confirmed字典，每项包含value/source_message_id。用户content始终保留原输入；历史不回填。
策略clarification_rewrite_v1只承接最近完整问答，同范围、权限及快照下的明确短回复。范围变化或歧义输入按原问题查询。Platform保存实际rewrite_used；Knowledge直接查询仍为false。RAG契约维持rag_api_v1_2，Prompt和Citation版本不变。

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
- 同一制度在草稿、待审核和审核通过待发布阶段只允许一条未完成变更；
- `POST /api/v1/admin/knowledge/documents/{document_id}/metadata/{revision_id}/withdraw`
  可撤回尚未发布的人工修订，必须填写原因；首次入库修订和已发布修订不能撤回；
- 保存、提交、审核及 IndexRun 冻结均执行状态一致性校验。只有 Alias 切换成功后，新的制度状态
  才成为制度库和问答检索的正式事实。

管理页的三个入口不直接调用草稿接口：页面先进入本地编辑态，只有发生人工修改并点击保存或提交时才创建草稿。
