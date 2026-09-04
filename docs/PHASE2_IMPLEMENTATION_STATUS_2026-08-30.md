# 第二期实施与首次发布状态（2026-08-30）

> 文件说明：记录第二期最终实现、首份真实制度审核与发布结果、配置方式、必要测试和仍需外部条件才能开展的事项。

## 2026-08-31 V2制度治理增量

- 已增加`policy_series`，明确`policy_document`是一份具体正式文件版本；
- 已增加版本化元数据修订、识别候选对照、人工确认、审核、修订和废止入口；
- 入库状态增加`METADATA_REVIEW`与`READY_FOR_INDEX`，Parse结构审核不再混同元数据确认；
- 已增加最多20份DOCX的批次组织、顺序上传和独立任务处理；
- 已增加`MANUAL_CORRECTION`派生ParseRun和`rework_of_job_id`，历史终态任务保持只读；
- 人工结构修正节点可在新ParseRun中单项确认，通过后再批准运行；源ParseRun不被覆盖；
- 已增加全局索引发布请求，IndexRun冻结具体MetadataRevision；
- 公开目录、正文和证据验证改为直接读取active IndexRun冻结来源；
- 只有Alias切换及回读核验成功后才更新正式发布状态，失败时旧快照继续生效；
- 废止元数据在制度治理页审核；由另一制度废止时，转到制度关系页建立`REPEALS`并绑定原文证据；
- Platform库已迁移至`0003_v2_governance`，现有两个active制度已非破坏性回填为正式文件版本和
  `PUBLISHED`元数据修订，未重建向量、未切换Alias。

## 一、第二期已完成范围

### 1. 身份与权限

- 保留 `AuthProvider → IdentityLink → UserAccount → AuthSession` 边界，本地登录可由未来4A替换，稳定 `user_id`、角色、服务端会话和审计模型保持不变。
- 已实现Argon2本地凭据、HttpOnly Cookie、CSRF和 `USER / REVIEWER / ADMIN`。
- `REVIEWER`负责ParseRun、ChunkRun和制度关系审核；`ADMIN`负责入库、关系草稿、流程维护与最终发布。
- 固定流程审核管理员已写入Platform `system_config`，当前指向正式管理员；环境变量 `PLATFORM_PROCESS_REVIEWER_USER_ID` 仍可覆盖数据库配置。

### 2. 制度入库与任务闭环

- 状态机已完整贯通：上传、预检、ParseRun、Parse审核、ChunkRun、Chunk审核、IndexRun、待发布、发布和失败重试。
- HTTP上传只返回202；解析、分块、Embedding、Qdrant索引和alias切换全部由单Worker串行执行。
- 任务详情展示状态事件、Document/ParseRun/ChunkRun/IndexRun ID、审核记录和受控SOURCE_DOCX、accepted DOCX、PDF产物。
- 状态事件记录对应run类型和run ID；失败重试保留原事件，不覆盖审计事实。

### 3. 真实审核工作台

- ParseRun详情展示真实Node树、字段候选、标准化值、置信度、页码、PDF、渲染引擎、覆盖率和质量问题。
- ChunkRun详情展示真实Chunk正文、类型、字符数、token数、页码、主Node及全部来源Node映射、重复和覆盖率指标。
- 单项审核支持字段/Node/问题确认、忽略、驳回和字段更正；运行结论统一为 `PASS / PASS_WITH_WARNING / REJECT`。
- 已完成运行继续保留为只读审核历史，不因任务发布后从工作台消失。

### 4. IndexRun、Embedding与Qdrant发布

- Worker先构建 `activate=false` 的IndexRun，逐点回读校验后进入 `READY_TO_PUBLISH`。
- 管理员显式确认后进入发布队列，由Worker切换 `policy_platform_dense_active` 并回读alias目标，最后更新active IndexRun。
- Platform使用独立profile、collection前缀和alias，不删除、不覆盖原RAG的 `policy_dense_active`。
- 发布失败不改变旧alias和active指针，人工重试从失败阶段继续。

### 5. 制度关系与流程证据

- 制度关系支持 `CITES / SUPERSEDES / REPEALS / RELATED_TOPIC / CONFLICTS_WITH` 受控枚举。
- 关系生命周期为 `DRAFT / PENDING_REVIEW / CONFIRMED / REJECTED / NEEDS_REVIEW`，只有人工审核后成为正式关系。
- 关系与流程节点/连线复用 `EvidenceReference`，保存Document、ParseRun、Node、页码、原文快照和SHA-256。
- 详情打开、送审和发布时统一执行证据有效性检查；active ParseRun变化后标记 `STALE/NEEDS_REVIEW`，不自动重绑。
- 流程维持 `DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED`，固定流程审核管理员审核，ADMIN发布；已发布历史修订只读。
- 前端使用ECharts展示已确认制度关系，AntV X6维护流程节点和连线；证据选择器只列出真实active制度Node，不制造候选数据。

### 6. DOCX无界面渲染

- `POLICY_DOCX_RENDER_ENGINE` 支持 `auto_headless / libreoffice / word`。
- 默认 `auto_headless`：优先LibreOffice Headless，Windows未安装LibreOffice时回退到隐藏Word。
- `POLICY_LIBREOFFICE_PATH` 可显式指定 `soffice`，同时支持PATH和Windows常见安装目录发现。
- LibreOffice使用独立临时用户配置目录，完成后清理，避免服务账户配置锁冲突。

## 二、首次真实制度发布结果

| 对象 | 结果 |
|---|---|
| IngestionJob | `PUBLISHED`，进度100% |
| Document | 1 |
| ParseRun | 1，approved，27个Node，57个Source Block，6页PDF |
| Parse质量 | 字符、Block、表格单元格和页码映射覆盖率均为100%，问题0 |
| ChunkRun | 1，approved，16个可检索Chunk |
| Chunk质量 | 19/19合格Node映射，覆盖率100%，重复0，问题0 |
| IndexRun | 1，succeeded / active |
| 向量核验 | expected 16、indexed 16、verified 16、failed 0 |
| Platform alias | `policy_platform_dense_active → policy_platform_dense_cfeaea5224cb_4ffad605` |
| 原RAG alias | `policy_dense_active` 保持原目标，未修改 |
| 最小真实问答 | `ANSWER`，685字，7条Citation，使用IndexRun 1 |
| 质量门契约 | `answer_quality_gate_v2`，未写死旧版version |

## 三、配置示例

```powershell
$env:POLICY_DOCX_RENDER_ENGINE = 'auto_headless'
$env:POLICY_LIBREOFFICE_PATH = 'C:\Program Files\LibreOffice\program\soffice.exe' # 安装后可选
$env:POLICY_EMBEDDING_URL = 'http://10.9.7.1:8001/v1/embeddings'
$env:POLICY_EMBEDDING_MODEL = 'qwen3-embedding-4b'
$env:POLICY_EMBEDDING_DIMENSION = '2560'
$env:POLICY_QDRANT_URL = 'http://127.0.0.1:6333'
```

本机当前未安装LibreOffice，因此已经发布的首份制度记录的渲染引擎仍为 `ms_word_docx2pdf`。代码默认顺序已经改为无界面优先；安装LibreOffice后，新ParseRun会自动优先使用 `libreoffice_headless`。

## 四、已执行的必要测试

- Python `compileall`：通过。
- 本轮V2定向测试：制度系列、元数据状态确认、人工Parse修正、Alias失败保护、active目录边界、
  入库状态和健康检查共14项，通过。
- 正式数据只读接口联调：任务列表/详情、审核历史/详情、索引状态、证据目录、关系、流程、制度列表共9个接口，全部HTTP 200。
- 前端TypeScript检查：通过。
- 前端生产构建：通过；关系页与流程设计器已按路由懒加载。Vite仍提示X6页面chunk超过500KB，这是非阻断构建警告。
- 现代Chromium冒烟：任务100%发布、闭环事件/审核/产物、ParseRun真实详情、关系空态、流程空态和浏览器控制台均通过，控制台错误0。
- 首份制度最小真实问答：返回 `ANSWER`，引用7条真实证据，使用当前active IndexRun 1，`quality_gate.version=answer_quality_gate_v2`。

## 五、按既定边界未执行

- 未执行Chrome 89实机测试；按用户安排在其他机器验证。
- 未执行负载、压力、长时间稳定性或8010暖态性能测试，因此未冻结SLA、超时提示阈值和并发容量。
- 未实现单位4A具体协议；需取得单位的登录、回调、属性映射和退出规范后接入 `FourAAuthProvider`。
- 未安装LibreOffice；依赖安装仍由用户手动决定。
- 当前已有两份active制度；本轮未代用户建立缺少真实业务依据的制度关系，关系创建、证据绑定和审核入口已可用。
- 当前没有正式流程业务内容，因此未代用户创建示例流程；流程证据功能已经可以绑定现有制度Node。

## 六、审核工作台问题修复（2026-08-30）

- 运行历史按“解析结果/分块结果”分组切换，不再混排ParseRun和ChunkRun。
- 修复同一任务在ParseRun与ChunkRun之间点击时详情不刷新的依赖错误。
- Chunk质量指标补齐中文名称并扩大质量检查区域，百分比和值不再逐字换行。
- ParseRun通过后轮询新ChunkRun并自动切换；ChunkRun通过后明确提示由单Worker处理待索引。
- 任务中心每5秒静默刷新，明确展示“待索引 → Worker自动处理 → 待发布 → 管理员确认发布”。
- 公开制度库和关系/流程证据候选只展示当前active IndexRun来源清单中的制度；仅通过ParseRun审核但尚未发布索引的制度不再提前可见。
- 元数据统一维护、发布后废止修订、深度结构纠错和多文档批量处理已登记到V2待完善内容。

### 2026-08-31验证结果

- “测试2”的待索引任务已由单Worker推进为 `READY_TO_PUBLISH`；IndexRun 2包含29个向量，写入和回读验证均为29/29，当前保持inactive，未代管理员发布。
- 现代浏览器已验证解析/分块分组切换、同一任务和不同任务详情切换、Chunk质量中文指标以及页面无横向溢出。
- 制度库实际只显示active IndexRun 1中的1份制度；制度2虽然ParseRun和ChunkRun均已批准，但IndexRun 2发布前保持不可见。
- 任务中心能够明确显示待索引由Worker处理，并显示制度2当前处于“待发布”。
- 开发模式仍有React Router未来版本提示和AntD内部 `findDOMNode` StrictMode弃用提示；未发现本次功能的API失败、渲染异常或交互阻断。

## 七、日常启动

```powershell
Set-Location 'D:\2-code\policy-platform'
& '.\scripts\dev-backend.ps1'
& '.\scripts\dev-frontend.ps1'
& '.\scripts\dev-worker.ps1'
```

生产化切换MySQL、配置服务账户和安装LibreOffice时，不需要修改业务状态机、权限模型或证据引用模型。
