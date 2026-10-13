# 学习成效检测功能说明

> 文件说明：即时个人自测工具的现行功能、接口、配置和数据生命周期。
> 版本：learning_assessment_v2；日期：2026-09-24；不属于考试或长期学习档案系统。

## 1. 功能定位和入口

两个入口复用 `/learning` 页面：主导航“学习检测”，以及现行有效制度详情卡片右上角“学习检测”。
功能默认关闭；登录并拥有 `knowledge.document.read` 权限后，开启功能才显示入口。
目前只有个人自测，不建设部门考试、排名、证书、公共题库、长期成绩或知识能力画像。

第一版选择一份用户有权访问、已正式发布且现行有效的制度。制度列表支持名称/文号搜索和每页10条。
选择全文或章节/条款，设置单选、多选、判断数量；默认5/3/2，共10题，总数最多15题。
调整总题数会按约50%/30%/余数自动分配，仍可逐类调整；后端再次校验合计。
全文仅表示从全文范围抽样，不保证每条都考到。每条最多两题，范围不足时要求减少题量或扩大范围。

## 2. 使用步骤

1. 选择制度和范围。指定范围使用真实章节/条款树，所选节点必须属于本次正式正文版本。
2. 点击生成。已有检测时提示新检测生成成功后将覆盖原结果，失败保留旧结果。
3. 页面显示等待领取、生成、审校及通过题数；可以离开后返回查看。
4. 在本页等待生成完成时自动切换到“答题与结果”，单题展示并使用题号导航或上一题/下一题切换。需要离开时点击“暂存作答”；第一版不自动逐次保存选项。
5. 提交前提示未答题数；确认提交后答案与结果冻结，不能再次改答案刷分。
6. 查看得分、错题/未答、正确答案、解析、条款原文快照及本次重点复习条款。

评分每题等权，满分100，汇总后保留一位小数。单选/判断必须选中正确选项；多选必须集合完全相同，少选、多选、错选均不得分。
未答与答错分别统计。弱项按主要条款Node ID聚合，不让模型打分或推断长期能力。
题目用于学习辅助，AI生成与审校仍可能出错，应以制度原文为准。

### 前端布局与交互（learning_assessment_ui_v2）

右上角提供“检测配置 / 答题与结果”切换，切换分区和题目保留本页未暂存选项，刷新或离开前仍需主动暂存。
配置区采用左侧制度列表、右侧检测配置：保留搜索、每页10条、全文/章节条款、题量设置、覆盖确认和最近一次检测入口。
答题区采用左侧制度快照与单题、右侧进度/题号导航/复习建议。生成完成仅自动切换一次；后续轮询不抢走用户选择的分区。
生成失败继续显示后端原始错误提示并保留旧检测。首次进入已有结果时可点击“查看最近一次检测”，不自动覆盖配置区。
未提交仅显示已答/未答；提交后才显示得分、对错、答案解析、薄弱条款与“查看制度依据”。
依据可展开查看冻结原文并按既有版本规则跳转。错题筛选保留原题号；全对时提示没有错题，可返回全部题目。
参考图中的收藏、最近学习、个人关联筛选、计时和提交前对错未实现，不虚构数据或新增接口。
本次只修改前端及说明文档；生成/审校v2、Worker错误分类、权限、评分与API契约保持不变。
测试与人工验收清单见[前端改版记录](testing/LEARNING_UI_VERIFICATION_2026-09-24.md)。

第二轮视觉精修（learning_assessment_ui_v2.1）：保持现有状态与接口，仅调整CSS、JSX及组件展示属性。
桌面共用等高工作区，制度列表、题目原文和复习列表在各自卡片内部滚动；窄屏恢复自然单栏。
成功提示收为轻量短提示；章节Tag最多显示2个，其余以+N汇总；选项提交后按已返回答案呈现浅绿/浅红。
“查看最近一次检测”区域改为进度面板，保留继续答题/查看结果入口：生成中显示不定进度动画与已有阶段文本，
生成后显示真实作答题数，不将作答百分比冒充生成百分比。

2026-09-25视觉追加：页面最大宽度1720px，READY提示并入检测配置标题行，效力状态色复用制度库。
答题双栏使用内容驱动等高布局，复习区设置独立最小高度，长列表内部滚动，避免仅显示一条建议。

## 3. 取材、生成与审校

- `knowledge/learning_source.py` 在一个只读事务内读取active IndexRun来源、对应ParseRun和元数据，冻结标题、文号和正文。
- 按完整条款及子项构造证据单元，按正文位置均匀抽样；无article时使用正文段落。抽样按题型过滤过短条款（单选≥25字、多选≥60字、判断≥15字，`MIN_UNIT_CHARS`），没有合格条款时才退回任意条款；每条最多两题。
- 不使用RAG TopK，不读取最新未发布草稿，不扩大到其他制度，也不调用额外的知识点规划模型。
- 一题一批（BATCH_SIZE=1），生成阶段3路并发（`GENERATION_CONCURRENCY=3`）、审校阶段串行，同一模型服务分别执行生成Prompt和审校Prompt。普通问答Prompt及运行契约保持不变。
- 模型仅返回slot、题干、选项、答案和解析，证据Node及原文由服务器按slot绑定，不能由模型自行制造。
- 程序校验题型、选项和答案索引、重复选项、重复题干、位置指代；模型审校答案支持性、条件完整性与歧义。
- 选择题四个选项；多选至少两个正确。判断题固定“正确/错误”。选择题通过后随机排列，答案索引同步映射；解析要求引用选项内容而非位置字母。
- 首轮之后最多再补3轮（`MAX_ROUNDS=4`）；补题轮对每个缺口并行出2个候选（`RETRY_FANOUT=2`），各用不同的、本slot未试过的合格条款，先通过者入选，多余候选不再审校；条款全部试过则重置后再按合格优先选取。数量仍不足则失败，不以少于用户指定数量的试卷冒充成功。
- 每个被拒候选记一条 `event=learning_candidate_rejected slot= stage=generate|dedupe|review reason=` 日志，reason 只用固定分类文字，不含题目内容。
- 单条原文最多16000字符，选定范围最多200万字符，超限明确报错，不截断后冒充完整依据。
- 自测模型单次传输超时180秒、传输自动重试0、输出预算2048、temperature=0.7/top_p=0.8；这是可见的实现预算，不是业务SLA。

## 4. 缓存与证据

Platform新增 `learning_assessment_slot`：一个用户最多一个槽位，存最近一次结果和至多一个临时候选。
知识库仅只读；不写Qdrant，不建立新索引，不写原rag工程。

检测级保存：assessment_id、document_id、标题/文号快照、index_run_id、parse_run_id、范围、题量、题目、作答、结果、创建/就绪/过期时间。
题目级保存：question_id、question_type、question、options、correct_answer、explanation、primary_node_id、source_text_snapshot、knowledge_point。
版本只在检测级保存；不逐题增加ChunkRun/Chunk ID或长期Prompt审计表。

有效期从生成成功开始计算，默认24小时。新检测成功后原子替换旧结果；失败清除候选正文并保留旧结果。
超过有效期API立即隐藏内容，Worker每轮分批物理清理过期内容；Worker停止或功能关闭期间不能承诺准点物理清除，恢复运行后继续清理。
不提供历史列表。删除/覆盖后不能恢复历史成绩；数据库备份和SQLite物理空闲页不等于安全擦除，本功能不承诺法证级删除。

答题态接口使用白名单，仅下发题干和选项，不下发标准答案、解析、原文或知识点标签。
交卷后才公开完整依据；所有请求校验当前身份、制度权限，写操作校验CSRF。提交具有幂等性，旧检测ID提交返回409。
ORM乐观锁防止多标签页或Worker覆盖并发状态，冲突提示刷新。

制度改版后仍按本次冻结原文评分：解析先展示原文快照；正文版本仍一致才定位当前条款，否则提示版本变化并打开当前制度。
不建设历史版本阅读器；缓存被覆盖/到期后不再承诺检测记录追溯。

## 5. Worker和开关

独立入口 `backend/learning_worker.py`，不占用入库Worker，不使用Redis、Celery或消息队列。
任务状态为GENERATING、READY、FAILED；检测内容状态为READY/SUBMITTED，到期为EXPIRED/空结果。
领取使用条件更新，一用户只允许一个生成任务；任务超过预算标记失败，旧Worker通过task_id和状态条件无法覆盖新结果。
退出信号等待当前任务结束后停止，实际停止宽限期在未来Compose验收时确定。

```dotenv
PLATFORM_LEARNING_ASSESSMENT_ENABLED=true
PLATFORM_LEARNING_ASSESSMENT_MAX_QUESTIONS=15
PLATFORM_LEARNING_ASSESSMENT_TTL_HOURS=24
PLATFORM_LEARNING_ASSESSMENT_TASK_TIMEOUT_SECONDS=1800
# PLATFORM_LEARNING_LOG_FILE=/data/logs/learning.log
```

当前最大题量配置范围1—15，有效期1—24小时。开关为启动配置，修改后需重启API和学习Worker并刷新页面。
关闭时导航/按钮不展示，直接路由显示不可用，业务API返回404，学习Worker退出且不初始化模型客户端。
普通制度库、问答和入库流程保持独立。日志只记录任务ID、阶段和异常类型，不记录完整试题/答案/原文。

Windows启用步骤：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m alembic upgrade head
# 在工程根.env配置开关后，重启API；另开终端启动学习Worker
& 'D:\2-code\policy-platform\scripts\dev-learning-worker.ps1'
```

如果同时运行入库流水线和学习检测，可使用统一入口：

```powershell
& 'D:\2-code\policy-platform\scripts\dev-workers.ps1'
```

它启动两个独立进程并分别写入 `logs/worker.log`、`logs/learning.log`；不是把两个业务循环合并到同一Python进程。

可移植入口：`scripts/run-service.py learning-worker`，未来与API复用镜像，在同一Compose独立运行。
缓存使用SQLAlchemy及独立迁移；大JSON列为SQLite TEXT/MySQL LONGTEXT适配，但尚未验证或切换MySQL。
当前环境已有全部所需依赖，本次没有安装新包。

## 6. API

| 方法和路径                                    | 用途                                                     |
| --------------------------------------------- | -------------------------------------------------------- |
| GET /api/v1/features                          | 已登录用户获取开关、题数上限、有效期                     |
| POST /api/v1/learning-assessments             | 创建任务，返回202及task_id；request_id为客户端UUID幂等键 |
| GET /api/v1/learning-assessments/current      | 读取本用户任务状态及最近一次未过期检测                   |
| PUT /api/v1/learning-assessments/{id}/answers | 暂存本次作答，不返回标准答案                             |
| POST /api/v1/learning-assessments/{id}/submit | 后端评分并返回解析，重复提交保持原结果                   |

创建请求：

```json
{"request_id":"客户端生成的UUID","document_id":1,"scope":"FULL","node_ids":[],"single":5,"multiple":3,"true_false":2}
```

`SELECTED`必须传章节/条款ID；`FULL`必须传空node_ids。答案格式为 `{"answers":{"题目UUID":[0,2]}}`，选项索引从0开始。
422为请求结构/题量错误，403为权限/CSRF错误，409为版本/任务冲突或范围不足，404为模块关闭。

## 7. 实现与验收记录

实现文件：`knowledge/learning_source.py`、`knowledge/learning_generator.py`、`app/application/learning_service.py`、`app/api/v1/learning.py`、`learning_worker.py`、前端 `LearningAssessmentPage.tsx`。
迁移版本 `0011_learning_assessment`，本机从0010升级成功。
最小测试及已执行/未执行项目见[自测验证记录](testing/LEARNING_ASSESSMENT_VERIFICATION_2026-09-24.md)。

此前空库迁移引用当前ORM导致0006重复列的问题已修复：历史结构冻结，隔离SQLite空库到0011已验证。
联合入口按模块开关启动学习Worker，退出时等待当前生成任务完成，失败保留最近一次检测的业务规则不变。
详情见[Worker与迁移修复记录](testing/WORKER_AND_MIGRATION_FIX_2026-09-24.md)；MySQL与真实模型验收另行安排。

## 2026-09-24：修复"生成检测题目一直失败"（方案C最终版）

### 修改原因

线上生成学习自测题目持续失败，Worker 日志形如：

```
2026-09-24T17:27:57+0800 WARNING policy_platform.learning event=learning_failed task_id=da60c28b-... error_type=GeneratorTransportError
```

用真实模型（Qwen/Qwen3.8-27B，vLLM，http://10.9.7.1:8000/v1）逐层复现后确认，`GeneratorTransportError` 只是表象（90 秒读超时），真正根因有两个，且都由"重提示词 + 严格 JSON Schema 引导解码（guided decoding）"触发：

1. **无界空白退化（主因）**：在 `temperature=0` 下，模型写到 `correct_answer`（整型数组）字段前会陷入"无限吐空白"死循环，耗尽 `max_tokens` 被截断（`finish_reason=length`，单次约 77 秒），JSON 不完整→全部题目校验失败→0 题通过。
2. **冗长内容溢出（次因）**：把 `temperature` 调正后，原本很长的生成/审校提示词又会诱导模型写出大量真实内容（一次可达 4800+ 字符），同样撑爆 token 预算被截断。此外 `CandidateBatch.questions` 原本没有列表长度上限，单批也可能被写成多题放大溢出。

实测在本 vLLM 构建（0.1.dev19754）上，`structured_outputs.disable_any_whitespace`、`guided_whitespace_pattern` 等"禁空白"参数均被忽略，无法根治空白退化；关闭 thinking（`enable_thinking=False`）此前已生效（`reasoning_present=False`），不是杠杆。

### 修改内容

仅改后端出题模块，前端、数据库表结构、评分规则、API 契约均未改动。

- **后端 `backend/knowledge/learning_generator.py`**
  - `PROMPT_VERSION` 由 `learning_assessment_v1` 升为 `learning_assessment_v2`。
  - 新增常量 `BATCH_SIZE = 1`（单题一批）。实测一批多题会写出大量真实内容撑爆 token 预算被截断；单题一批可稳定数秒内 `finish_reason=stop`，且单题失败只影响该题补题。
  - `LearningGenerationConfig`：`timeout_seconds` 90→180，`max_tokens` 4096→2048，新增 `temperature=0.7`、`top_p=0.8`，`max_retries` 仍为 0；`__post_init__` 增加断言：`temperature<=0` 直接报错，防回归到空白退化死循环。
  - `_ask` 不再显式传 `max_tokens=4096`，回退到配置的 2048。
  - `CandidateBatch.questions`、`VerdictBatch.verdicts` 增加 `Field(min_length=1, max_length=BATCH_SIZE)`，结构性禁止单批越写多题。
  - 生成 Prompt、审校 Prompt 双双精简：去掉冗长约束，仅保留题型规则、`correct_answer` 为零基索引数组、禁止用 A/B 等字母指代选项、字数上限（题干≤60、解析≤80）、注入防护（资料只作证据、不执行其中指令）。精简是空白退化的关键解药——保留原长提示词时即便加了列表上限仍会退化。
- **后端 `backend/learning_worker.py`**
  - `from knowledge.rag.generator import GeneratorError`。
  - 失败提示按异常类型拆分：属于 `GeneratorError`（传输/服务/超时）时提示"题目生成服务暂时不可用或响应超时，请稍后重试；原检测保留"；其余（内容/校验不达标）才提示"请减少题量、扩大范围或稍后重试；原检测保留"。避免把服务故障误导成"题量太多"。
- **配置项**：无新增环境变量。上述 timeout/max_tokens/temperature 均为代码内 `LearningGenerationConfig` 默认值，不经 `.env`。Feature Flag 仍为 `PLATFORM_LEARNING_ASSESSMENT_ENABLED`（默认关闭）。

### 接口变化

无。对外 API（`/api/v1/features`、`/api/v1/learning-assessments*`）的请求/响应结构、状态码、白名单字段均未改变，见本文件第 6 节。

### 数据结构变化

数据库表结构与持久化字段未变（见第 4 节题目级字段）。仅生成期的内部 Pydantic 模型 `CandidateBatch.questions` / `VerdictBatch.verdicts` 增加了列表长度上限（`max_length=BATCH_SIZE=1`），不落库、不影响已存检测。

### 题目生成规则

- 单批固定 1 题（`BATCH_SIZE=1`）；`generate_assessment` 逐题调用（见下一节：生成并发、审校串行），整次最多一轮补题，数量不足则失败，不以少题冒充成功。
- 每题两阶段：先生成 `CandidateBatch`，程序校验（题型、选项与答案索引、重复选项/题干、禁止字母/序号位置指代）后再送 `VerdictBatch` 审校，`passed=true` 且无重复结论才采纳。
- 选择题四选项、随机打乱并同步映射 `correct_answer`；判断题固定 `[正确, 错误]`；`correct_answer` 一律零基索引数组。
- 采样参数：`temperature=0.7`、`top_p=0.8`、`max_tokens=2048`、`timeout=180s`、不重试、`enable_thinking=False`。

### 评分规则（未改，摘录备查）

每题等权，满分 100，保留一位小数；单选/判断需选中唯一正确项，多选需集合完全一致（少选/多选/错选均 0 分）；未答与答错分别统计；弱项按主要条款 Node ID 聚合。

### Worker 启动方式与 Feature Flag（未改，摘录备查）

- 独立入口 `backend/learning_worker.py`；可移植入口 `scripts/run-service.py learning-worker`；联合入口 `scripts/dev-workers.ps1`（学习日志写 `logs/learning.log`）。
- Feature Flag `PLATFORM_LEARNING_ASSESSMENT_ENABLED`（默认关闭）；开关与上述采样预算均为启动配置，**修改代码或开关后必须重启 API 和学习 Worker**（Python 进程不热加载）。

### 已知限制

- `disable_any_whitespace` 等 vLLM 禁空白参数在当前部署无效，本修复依赖"精简提示词 + 正 temperature + 列表上限 + 单题一批"组合规避退化，而非从解码层根治；若更换模型/ vLLM 版本需重新验证。
- 精简提示词去掉了"保留适用对象/条件/期限"等细粒度出题指导，题面更简短；质量约束主要由审校阶段与程序校验兜底。
- **部署隐患**：排查时发现本机同时运行了 3 个 `learning_worker.py` 及多个 `run-service.py`（workers/worker/learning-worker）重复进程。旧进程仍跑改动前的代码（batch=3、temp=0、timeout=90），会继续产生本次的失败日志。**修复生效前必须先结束全部旧 learning worker 进程，只保留一个重新启动的实例。**

### 验证方式与结果

均使用默认解释器 `D:\3-anaconda\envs\py312\python.exe`，模型服务在线。

- 端到端（真实 `generate_assessment` 全链路，2 单选 + 1 判断）：**16.2 秒生成 3/3 题成功**（修复前 200 秒超时、0/3）。
- 单调用探针（完整证据、三题型各 2 次，`temperature=0.7`、`batch=1`、列表上限=1、精简提示词）：6/6 全部 `finish=stop`、`PARSE_OK`，单次 3.7–7.6 秒。
- 对照复现：完整原长提示词即便配合列表上限，SINGLE/TRUE_FALSE 仍 ~77 秒 `finish=length`、解析失败——确认"精简提示词"是关键。
- 单元测试：`test_learning_assessment.py` 16 项全部通过。

复跑命令（PowerShell）：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_learning_assessment.py -q
```

## 2026-09-24（二）：提速与"8/10 差两题"补题失败修复

### 修改原因

v2 上线后真实任务不再卡死，但出现两类新问题（`logs/learning.log` task `15bcaf45`）：

1. **慢**：10 题 = 20 次串行 HTTP 往返（生成 4–7 秒 + 审校 1–2 秒/题），约 60–75 秒。经核算每次请求输入只有 250–900 token（system 提示词 ≈150 tok + 单条条款原文 15–685 字 + 已通过题干列表），输入体量不是瓶颈，瓶颈是 27B 模型固有的逐题生成延迟。
2. **8/10 后失败**：位置均匀抽样不看条款长度，会把"本办法自发布之日起施行"这类 15–25 字的条款分给多选题（要求 4 选项、≥2 正确、干扰项可被原文排除），必然审校不过；补题轮又用同一条款原地重试，注定再失败。

### 修改内容（`backend/knowledge/learning_generator.py`）

- 新增 `MIN_UNIT_CHARS = {"SINGLE": 25, "MULTIPLE": 60, "TRUE_FALSE": 15}` 与 `MAX_QUESTIONS_PER_UNIT = 2`；`_pick_unit()` 在目标位置附近优先选达到该题型最短字数的条款，没有合格条款时退回任意条款，每条不超过两题。
- 补题轮对未通过的 slot 调用 `_pick_unit(..., exclude={原条款})` 换用附近未用过的合格条款，无可换时才沿用原条款。
- 新增 `GENERATION_CONCURRENCY = 3`：生成阶段用 `ThreadPoolExecutor` 并发出题（`_generate_one()` 单题生成 + 结构校验，JSON/业务失败返回 None，传输类错误原样抛出）；审校阶段保持串行，保证去重判断基于最新已通过题目。
- `progress()` 只在主线程调用且不再被单题校验的 `except ValueError` 吞掉，任务过期/被替换能正确中止。
- 生成/审校提示词抽成模块常量 `CANDIDATE_PROMPT` / `REVIEW_PROMPT`，内容未变。

### 接口 / 数据结构变化

无。API 请求响应、`learning_assessment_slot` 表结构、题目字段均未变。

### 验证方式与结果

- 单元测试：`test_learning_assessment.py` **17 项全部通过**（新增 `test_sampling_skips_short_units_and_retry_switches_unit`：过短条款不参与多选、补题轮换条款；`FakeModel` 补充多选返回两个正确索引）。
- 真实模型端到端（文档 12《监督执纪工作指引》，5 单选 + 3 多选 + 2 判断）：**39.2 秒生成 10/10 题**（改前约 70 秒且止于 8/10）。生成阶段 19 秒并发完成，审校每题约 1.4 秒，1 题补题换条款后通过。
- 文档 4、9 复测期间模型服务 `10.9.7.1:8000` 出现反复 `ConnectionReset` / `RemoteDisconnected`，`/v1/models` 探活交替 UP/DOWN（连接超时），串行模式同样复现，属服务端不稳定，与本次改动无关；worker 会将其记为 `GeneratorTransportError` 并提示"服务暂时不可用"。待服务稳定后建议再跑一次 `tests/manual_learning_smoke.py --document-id 4 --questions 3` 确认。

### 已知限制

- 并发路数为常量 3，未做成配置项；若模型服务并发能力弱可下调为 1（行为退化为串行，逻辑不变）。
- 最短字数阈值是经验值（基于本地 10 份制度的条款长度分布：中位数 40–130 字），后续可按真实通过率调整。
- 传输层仍是 `max_retries=0`，模型服务瞬断直接判该次任务失败，不做静默重试；用户点"重新生成"即可。

## 2026-09-25：补题预算扩大、多路候选与失败原因可见

### 修改原因

`logs/learning.log` task `4526013a`：首轮 10 题通过 9 题（约 35 秒），补题轮为最后 1 题只出了 1 个候选，且在 6 秒后未进入审校就整体失败（候选没过程序结构校验）。同日 `bbd2e804`、`1370d3d6` 两次任务同样都是首轮差 1–2 题，只是补题一次恰好通过。说明：

1. 单题一次通过率约 85%，"整次只补一轮、每个缺口只出一个候选"的预算太小——10 题有约 15% 的概率因最后一题失败而整体白干，前 9 题的成本全部浪费。
2. 日志只有"生成中/审校中/失败 ValueError"，看不出候选是死在生成、结构校验还是审校，无法定位。

### 修改内容

`backend/knowledge/learning_generator.py`

- 新增 `MAX_ROUNDS = 4`（首轮 + 最多 3 轮补题）与 `RETRY_FANOUT = 2`：补题轮对每个缺口并行出 2 个候选，各用不同的、本 slot 未试过的合格条款（`tried[slot]` 记录），先通过者入选，其余候选直接丢弃、不再花审校调用；条款全部试过则清空记录后重新按合格优先选取。条款占用 `usage` 每轮按已通过题目重算，失败候选不再长期占着条款名额。
- `_generate_one()` 改为返回 `(候选, 失败原因)`，`pydantic.ValidationError` 单独归为"输出不符合 JSON 结构"，其余原因取自 `validate_candidate` 的固定文案；新增 `_reject()` 输出 `event=learning_candidate_rejected slot= stage=generate|dedupe|review reason=`，不记录题目内容。
- 新增 `LearningContentError(ValueError)`：条款不足、题数不足两类内容性失败改抛该异常，消息形如"仅有 9/10 道题通过校验，未形成检测；请减少题量或扩大范围"。

`backend/learning_worker.py`

- 失败提示分三类：`GeneratorError` → "服务暂时不可用"；`LearningContentError` → 直接展示其消息 + "原检测保留"（用户能看到差几题）；其他异常仍用原通用文案。

前端 `LearningAssessmentPage.tsx` / `learning-assessment.css`（同日 UI 调整，一并记录）

- 生成中不再在页面顶部显示"由独立学习 Worker 处理…"提示，进度只在右侧"题目生成进度"区展示；失败提示保留。
- "查看制度原文"链接改为新标签页打开（登录态走同源 Cookie，不受影响）。
- 制度列表每页条数按列表容器可用高度自适应（`fitPageSize()`，3–30 条；首次按估算高度、条目渲染后按实测高度校正一次、之后仅随窗口 resize 重算），不再固定 10 条。
- 制度条目改为带浅边框的独立卡片，条目分界更明显；制度依据改为独立面板（左侧蓝色竖线）。
- 答题页去掉 820px 最小行高；右侧"本次建议复习"卡片以 `min-height` 占位、列表主体绝对定位并内部滚动，使网格行高只由左侧题目内容决定：未展开制度依据时不再出现大段空白，展开后两列一起变长且底部对齐。

### 接口 / 数据结构变化

无。`error_message` 字段仍为字符串，只是内容更具体。

### 验证方式与结果

- 单元测试：`test_learning_assessment.py` **17 项全部通过**。调整：`test_generation_review_frozen_evidence_and_finite_retry` 全拒模式调用数 4 → 8（1 + 3 轮，各 1 生成 + 1 审校，仍有限）；`test_sampling_skips_short_units_and_retry_switches_unit` 断言补题轮两个候选分别用了不同的未试条款；`test_worker_success_failure_and_old_result` 断言失败提示含 "0/1" 与 "原检测保留"。
- 前端 `tsc --noEmit` 通过；本项目前端无测试框架。
- 真实模型端到端未在本次执行（Worker 由使用者自行启动，改动后需重启 Worker 才会加载）。

### 已知限制

- 最坏情况（每轮都失败）总调用数上限约 `N + 3 × 2 × 缺口数` 次生成，10 题全失败的极端场景约 70 次调用，仍远小于 1800 秒任务超时；正常场景补题只发生在个别缺口。
- `RETRY_FANOUT=2` 只作用于补题轮；首轮仍是每题 1 个候选，避免正常情况下翻倍调用。
# 2026-09-27：提交后辅助资料

## 2026-09-27：模型调用有限重试和错误分类

学习生成和审校的单次调用对连接异常、响应超时、HTTP 429、500/502/503/504 最多尝试三次，间隔 1、2 秒；保留当前任务内已通过的题目。其他异常保持原校验路径。传输客户端内层仍为零重试，学习层统一控制预算，避免并发重试关闭共享连接；题量、评分、API 和数据库结构保持现状。

失败调用记录 task_id、阶段、slot（零基）、尝试次数、耗时、错误分类、HTTP 状态、底层异常类型和是否重试；不记录原文、题目、答案、密钥或异常响应正文。前端沿用 error_message，分别提示连接失败、服务繁忙、服务不可用、响应超时及响应契约异常；内容质量不足仍显示通过题数。

切换“检测配置 / 答题与结果”仅更新前端 view，轮询依赖 enabled，切换不会取消或重建后台任务。9月27日任务 ec91ebf2 在48秒后于审校阶段报 GeneratorTransportError，旧日志缺少底层原因，无法进一步判定具体网络或HTTP错误。

验证：使用模型替身验证重试次数上限、瞬断恢复、HTTP分类和日志脱敏；真实15题复测由用户在重启学习Worker后执行。Prompt仍为 learning_assessment_v2。

查看制度依据旁增加相关流程图/案例入口，每类最多1条，无结果隐藏；仅已提交、本人、未过期检测可查询，不改生成评分。详见[完整说明](LEARNING_MATERIALS.md)。
