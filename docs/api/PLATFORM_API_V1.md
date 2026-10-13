# Platform API v1

## 配套资料检索v3（2026-10-11）

recommendations新增可选kind=CASE/IMAGE，仅缩小资料类型范围；返回search_version=material_search_v3，items新增可选match_reason、match_excerpt。纯案例/流程图聊天消息使用既有reason_code=MATERIAL_SEARCH，answer_status=ANSWER，无RAG/Citation执行信息；仍使用既有消息接口。权限与SELECTED约束见[设计及验证](../SUPPORTING_MATERIALS_V3.md)。

## 配套资料v2（2026-10-09，取代旧七列契约）

图片metadata仅 title/tags/summary；案例fields为title/person_category/position/rank/political_status/age/domains/problem_types/outcome/original，按类型拒绝额外字段。POST /api/v1/materials/imports/preview仅上传file，移除defaults；案例模板十列。列表移除来源/地区/日期筛选；items新增preview_text，全文仍仅详情返回。推荐search_version为material_search_v2。完整规则见[当前字段契约](../SUPPORTING_MATERIALS_V2.md)。OpenAPI已重新导出。

> 文件说明：记录当前对浏览器公开的接口和迁移后的知识访问边界；机器可读契约见 `openapi.json`。

## 学习成效检测（learning_assessment_v1）

- `GET /api/v1/features`：登录后读取可见功能开关和题量/有效期配置。
- `POST /api/v1/learning-assessments`：创建个人生成任务，202返回task_id；request_id UUID用于去重。
- `GET /api/v1/learning-assessments/current`：本用户任务和未过期检测；提交前仅返回题干、选项及本人暂存答案。
- `PUT /api/v1/learning-assessments/{assessment_id}/answers`：暂存答案。
- `POST /api/v1/learning-assessments/{assessment_id}/submit`：确定性评分，提交后公开答案、解析和原文快照；重复提交保持首次结果。

模块开关关闭时业务接口404；写接口校验CSRF，所有请求校验身份与制度访问权限。
最多15题，单用户最近一次24小时；后端不接受客户端传入标准答案。详细字段、示例与错误码见[功能文档](../LEARNING_ASSESSMENT.md#6-api)。

## 配套资料库接口（supporting_materials_v2）

- `GET /api/v1/materials`：q/kind/state/domain/sort/page；固定每页10条。普通用户仅PUBLISHED。
- `GET /api/v1/materials/case-template`：下载标准十列空模板。
- `POST /api/v1/materials/imports/preview`：仅multipart file，生成24小时预览；包含逐行中文错误与重复信息。
- `POST /api/v1/materials/imports/{batch_id}/confirm`：仅预览创建人可确认，重复调用返回首次结果。
- `POST /api/v1/materials/images`：multipart图片与metadata JSON（title/tags/summary，三项必填），保存草稿。
- `GET /api/v1/materials/{id}?revision_id=...`：详情；历史版本仅管理员读取。
- `PUT /api/v1/materials/{id}`：expected_version与fields；无改动不新建修订，案情原文不可替换。
- `POST /api/v1/materials/actions`：action=PUBLISH|OFFLINE，items=[{id,expected_version}]，整批事务；发布校验失败提示带资料标题。
- `GET /api/v1/materials/{id}/revisions/{revision_id}/file`：受控图片，不暴露本地路径。

读取需要material.read；写入需要material.manage及CSRF。400字段/发布约束（中文字段名+原因），403权限，404不可访问，409重复/版本冲突/过期，422请求结构校验。类型仅CASE/IMAGE，模板未开放。详细格式见[配套资料v2说明](../SUPPORTING_MATERIALS_V2.md)。

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
# 配套资料推荐补充（2026-09-26）

GET `/api/v1/materials/recommendations?q=...`，要求material.read，q最多2000字符。
返回items（资料列表摘要）、search_version=material_search_v1、reference_only=true。
只返回已发布版本，每类型最多2项。空主题返回空列表，不改变聊天/RAG契约。
详细规则见[配套资料M4](../SUPPORTING_MATERIALS_M4.md)。
# 学习辅助资料接口（2026-09-27）

GET `/api/v1/learning-assessments/{assessment_id}/questions/{question_id}/materials`：学习开关、制度读取与资料读取权限，校验本人未过期已提交检测。404不可访问，409未提交；返回当前已发布辅助资料每类最多1条，不改变题目及评分契约。详见[设计](../LEARNING_MATERIALS.md)。
