# 问答质量与混合检索分阶段开发方案

> 文件说明：定义回答展示、Answerability、多轮澄清、混合检索和结构补全的实施与验收契约。
> 方案版本：1.3；日期：2026-09-19；状态：实施中（S1—S3代码完成，S4/S5未开始，S6延后）。
> 当前版本入口：[文档总台账](README.md#7-当前实现版本台账)。本文中的目标版本均为拟定值。

## 1. 目标与边界

让系统展示已有的有效回答，在信息不完整时给出有证据的条件答案和具体追问；通过分层评测决定检索增强是否启用。

- Platform 应用层通过进程内 KnowledgeService 调用知识能力；保持双数据库边界。
- 用户可访问范围、主动选择、CURRENT/HISTORICAL 和固定 IndexRun 共同约束所有检索分支。
- 正常答案生成一次同时输出答案与 Answerability；第一版不增加 Answerability 专用 LLM 调用。
- 严格 JSON 校验失败后的现有有限重试单独计数，不能承诺每个请求严格一次模型调用。
- 语义 Quality Gate 保留配置能力；通用 LLM Rewrite、Multi-Query 默认关闭。
- 不改变既有已发布内容和 Citation 历史，不自动切换 Alias，不修改原 rag 工程。
- 新依赖先列版本、用途和安装命令，由用户手动安装并确认。

## 2. 代码基线与已确认问题

当前调用链：ChatService → QueryScopeResolver → KnowledgeService → RagRuntime → Dense20 → Rerank8 → Context → Generator → Parser/可配置门禁。

1. 原ChatPage对INSUFFICIENT_EVIDENCE使用固定提示，隐藏已持久化的条件答案；S1已改为共用公开正文渲染。
2. S3已接入最近完整问答的结构化澄清补全；Platform记录真实rewrite_used，Knowledge直接查询仍默认false。
3. Context v1 固定最多8条、8000 token估算预算；先截取再去重，缺乏补位候选。
4. Chunker 支持超长条款的 context 父块和 retrieval 子块；Context v1 禁止父块扩展，回读接口只允许 retrieval。
5. 较短条款已包含下属子项。2026-09-19只读核查的 active IndexRun 8 有325个 retrieval Chunk，父子块数量为0；这是时间点记录，不作为运行配置。
6. S2门禁v3对有引用的部分答案执行支持性校验；独立clarification_question不参与事实引用覆盖检查。门禁仍默认关闭。

## 3. 答案契约

保留 status：ANSWER / INSUFFICIENT_EVIDENCE / CONFLICT。
新增 answerability：SUFFICIENT / PARTIAL / NONE，描述本轮问题的可回答程度。

| 组合 | 语义 |
|---|---|
| ANSWER + SUFFICIENT | 已回答本轮问题 |
| ANSWER + PARTIAL | 有实质部分答案或条件分支，仍存在缺口 |
| INSUFFICIENT_EVIDENCE + PARTIAL | 有相关资料，尚不足以形成有用的目标结论 |
| INSUFFICIENT_EVIDENCE + NONE | 当前证据不能支撑实质回答 |
| CONFLICT + SUFFICIENT/PARTIAL | 已确认冲突；覆盖程度不代表解决了冲突 |

程序拒绝其他组合；CONFLICT继续要求真实的冲突结构和不同证据。适用类别不同不等于冲突。

新增字段：reason_code、missing_fields、clarification_question。missing_fields 在不需追问时为空数组；clarification_question 可为空。需要多轮补全时必须给出受支持的结构化字段键。

原因码首批：COMPLETE、MISSING_USER_CONTEXT、EVIDENCE_COVERAGE_GAP、POLICY_LIMIT_ONLY、NO_RELEVANT_EVIDENCE、CONFLICTING_EVIDENCE、ANSWER_VALIDATION_FAILED、SUPPORT_CHECK_FAILED。
原因描述整体缺口，不单独决定status；例如询问奖励上限时，制度只给上限仍可充分回答。

- PARTIAL 必须在正文说明缺口；只有用户可以补充的缺口才追问。
- 无可用证据由程序直接返回 NONE；授权失败、服务异常使用错误契约，不伪装成无依据。
- 引用不存在、越权或快照错配必须拦截；非法原始答案不进入可展示结果。
- 模型仅返回本轮E编号，制度名、页码、版本和证据快照由程序生成。
- 语义校验启用时覆盖部分答案中的事实，追问句与非事实说明不强制绑定引用。
- 金额必须保留“不超过”、税前等限定，不将奖励上限改写成实发金额。

S2已升级知识结果契约为 rag_api_v1_2，严格生成Schema为 policy_rag_answer_schema_v3，Prompt为 policy_rag_prompt_v4；Generator配置v3、Pipeline v2、Quality Gate v3。Citation及Context版本保持原值。
Platform为新增公开字段增加迁移、响应类型和历史兼容分支。旧记录保留空字段，按旧契约显示，不反推Answerability，不调用LLM批量回填。

## 4. 分阶段实施与验收

| 阶段 | 状态 | 内容 | 完成条件 |
|---|---|---|---|
| S1 | 代码完成，类型检查通过 | 回答展示修复 | 共用正文及引用渲染，空白正文兜底；浏览器交互待手工验收 |
| S2 | 代码及迁移完成，最小测试通过 | Answerability、Prompt和程序校验 | 字段贯通；真实模型与浏览器验收待执行 |
| S3 | 代码及迁移完成，最小测试通过 | 结构化多轮澄清及受控补全 | 用户条件来源可追溯；真实模型/浏览器验收待执行 |
| S4 | 未开始 | BM25/RRF、召回评测、候选补位 | 同预算比较完成后决定Hybrid开关 |
| S5 | 未开始 | Context v2.1父块补全 | 同快照父子关系、预算与引用核验通过 |
| S6 | 延后 | 关联条款检索/Multi-Query | 独立评测证明增益后再启用 |

### S1：真实回答展示

修改 frontend/src/pages/ChatPage.tsx。所有状态展示公开正文；提示条表达回答状态，正文为空时使用兜底文案。继续使用现有引用渲染，不显示内部草稿。阶段结束执行前端类型检查及已有相关最小测试。

### S2：一次生成与结构化澄清

修改 knowledge/rag 的 models、prompt、answer_parser、pipeline、quality_gate，以及 knowledge/contracts.py、Platform聊天模型/Schema/服务、前端类型和呈现。
增加版本化迁移，历史记录可读；升级严格Schema和配置哈希。对有用的条件答案使用 ANSWER + PARTIAL，界面提示“已提供条件答案，仍需补充信息”。
Prompt示例涵盖完整回答、条件回答、无依据、上限与实发金额区分、不同条件非冲突。
最小验收：合法/非法组合、引用集合一致、NONE短路不调用模型、旧记录兼容、条件答案事实校验。

### S3：受控多轮补全

在Platform保存待澄清字段、用户确认值和来源消息ID。只使用本用户当前会话的相关信息；本轮明确纠正值覆盖旧值，切换话题或范围时清理不再适用的待澄清状态。
原始问题与完整化检索问题分别保留；历史模型回答不是事实源。对“一类”“个人一等奖”等支持字段执行确定性归一化，复杂指代无法确认时继续澄清。
QueryScopeResolver按本轮请求重新计算范围，补全过程没有修改权限和制度选择的能力。更新rewrite_used为实际值，并记录补全策略版本。
验收：一类与一等奖不混淆、跨用户隔离、用户纠正生效、范围变更不继承越界证据、失败回退原问题。

S3策略clarification_rewrite_v1：仅最近完整一轮、同状态范围/制度选择/权限哈希和版本/IndexRun时承接。支持“一类，个人一等奖”“改为二类”；通用字段需标签，如“部门：财务部”“日期：2026-09-19”“业务情形：培训报名”。否定、歧义、无法完整解析或超过200字的回复作为独立原问题，不猜测。
每轮保存原始content、retrieval_query、策略版本及root_question/root_message_id、confirmed中的value/source_message_id。待澄清字段来自最近回答，确认值只来自用户；新值覆盖已确认同名字段。新话题和范围变化清空有效确认，历史快照保留；失败轮次不提交确认状态。
前端补充卡片提交短回复，成功后可展开查看检索问题；通用LLM Rewrite保持关闭。

### S4：混合召回与候选补位

新增LexicalRetriever接口，第一实现候选为知识侧SQLite FTS5/BM25。先验证指定Python环境的FTS5能力和中文分词方案，再确定依赖。
索引字段包括冻结文档标题、文号、条款路径、Chunk正文；分词、规范化、词典和字段权重纳入版本。中文、短词、数字及文号分别验证，不直接假设默认tokenizer满足需求。

第一轮实验参数：Dense20 + BM2520 → RRF → 融合Top20 → Reranker有序候选池最多20 → Context最多8。候选深度与RRF参数可配置并记录哈希，不作为已验证最佳值。
每条分支在取TopK前按本轮相同范围过滤；结果按IndexRun/Chunk身份去重。保持固定的QueryExecutionContext，集中记录IndexRun、collection及授权范围；索引切换导致不一致时显式失败/重试，不混用快照。

词法索引为可重建派生数据，按冻结IndexRun登记就绪状态、配置和来源校验信息；正式启用Hybrid后发布前验证词法索引就绪。已有active快照可单独构建词法索引，无需重跑Embedding。失败保留原active；清理旧词法数据需保留正在使用的快照。
词法实现位于知识模块，未来Platform迁入MySQL不强制改变检索存储。

修改Reranker输出候选数量及Context遍历：先校验/去重，再按序尝试预算装载，达到8条或候选耗尽结束。单条超预算后继续考察较短候选，不以无关内容凑满数量。普通Hybrid失败采用明确、可审计的错误或配置允许的Dense降级，响应审计记录实际模式。

### S5：Context Builder v2.1

只实现确定性父块补全，新增冻结快照内context Chunk和来源节点只读回读方法。验证document、ParseRun、ChunkRun和IndexRun来源一致；父关系缺失或非法时保留有效命中并记录诊断。
完整父块预算允许时替代子块，同父子块去重；超大父块保留子块。第一版不动态拼接新的证据原文，不做同制度二次搜索。
父块用自己的chunk_id、原文、来源映射和哈希构造Citation，不冒用子块身份。现有citation_v1能完整表达时保持版本；若需要改变公开语义，另行升版并补兼容测试。
拟定builder_version=context_builder_v2_1，扩展预算和选择策略纳入配置哈希。使用测试夹具覆盖父子块，实际语料无父块不代表已验证该功能。

### S6：按需发现关联证据

放在Retriever/查询规划层。针对复合问题或可定位的证据覆盖缺口触发；缺用户类别时走澄清，不触发盲目补检索。
最多增加两条子查询，共用原授权范围、快照、总候选及token预算，统一融合重排。记录触发原因与调用次数；默认关闭，独立比较启用前后收益。通用LLM Rewrite与语义门禁同样单独评测和启用。

## 5. 评测与必要测试

复用backend/tests和现有人工测试集指南。每题允许多个gold证据及可替代证据，字段至少包括question、固定index_run_id、范围、gold_document_id/parse_run_id/node_id、必要证据组、期望状态/缺口；gold_chunk_id按快照映射。重新解析后重新核验标注。

- 召回层：Dense20、BM2520、Hybrid20的Recall@20、Hit@5、MRR；nDCG@10需分级相关性标注。
- 多证据问题：额外记录必要证据全部召回率；重排层和Context层分别检查证据保留。
- 答案层：限定词、条件、引用和追问正确性；所有模型调用、token及阶段耗时分开记录。
- 空gold的无依据样本独立统计，不混入Recall分母。比较使用相同快照、范围、预算和标注。
- 最小案例：行业一等奖、省级一等奖、一类个人一等奖、接续“一类”、是否一定发10000元、税前及拨付复合问题、无依据、冲突、越权、历史范围、索引切换、重复候选、超预算和父子块。

每阶段仅执行相关单元/契约测试，前端改动执行pnpm typecheck。模型真实联调使用小规模批准用例；全量评测、压力和长稳测试准备命令与说明，由用户手动执行。阶段交付登记具体命令、结果、未执行项和原因，不用计划冒充测试记录。

## 6. 文档同步与完成定义

每阶段功能合入时，同步完成下表；没有文档和版本更新的阶段不能标为完成。

| 文档 | 同步内容 |
|---|---|
| docs/README.md | 当前版本、代码锚点、启用状态、核验日期和本方案阶段状态 |
| 根README.md、PROJECT_HANDOFF.md | 当前运行链、能力和启动/依赖变化 |
| api/PLATFORM_API_V1.md、api/openapi.json | 公开字段、枚举、示例、历史兼容；Schema变更后按现有脚本重新生成OpenAPI |
| INGESTION_TO_QA_WALKTHROUGH.md | 范围、词法索引构建发布、查询和Citation数据流 |
| deployment/LOCAL_DEVELOPMENT.md、OPERATIONS.md | 实际开关、索引准备、回退与故障诊断 |
| testing/RAG_MANUAL_TESTSET_GUIDE.md | 标注格式、分层评测和可执行测试命令 |
| 代办.md | 已完成事项移出；延后功能链接本方案，避免两份规则漂移 |

版本管理区分代码配置版本、实际运行响应版本、数据Run ID。重启与发布核验前只能称“代码已实现”；已持久化旧回答继续按自己的provenance解释。
发布新行为同时记录Prompt/Schema/检索/Context/Pipeline配置版本和哈希；语义门禁行为变化时升级门禁版本；字段与Schema不变的纯展示修复不强行升级Citation。
功能开关保留可验证的基线回退，历史数据使用兼容读取；回退不删除历史记录或恢复到不兼容的旧Schema。

## 7. 本文交付状态

2026-09-19 S3：0010_conversation_context已应用到本机并核验head；34项相关后端测试和pnpm typecheck通过，OpenAPI已导出。未调用真实模型、执行浏览器交互、压力或长稳测试。S4/S5未开始，S6延后。以下S1/S2记录为各阶段交付时点记录。

2026-09-19追加：完成引用快照状态展示与按需补充卡片，S3前通过完整问题模板补充；query_timing_v1分段日志已实现，三个真实问题复测完成，详见[验证记录](testing/QUERY_TIMING_VERIFICATION_2026-09-19.md)。本次不升级回答或Citation契约。

2026-09-19：S1代码完成，执行根目录 `pnpm typecheck` 通过。三种状态共用公开正文和引用渲染；INSUFFICIENT_EVIDENCE提示为“尚不能确定最终结论”，正文为空或仅空白时才兜底。旧回答无需重新生成。

S1没有新增测试依赖或接口变化；手工验收步骤见 [测试指南](testing/RAG_MANUAL_TESTSET_GUIDE.md#s1-回答展示最小手工验收)。

2026-09-19 S2：新增answerability、reason_code、missing_fields、clarification_question，旧记录保持NULL；迁移0009已应用到本机Platform库。23项最小后端测试和pnpm typecheck通过，OpenAPI已重新导出。未运行真实模型、浏览器交互、全量、压力或长稳测试。需要后端加载新代码后按测试指南完成真实问答验收；S3—S5未开始，S6延后。

S2补充约束：COMPLETE仅用于ANSWER+SUFFICIENT；CONFLICTING_EVIDENCE与CONFLICT对应；MISSING_USER_CONTEXT必须为PARTIAL且携带受支持字段和非空追问。正文条件式表述结论边界，追问独立存放；语义校验启用时保守拒绝正文末尾未引用的事实陈述，不靠删除句子放行。
