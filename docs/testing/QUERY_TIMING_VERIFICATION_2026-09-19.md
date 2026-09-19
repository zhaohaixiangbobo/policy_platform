# 问答界面与耗时追踪验证记录

> 文件说明：记录引用状态、按需补充卡片、query_timing_v1日志及三个慢问题的实际复测。
> 日期：2026-09-19；性质：时间点测试记录，不承诺持续性能或SLA。

## 1. 本轮变更

- EvidencePanel在来源信息中显示document_status，明确为回答时引用快照状态，不查询或覆盖最新状态。
- 删除三个固定追问。仅最近助手消息满足PARTIAL、MISSING_USER_CONTEXT、有clarification_question、当前未发送时显示“需要补充”卡片。
- 卡片按钮把原问题和“补充信息：”填入输入框，用户补充后发送；不自动发送、不猜类别，S3多轮补全仍未启用。
- query_timing_v1记录queue、runtime_init、dense_total、embedding_total/HTTP、qdrant_alias/search、hydrate_chunks、reranker_total/HTTP/backoff、context_total、generator_total/HTTP/backoff、pipeline_total。
- 同一request_id关联阶段事件、HTTP状态、异常类型、校验失败代码及生成/传输/验证器调用次数；请求完成或异常时写query_timing_summary。后续日志包含阶段开始和受控异常类型链。
- API请求写logs/api.log；只新增诊断日志，不变更结果Schema或数据库。父阶段包含子阶段，汇总不能重复相加。历史请求没有分段记录，无法回补。

## 2. 自动验证

22项相关测试通过：test_query_telemetry.py、test_knowledge_service.py、test_answerability.py、test_dependency_logging.py。pnpm typecheck通过。浏览器视觉和点击交互尚未实测；未运行全量、压力或长稳测试。

## 3. 真实复测方法

在backend目录使用固定解释器执行：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' tests/manual_query_timing.py
```

复用与Web一致的KnowledgeService/RagRuntime及配置读取路径，CURRENT+ALL顺序执行三题，同一Runtime第一题冷初始化。直接知识服务复测不经过浏览器、登录、ChatService持久化或用户权限解析，因此结果是知识查询链路耗时，不是浏览器端到端耗时。未新建聊天、修改制度或发布索引。

本次产物：[timing.log](../../outputs/query-timing-20260919-151955/timing.log)、[results.json](../../outputs/query-timing-20260919-151955/results.json)。日志不含原始问题、Prompt或草稿，测试结果文件仅保存本次批准问题及公开响应。

## 4. 实际结果（单位：秒）

| 问题 | 旧RAG总耗时 | 本次RAG总耗时 | Embedding总计 | Reranker总计 | Generator总计 |
|---|---:|---:|---:|---:|---:|
| 行业级一等奖和省级一等奖的奖励标准一样吗？ | 55.458 | 5.804 | 0.210 | 0.181 | 5.328 |
| 获得个人一等奖以后，奖金是税前还是税后？ | 48.835 | 4.273 | 0.216 | 0.179 | 3.813 |
| 省级一类个人一等奖奖励50000元，对吗？ | 134.216 | 49.250 | 0.205 | 42.349 | 6.646 |

第一题服务层总耗时6.041秒，其中runtime_init约0.235秒；另外两题服务层约4.274秒、49.251秒。三题queue均不超过1.3毫秒，Context为2.7—3.4毫秒。Generator各调用一次，无JSON校验重生成、无Generator网络重试、无语义验证器调用。

第三题关联ID：timing-1254d40ee4124724bb1884d172acef1d。Reranker明细：

1. 第一次HTTP：20.035秒，ConnectionError。
2. 退避1.001秒，重建会话后重试。
3. 第二次HTTP：19.125秒，ConnectionError。
4. 退避2.001秒。
5. 第三次HTTP：0.186秒，HTTP 200。

本次第三题主要耗时是重排服务调用发生连接异常后重试，占总耗时约86%。不能进一步断言是TCP建连、远端主动断开或服务内部负载；需结合模型服务端日志和网络状态。客户端配置的Reranker超时为120秒，不能把约20秒ConnectionError直接称作配置超时。

前两题未复现慢现象；历史三题只有总耗时，不能据本次结果追认其全部历史根因。本轮不改重试/超时参数，也不跳过Reranker。第一题的类别解释质量需另按答案评测处理，本记录只评估耗时。

## 5. 后续使用

后端重启/热加载本次代码后，按request_id检索query_timing_summary，再定位慢阶段对应HTTP事件。仍无法区分网络与服务内排队时，带时间、服务名和异常类型向服务端定位；不把候选增强或新增LLM调用当作延迟修复。

## 6. 连接对比诊断（同日15:27—15:29）

使用tests/manual_reranker_connections.py做有限顺序探测，不改变生产配置。探测关闭自动重试，连接/读取超时分别为5/15秒；这与生产120秒超时、失败后重建连接的策略不同，结果不能当作正式吞吐测试。

- 两条短候选：复用连接与新连接交替各3次，6次全部HTTP 200，71—184毫秒。
- 增加 `--real-candidates`：召回第三题实际20条CURRENT候选，原payload分别使用复用连接/新连接各2次，4次全部HTTP 200，97—190毫秒；不调用答案Generator。
- 产物：[短候选](../../outputs/reranker-connections-20260919-152750/results.json)、[实际候选](../../outputs/reranker-connections-20260919-152855/results.json)。

结论：本次未发现顺序连续请求或20条候选负载必然引起失败；复用和新连接都可正常工作。旧异常第二次发生前客户端已重建Session，因此失效旧连接不能单独解释两次失败。仍只能确认当时8004调用发生间歇性连接异常，具体网络、服务监听/重启或连接被中间设备关闭需服务端15:20:06—15:20:48日志与底层错误码。不能依据本次无错误探测宣称故障已消失或唯一根因已确定。

## 7. 输入对照复测（同日16:07）

执行 `& 'D:\3-anaconda\envs\py312\python.exe' tests/manual_reranker_connections.py --input-comparison`。
固定原题本次实际召回的20条候选（2871字符），同一Session、无自动重试、5秒连接/15秒读取超时，按原题→修改金额→正常问题顺序重复两轮，每次间隔1秒。只调用召回与重排，不调用Generator、不写聊天或切换索引。

| 输入 | 第一次耗时 | 第二次耗时 |
|---|---:|---:|
| 省级一类个人一等奖奖励50000元，对吗？ | 216ms | 113ms |
| 省级一类个人一等奖奖励10000元，对吗？ | 188ms | 98ms |
| 获得个人一等奖以后，奖金是税前还是税后？ | 115ms | 104ms |

6次均HTTP 200，并通过现有客户端的返回数量、索引、分数和模型标识校验，均返回8条结果。产物：[results.json](../../outputs/reranker-connections-20260919-160748/results.json)。

本轮未复现输入特定故障，原题和相同候选可以正常处理，无法支持“50000元或该题输入必然导致连接异常”的判断。候选为本次重新召回，并非历史失败HTTP原始字节归档；有限成功样本也不能排除偶发的输入与服务状态交互。未运行压力、全量测试或端到端答案质量测试，生产重试配置保持不变。
