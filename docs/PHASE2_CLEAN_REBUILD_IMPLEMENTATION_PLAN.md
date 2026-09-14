# 第二期清空重建与开发实施方案

> 文件说明：本文件是制度知识智能服务平台第二期清空测试数据、建立独立知识基线、重建平台业务库并继续开发管理功能的执行依据。本文覆盖删除范围、安全检查、数据库重建、Qdrant隔离、4A兼容认证、文档入库、关系与流程管理、测试和验收。  
> 当前状态：**已获用户批准并执行空基线重建；P2-0、P2-1及P2-2/P2-3/P2-5第一批工程骨架已实现。**  
> 目标工程：`D:\2-code\policy-platform`  
> 不操作工程：`D:\2-code\rag`

## 1. 方案结论

第二期不继续保留迁移进来的测试制度、知识运行记录、聊天、Citation、日志和迁移备份。工程保留已经迁入并整理好的知识模块代码，在空数据基线上通过新的Platform管理流程重新导入制度。

最终目标如下：

1. `policy-platform`拥有自己的Platform数据库、知识数据库、受控文档目录和Qdrant命名空间；
2. 运行时不访问、回退或同步`D:\2-code\rag`；
3. 原RAG目录保持不变，既不删除也不修改；
4. 新制度必须通过“上传、预检、解析、审核、分块、审核、建索引、发布”闭环进入active；
5. 用户、权限、会话、任务、审计、关系和流程归Platform业务库管理；
6. 文档、Node、ParseRun、ChunkRun、IndexRun及正式知识审核结果归知识数据库管理；
7. 第二期继续使用SQLite完成本机阶段，模型和迁移脚本同时保持MySQL可迁移性；
8. 所有依赖由用户手动安装，Codex不自动安装依赖。

## 2. 已确认的环境和当前状态

### 2.1 固定工具链

| 工具 | 固定版本或路径 | 当前检查结果 |
|---|---|---|
| Node.js | `22.23.2` | 已匹配 |
| pnpm | `11.22.0` | 已匹配 |
| Python | `D:\3-anaconda\envs\py312\python.exe` | Python 3.12.12，可用 |
| 浏览器测试 | 当前现代Chromium | Chrome 89由用户在其他机器验证 |

### 2.2 后续依赖门禁

当前环境和项目依赖清单已冻结`python-multipart 0.0.20`与`argon2-cffi 25.1.0`。流程和关系可视化前端依赖已经安装，冻结版本如下：

| 包 | 冻结版本 | 用途 |
|---|---:|---|
| `@antv/x6` | `3.1.7` | 流程图编辑器、节点和连线交互 |
| `@antv/x6-react-shape` | `3.0.1` | 使用React 18组件渲染流程节点 |
| `echarts` | `6.1.0` | 制度关系和已发布流程的只读可视化 |

版本依据：[@antv/x6 npm](https://www.npmjs.com/package/%40antv/x6)、[X6 React节点兼容说明](https://x6.antv.antgroup.com/tutorial/intermediate/react)、[Apache ECharts npm](https://www.npmjs.com/package/echarts)。X6 3.x与React适配包3.x配套，当前工程React 18.3.1满足官方React 18以上要求。

前端手动安装命令：

```powershell
Set-Location 'D:\2-code\policy-platform'
pnpm --filter @policy-platform/frontend add @antv/x6@3.1.7 @antv/x6-react-shape@3.0.1 echarts@6.1.0
```

以上命令由用户在确认后手动执行。安装后必须保留lockfile，并在P2-5实施前执行生产构建和现代浏览器冒烟；Chrome 89实机仍由用户按冒烟清单验证。

执行原则：

1. P2-1开始前，检查密码哈希方案并冻结`argon2-cffi`的兼容版本；
2. P2-2开始前，将`python-multipart`作为直接依赖固定到后端依赖文件；
3. P2-5开始前，确认上述三个前端包已经按冻结版本安装，并验证生产构建；
4. 每次新增依赖前先向用户列出精确的手动安装命令，用户确认安装完成后再继续；
5. 不依赖当前环境中由其他软件间接安装的包。

## 3. 清空、保留和禁止操作范围

### 3.1 明确删除且不备份

删除以下Platform测试数据：

- `D:\2-code\policy-platform\var\platform.db`
- `D:\2-code\policy-platform\var\platform.db-wal`（存在时）
- `D:\2-code\policy-platform\var\platform.db-shm`（存在时）
- `D:\2-code\policy-platform\var\diagnostic_chat`中的测试诊断数据
- `D:\2-code\policy-platform\logs\rag_api`中的历史查询日志

删除以下迁移知识数据：

- `D:\2-code\policy-platform\var\knowledge\policy_parser.db`
- `D:\2-code\policy-platform\var\knowledge\policy_parser.db-wal`
- `D:\2-code\policy-platform\var\knowledge\policy_parser.db-shm`
- `D:\2-code\policy-platform\var\knowledge\source_documents`中的现有文件
- `D:\2-code\policy-platform\var\knowledge\accepted`中的现有文件
- `D:\2-code\policy-platform\var\knowledge\pdf`中的现有文件
- `D:\2-code\policy-platform\var\knowledge\pending`中的现有文件（存在时）
- `D:\2-code\policy-platform\var\knowledge\temp`中的现有文件（存在时）
- `D:\2-code\policy-platform\var\knowledge\migration_manifest.json`

删除迁移回退备份：

- `D:\2-code\policy-platform\var\migration_backup\20260829_172156`

上述删除完成后，原有20份制度、72个ParseRun、30个ChunkRun、3个IndexRun、43个历史待审核ParseRun和4个历史待审核ChunkRun全部不再保留。由于Platform数据库同时清空，不存在历史Citation或业务记录需要继续引用这些ID。

### 3.2 明确保留

- `backend/knowledge`中的Parser、Chunk、Index、Retrieval和RAG代码；
- `backend/app`和`frontend`产品代码；
- Alembic框架、测试框架和必要的小型独立测试夹具；
- 产品设计、架构决策和迁移历史文档；
- Node、pnpm和Python现有环境；
- 外部Embedding、Reranker、Generator服务配置能力。

历史ADR和迁移验证记录可以移入历史文档区，但不得继续作为当前运行事实源。

### 3.3 明确禁止操作

- 不删除、移动、修改或写入`D:\2-code\rag`；
- 不从原RAG SQLite恢复或复制数据；
- 不从原RAG目录重新复制DOCX、PDF、JSON或Markdown；
- 不修改旧RAG正在使用的Qdrant alias或collection；
- 不删除模型权重、Qdrant物理存储或其他工程的数据；
- 不自动安装任何Python或前端依赖。

## 4. 完全解耦后的总体结构

```text
浏览器
  ↓
Platform API
  ├─ Platform业务服务
  │    └─ platform.db（后续迁移MySQL）
  ├─ KnowledgeCatalogService（只读active知识）
  ├─ KnowledgeQueryService（在线问答）
  └─ KnowledgeManagementService（受控知识管理命令）
           ↑
       单进程Worker
           ↓
  policy_parser.db + var/knowledge文件
           ↓
  policy_platform_dense_* Qdrant命名空间
```

应用层规则：

- API路由不直接导入知识数据库、Qdrant适配器、Parser或Indexer；
- 在线问答与文档处理使用不同的服务入口和执行资源；
- 所有知识库写操作由单进程Worker串行执行；
- HTTP上传、审核和发布接口只校验权限、记录命令并返回，不执行长耗时流水线；
- Platform与知识数据库不建立跨库外键，通过稳定ID、运行版本和证据快照关联。

## 5. Qdrant独立命名空间

当前默认`profile=policy_dense`、`alias=policy_dense_active`可能与原RAG共享，必须在新基线中替换。

新Platform使用：

```text
profile_name: policy_platform_dense
alias_name:   policy_platform_dense_active
collection:   policy_platform_dense_*
```

处理规则：

1. 不删除原`policy_dense_active`及其collection；
2. 新知识数据库中只创建`policy_platform_dense`配置；
3. 第一次索引构建只创建新collection，不建立active alias；
4. IndexRun验证通过且管理员确认发布后，才创建或切换`policy_platform_dense_active`；
5. 检索和RAG只读取知识数据库登记的active profile，不回退旧alias；
6. 以后清理旧RAG向量必须另行审核，不属于本方案。

共享Embedding、Reranker和Generator服务属于共享基础设施，不构成对旧RAG工程的运行时耦合。

## 6. 安全删除执行步骤

### 6.1 删除前检查

1. 确认目标工作目录为`D:\2-code\policy-platform`；
2. 确认后端、前端、Worker、CLI、旧8010进程和可能写入SQLite的脚本全部停止；
3. 确认没有`platform.db`、`policy_parser.db`的打开写入进程；
4. 再次列出所有删除目标的绝对路径、类型和大小；
5. 检查每个目标解析后的绝对路径均位于`D:\2-code\policy-platform\var`或`D:\2-code\policy-platform\logs`；
6. 明确排除`D:\2-code\rag`以及任何Qdrant目录；
7. 不创建备份，直接执行用户批准的清空。

### 6.2 删除方式

执行时使用单一PowerShell进程和`Remove-Item -LiteralPath`，不使用通配路径指向工程根目录，不跨Shell拼接删除命令。

安全校验逻辑：

```powershell
$projectRoot = [System.IO.Path]::GetFullPath('D:\2-code\policy-platform')
$allowedRoots = @(
    [System.IO.Path]::GetFullPath('D:\2-code\policy-platform\var'),
    [System.IO.Path]::GetFullPath('D:\2-code\policy-platform\logs')
)

function Assert-AllowedTarget([string]$path) {
    $resolved = [System.IO.Path]::GetFullPath($path)
    $allowed = $false
    foreach ($root in $allowedRoots) {
        $prefix = $root.TrimEnd('\') + '\'
        if ($resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $allowed = $true
            break
        }
    }
    if (-not $allowed) {
        throw "删除目标超出允许范围：$resolved"
    }
    return $resolved
}
```

正式执行时先逐项调用`Assert-AllowedTarget`并输出结果，再删除第3.1节列出的精确文件或目录内容。`var`、`var/knowledge`和项目根目录本身不得作为递归删除目标。

### 6.3 删除后核验

- `platform.db`及同名WAL/SHM不存在；
- `policy_parser.db`及同名WAL/SHM不存在；
- `source_documents/accepted/pdf/pending/temp`为空；
- `migration_manifest.json`不存在；
- 指定迁移备份目录不存在；
- 历史查询日志和诊断数据为空；
- `D:\2-code\rag`仍存在且未发生修改；
- 不执行任何Qdrant删除操作。

## 7. 空基线重建顺序

为避免删除后业务代码只能依赖旧数据运行，先在临时测试目录验证空基线创建逻辑，再清空正式数据。

### 7.1 清空前的临时验证

1. 将知识模块测试改为使用临时数据根目录；
2. 验证可以从不存在的SQLite文件创建完整知识表；
3. 验证空知识库目录查询返回0条制度而不是HTTP 500；
4. 验证没有active IndexRun时返回稳定的“知识库尚未发布”状态；
5. 验证Platform新基线可以在临时SQLite中从空库创建；
6. 验证测试不读取`var/knowledge`正式目录和`D:\2-code\rag`。

### 7.2 Platform业务库新基线

建立一次新的最终核心基线，第二期开始后不再压缩迁移历史。

建议迁移顺序：

```text
0001_platform_core_baseline
0002_document_ingestion
0003_policy_relations
0004_policy_processes
```

`0001_platform_core_baseline`至少包含：

- `user_account`
- `local_credential`
- `auth_provider`
- `identity_link`
- `role`
- `user_role`
- `auth_session`
- `system_config`
- `chat_session`
- `chat_message`
- `message_citation`
- `message_conflict`
- `conflict_position`
- `message_feedback`
- `eval_candidate`
- `platform_audit_log`

所有聊天、任务和审计使用内部稳定`user_id`，不再使用固定`local-user`。

### 7.3 SQLite阶段并发基础

Platform SQLite连接仅在SQLite方言下设置：

- `PRAGMA foreign_keys=ON`
- `PRAGMA journal_mode=WAL`
- `PRAGMA busy_timeout=5000`

WAL和busy timeout只解决本机SQLite的短暂读写竞争。任务正确性仍由租约、幂等键、状态条件更新和单Worker保证。切换MySQL后自动跳过SQLite PRAGMA，不改变业务服务。

### 7.4 知识库空基线

1. 重新创建空的`policy_parser.db`；
2. 创建Parser、Chunk、Index所需完整表结构；
3. 创建空的`source_documents/accepted/pdf/pending/temp`目录；
4. 创建`policy_platform_dense`索引配置，但active IndexRun保持为空；
5. Document、ParseRun、ChunkRun、IndexRun计数均为0；
6. 不生成迁移清单，不记录原RAG路径；
7. 新文档ID和运行ID从新数据库重新开始。

## 8. 4A兼容身份与权限设计

### 8.1 当前本地认证

```text
浏览器
  ↓
LocalAuthProvider
  ↓
identity_link
  ↓
user_account
  ↓
服务端Session / HttpOnly Cookie
  ↓
USER / REVIEWER / ADMIN
```

### 8.2 后续4A认证

```text
浏览器
  ↓
FourAAuthProvider（协议待单位规范确认）
  ↓
identity_link(provider_id, external_subject)
  ↓
同一个user_account
  ↓
服务端Session / HttpOnly Cookie
  ↓
同一套USER / REVIEWER / ADMIN权限
```

4A只替换“用户是谁”的认证方式，不替换Platform内部用户主键、角色、业务权限、会话和审计。

### 8.3 本地认证最小范围

保留：

- CLI初始化首个管理员；
- 管理员创建、停用和重置本地账号；
- 固定的最低密码要求和安全哈希；
- 一次性初始密码及首次登录强制修改；
- 服务端短期会话、会话撤销、HttpOnly Cookie；
- Cookie管理写操作的CSRF防护；
- 登录失败限制和完整审计。

不建设：

- 公开注册；
- 邮箱验证和邮箱找回；
- 短信验证码；
- 复杂密码策略管理页面；
- 完整用户资料中心；
- 与制度管理无关的用户社交资料。

4A身份必须使用不可变主体标识进行映射，不使用显示姓名作为外键。是否保留受控应急本地管理员，在4A正式接入时另行决策。

## 9. 第二期开发里程碑

### P2-0：空基线和管理服务边界

- 完成第3至第7节的清空与重建；
- 将当前问答入口明确命名为`KnowledgeQueryService`；
- 保留`KnowledgeCatalogService`只读active数据；
- 新增`KnowledgeManagementService`封装导入、解析、审核、分块、索引和发布；
- CLI和Worker复用管理服务，不把业务规则写在命令参数处理中；
- API路由不直接操作知识SQLite或Qdrant；
- 增加空知识库页面和未发布提示；
- 更新README、PROJECT_HANDOFF、运维说明和当前架构事实源，取消旧RAG回退描述。

### P2-1：身份、权限、会话和审计

- 实现第8节认证模型；
- 建立`USER/REVIEWER/ADMIN`三类角色；
- 角色用于粗粒度授权，具体接口使用明确权限码，不使用含义宽泛的“Reviewer”判断；
- `REVIEWER`负责ParseRun、ChunkRun和制度关系审核，对应`knowledge.parse.review`、`knowledge.chunk.review`和`policy_relation.review`；
- 流程审核采用双重条件：当前用户属于`REVIEWER`或`ADMIN`，并且`user_id`等于Platform配置中的固定流程审核管理员；
- 流程发布权限为`policy_process.publish`，只授予`ADMIN`；固定流程审核管理员审核通过后仍需ADMIN执行独立发布动作；
- 固定流程审核管理员不使用`review_assignment`，更换该用户必须记录配置变更审计；
- 普通制度、问答和管理接口按权限保护；
- 诊断接口仅允许受控管理员访问；
- 管理写操作启用CSRF；
- 用户停用或角色变化后撤销相关会话；
- 审计记录稳定`actor_user_id`、认证来源、request_id、对象、动作、结果和必要快照；
- 为4A保留Provider、回调、身份映射和退出接口，不提前实现具体协议。

### P2-2：上传、任务中心和单Worker

- 只接受DOCX；
- 校验扩展名、MIME、ZIP结构、压缩规模和路径安全；
- 计算SHA-256并识别重复上传；
- 上传内容先在内存预检，通过后进入`pending`；后续失败由任务与Run状态表达；
- 新增`ingestion_job`、`ingestion_job_event`、`ingestion_artifact`和`review_assignment`；
- Job包含幂等键、租约、心跳、尝试次数、阶段进度和错误结构；
- 第一版仅启动一个Worker，不引入Redis、Celery或多Worker；
- HTTP接口只保存文件和创建任务，返回`202 Accepted`；
- 第一版只支持人工重试，不自动无限重试。

#### P2-2.1 固定入库状态机

任务状态使用受控枚举，禁止页面、Worker或数据库脚本创建未定义状态：

```text
UPLOADED
  → PREFLIGHTING
  → PARSE_QUEUED
  → PARSING
  → PARSE_REVIEW
  → CHUNK_QUEUED
  → CHUNKING
  → CHUNK_REVIEW
  → INDEX_QUEUED
  → INDEXING
  → READY_TO_PUBLISH
  → PUBLISH_QUEUED
  → PUBLISHING
  → PUBLISHED
```

补充状态：

- `FAILED`：系统、文件或外部依赖失败，必须保存`failed_stage`、`error_code`、`retryable`和错误摘要；
- `REJECTED`：人工审核明确驳回，属于业务结果，不得记为系统失败；
- `CANCEL_REQUESTED`：运行中收到取消请求，Worker在安全检查点停止；
- `CANCELLED`：已安全取消，不再自动恢复。

状态转换规则：

1. `UPLOADED`、各`*_QUEUED`、`PARSE_REVIEW`、`CHUNK_REVIEW`和`READY_TO_PUBLISH`可以直接进入`CANCELLED`；
2. `PREFLIGHTING/PARSING/CHUNKING/INDEXING`只能先进入`CANCEL_REQUESTED`，再由Worker在安全检查点进入`CANCELLED`；
3. `PUBLISHING`开始执行alias切换后不接受取消，只允许完成幂等核验；
4. `PARSE_REVIEW`或`CHUNK_REVIEW`人工驳回后进入`REJECTED`，不得自动重跑；
5. `PUBLISHED`、`REJECTED`和`CANCELLED`为终态；重新处理必须创建新任务或新版本；
6. Worker使用`state_version`进行条件更新，任何越级、倒序或重复提交均返回冲突；
7. 每次转换写入`ingestion_job_event`，保存操作者、前后状态、时间、run ID和原因。

人工重试只允许从`FAILED`发起，且`retryable=true`：

| 失败阶段 | 重试目标 | 约束 |
|---|---|---|
| `PREFLIGHTING` | `UPLOADED` | 仅重新执行预检，不复制新文件 |
| `PARSING` | `PARSE_QUEUED` | 保留失败ParseRun，新建ParseRun尝试 |
| `CHUNKING` | `CHUNK_QUEUED` | active ParseRun必须与失败时一致，新建ChunkRun |
| `INDEXING` | `INDEX_QUEUED` | 保留失败IndexRun，新建IndexRun和版本化collection |
| `PUBLISHING` | 先执行发布对账 | alias已切换则补齐数据库状态；未切换则回到`READY_TO_PUBLISH` |

每次人工重试增加`attempt_no`并写审计。审核意见调整不叫重试：审核页在当前`PARSE_REVIEW/CHUNK_REVIEW`内完成问题确认、修正或驳回。

### P2-3：ParseRun、ChunkRun和IndexRun闭环

- ParseRun结构、字段、问题、PDF和页码预览；
- ParseRun审核与active切换分开；
- Chunk内容、来源Node、重复和超长问题审核；
- ChunkRun审核与active切换分开；
- IndexRun构建默认`activate=false`；
- 检查向量数量、collection、模型契约和source manifest；
- 管理员单独确认后切换`policy_platform_dense_active`；
- 任一失败不改变原active ParseRun、ChunkRun、IndexRun或alias；
- 首份制度必须通过本模块完整导入，禁止复制旧库或直接改active指针。

#### P2-3.1 标准审核结果

ParseRun和ChunkRun对外统一使用以下运行审核结果：

- `PASS`：不存在未处理的阻断问题或警告；
- `PASS_WITH_WARNING`：不存在阻断问题，所有警告均已逐项确认并填写接受理由；
- `REJECT`：存在不可接受问题或审核人明确驳回，不允许激活。

审核结果与单个问题处置分开。单个问题保存`severity=ERROR/WARNING/INFO`以及`OPEN/CONFIRMED/CORRECTED/IGNORED/REJECTED`处置状态。只有阻断问题全部解决后，运行才能得到`PASS`或`PASS_WITH_WARNING`。

ParseRun首批问题类型：

- `TITLE_DETECTION_ERROR`：标题识别错误；
- `HIERARCHY_ERROR`：章节、条款或编号层级错误；
- `PAGE_MAPPING_ERROR`：页码缺失、越界或映射异常；
- `TABLE_PARSE_ERROR`：表格行列、合并单元格或内容异常；
- `FIELD_EXTRACTION_ERROR`：文号、日期、机构等字段错误；
- `CONTENT_OMISSION`：正文或附件内容缺失；
- `IMAGE_REVIEW_REQUIRED`：图片内容需要人工确认；
- `OTHER`：必须填写说明的其他问题。

ChunkRun首批问题类型：

- `CHUNK_TOO_LONG`：Chunk超过配置上限；
- `CHUNK_TOO_SHORT`：Chunk过短且缺乏独立语义；
- `CHUNK_DUPLICATE`：正文重复或不允许的重叠；
- `SOURCE_NODE_MISSING`：缺少来源Node；
- `COVERAGE_GAP`：合格Node或正文覆盖不完整；
- `BOUNDARY_ERROR`：切分破坏条款、表格或语义边界；
- `CONTEXT_ERROR`：标题上下文或继承上下文错误；
- `OTHER`：必须填写说明的其他问题。

审核API、数据库、前端筛选和审计统一使用上述稳定枚举；用户可见中文名称由前端映射，不把中文文案作为数据库状态。

### P2-4：制度关系

第一版只实现：

- `CITES`：引用；
- `SUPERSEDES`：替代；
- `REPEALS`：废止。

关系存入Platform业务库，至少包含源/目标制度、ParseRun、Node、页码、证据原文、快照哈希、审核状态和有效期。active ParseRun变化时，关系进入待复核状态，不自动重绑新Node。LLM只能生成候选关系，不能直接确认。

#### P2-4.1 统一跨库证据失效检查

新增`EvidenceReferenceValidator`，由关系和流程共同使用。它只能通过只读Knowledge证据查询服务验证引用，不允许直接访问或修改知识SQLite。

统一验证结果：

- `VALID`：文档、ParseRun、Node归属和页码均有效，且引用的ParseRun仍为active；
- `STALE`：引用对象仍存在，但文档active ParseRun已经变化；
- `MISSING`：文档、ParseRun或Node不存在；
- `MISMATCH`：Node不属于指定文档/ParseRun，或页码与证据记录不一致；
- `UNAVAILABLE`：Knowledge服务暂时不可用；这是可重试故障，不得误标为`STALE`。

验证时点：

1. 打开详情时执行只读即时验证并返回当前结果，不让GET请求产生业务状态变更；
2. 审核提交时同步验证并持久化`validation_status/last_validated_at/active_parse_run_id_at_validation/invalid_reason`；
3. 发布时再次同步验证，任何非`VALID`结果都阻止发布；
4. active ParseRun变化后，关系进入`NEEDS_REVIEW`，未发布流程修订版进入待修复状态；
5. 已发布历史关系和流程保留原证据快照，只显示失效提示，不改写历史内容；
6. `UNAVAILABLE`只返回可重试错误，不改变原审核状态。

### P2-5：流程管理

第一版仅支持管理员人工创建流程节点、连线、条件和制度证据绑定。

生命周期：

```text
DRAFT 草稿
  ↓ 提交
PENDING_REVIEW 待审核
  ↓ 审核通过
APPROVED 已审核
  ↓ 发布
PUBLISHED 已发布
```

规则：

1. 审核退回时直接回到`DRAFT`并填写退回意见，不增加复杂状态；
2. `PENDING_REVIEW`和`APPROVED`内容不可编辑；
3. 发布失败保持`APPROVED`，不得自动生成重复版本；
4. 固定流程审核管理员通过Platform配置保存稳定`user_id`，该用户必须属于`REVIEWER`或`ADMIN`；
5. 不建立业务部门、责任角色、具体审核人的任务分配；
6. 管理员可以更换固定审核人，但必须记录审计；
7. 已发布流程不可修改；修改时复制为新的`DRAFT`修订版；
8. 已发布历史版本永久保留，只读查看；
9. 每个节点和连线可以绑定多条制度证据；
10. 证据保存`document_id`、`parse_run_id`、`node_id`、页码、原文和快照哈希；
11. 打开、审核和发布统一调用`EvidenceReferenceValidator`；失效证据阻止审核通过和新版本发布；
12. 历史发布版本保留当时证据快照，不随active制度变化而改写；
13. 自动抽取只允许创建来源为`AUTO_CANDIDATE`的草稿，不能审核或发布；
14. 使用`@antv/x6 3.1.7`、`@antv/x6-react-shape 3.0.1`和`echarts 6.1.0`；由用户按第2.2节命令手动安装。

### P2-6：条件功能

以下内容不阻塞第二期主闭环：

- LLM制度关系候选抽取；
- LLM流程候选抽取；
- 多轮Query Rewrite；
- 批量上传；
- 多Worker和分布式队列；
- 自动清理和复杂重试；
- SLA、超时提示阈值和并发容量；
- MySQL、4A具体协议、部门权限和密级过滤。

这些能力分别完成专项设计和最小评测后再启用，不提前写死契约。

## 10. 测试改造与最小验证

### 10.1 测试隔离

删除当前正式知识数据前，先移除测试对20份制度、1439个Node和正式`var/knowledge`目录的依赖。

测试统一使用：

- `backend/tests/fixtures`中的小型DOCX/PDF；
- 单次测试临时Platform SQLite；
- 单次测试临时Knowledge SQLite和文件根目录；
- Fake或隔离的向量存储；
- 不访问`D:\2-code\rag`；
- 不连接生产或旧RAG Qdrant alias。

### 10.2 每个里程碑的必要测试

P2-0：

- 空Platform数据库建立；
- 空Knowledge数据库建立；
- 空制度列表和未发布状态；
- 新Qdrant profile/alias配置不引用旧命名空间。

P2-1：

- 登录成功和失败；
- 角色权限拒绝；
- Cookie、CSRF和会话撤销；
- 4A身份映射接口契约；
- 管理动作审计。

P2-2：

- DOCX预检、恶意文件名、重复文件和失败状态留痕；
- Job原子领取、租约过期和Worker重启恢复；
- 固定状态机覆盖正常流转、非法越级、人工驳回、取消请求和终态；
- 各失败阶段只回到规定的重试入口，并创建新的运行尝试；
- 发布阶段中断后可以通过alias和数据库状态对账恢复；
- HTTP请求不执行解析；
- 单Worker并发下SQLite不出现未处理锁错误。

P2-3：

- ParseRun和ChunkRun未审核时不能激活；
- `PASS/PASS_WITH_WARNING/REJECT`及问题类型、严重级别和处置状态完整落库；
- 存在未解决阻断问题时不能获得PASS，警告未确认时不能获得PASS_WITH_WARNING；
- 失败运行不改变active；
- IndexRun构建与发布分离；
- alias切换失败保持旧alias；
- 一份小型DOCX的完整隔离闭环。

P2-4/P2-5：

- 关系和流程证据可追溯；
- `EvidenceReferenceValidator`在详情、审核和发布三个时点返回一致结论；
- `STALE/MISSING/MISMATCH`触发待复核或发布阻止，`UNAVAILABLE`不污染业务状态；
- REVIEWER、固定流程审核管理员和ADMIN发布权限相互区分；
- 流程退回、批准、发布和新修订版；
- 已发布版本不可修改。

### 10.3 本方案不自动执行的测试

- 120题或其他全量RAG回归；
- 并发、负载、压力和长时间稳定性测试；
- 全部制度批量解析或重新索引；
- 大规模数据迁移；
- Chrome 89实机测试；
- PDF视觉版式核对；
- MySQL正式迁移演练；
- 4A真实环境联调。

上述测试只准备命令和说明，由用户决定何时执行。

## 11. 首份制度重新导入验收

清空重建后，选择一份用户明确允许使用的测试DOCX，通过界面完成：

1. 管理员登录；
2. 上传DOCX；
3. 预检和SHA-256记录；
4. Worker创建ParseRun；
5. 审核结构、字段、PDF和页码；
6. 审核通过并激活ParseRun；
7. Worker创建ChunkRun；
8. 审核Chunk及来源Node；
9. 审核通过并激活ChunkRun；
10. 构建新的IndexRun；
11. 验证新Qdrant collection；
12. 管理员发布并切换`policy_platform_dense_active`；
13. 制度库显示该制度；
14. 执行1至3个真实问答最小冒烟；
15. Citation可以跳转到对应制度、Node和PDF页码；
16. 全流程管理操作均有审计记录。

第一份制度完成闭环前，不开始批量导入。

## 12. 文档更新

清空重建完成后同步更新：

- `README.md`：删除“原RAG只读回退副本”表述；
- `docs/PROJECT_HANDOFF.md`：改为独立空基线及新的后续开发顺序；
- `docs/deployment/OPERATIONS.md`：删除旧8010和旧RAG回退操作；
- `docs/deployment/LOCAL_DEVELOPMENT.md`：增加空知识库、Worker和认证启动方式；
- `docs/api/PLATFORM_API_V1.md`及OpenAPI：增加身份、管理、任务、审核和发布接口；
- `docs/UI_DESIGN_SPEC.md`：增加登录、管理后台、审核和流程页面；
- 迁移ADR和验证记录：标记为历史记录，不作为当前事实源；
- 新增清空重建完成记录，列出实际删除目标、零数据校验和新基线版本。

## 13. 风险与控制

| 风险 | 控制 |
|---|---|
| 无备份删除后不可恢复 | 用户已确认测试数据无需保留；删除前精确列出路径和范围 |
| 误删原RAG或其他目录 | 仅允许`policy-platform/var`和`policy-platform/logs`下的精确目标，逐项绝对路径校验 |
| 清空SQLite后仍检索旧向量 | 使用全新的`policy_platform_dense` profile和alias，不回退旧alias |
| 测试仍依赖迁移数据 | 删除前先把测试改为临时数据库和独立夹具 |
| API或Worker直接写知识表 | 所有写操作收口到`KnowledgeManagementService`和单Worker |
| SQLite锁竞争 | SQLite阶段使用WAL、busy timeout、租约、幂等键和单Worker |
| 任务状态含义不清或非法跳转 | 使用固定状态机、state_version、事件记录和逐阶段重试入口 |
| 人工驳回被误记为系统失败 | 使用独立`REJECTED`状态，FAILED只表示系统或依赖失败 |
| 后续MySQL迁移困难 | SQLAlchemy/Alembic使用可移植模型，SQLite PRAGMA隔离在适配层 |
| 4A接入导致业务用户ID变化 | 使用内部`user_id`和`identity_link`，4A仅替换AuthProvider |
| REVIEWER与流程审核人职责混淆 | Parse/Chunk使用权限码；流程审核同时校验角色和固定user_id；发布只允许ADMIN |
| 跨库引用没有数据库外键 | 详情、审核、发布统一调用EvidenceReferenceValidator并保存验证快照 |
| 流程证据随制度版本漂移 | 保存ParseRun/Node/页码/原文快照，发布前校验，历史版本不改写 |
| 自动抽取直接污染正式数据 | 自动能力只能创建候选草稿，人工审核和发布不可绕过 |

## 14. 执行检查清单

### 开始前

- [x] 用户审核并批准本文；
- [x] 依赖检查完成，手动安装命令已提供；
- [x] 用户确认所需依赖已安装；
- [x] 临时空库和测试隔离验证通过；
- [x] 后端、前端、Worker及SQLite写入进程已停止；
- [x] 删除目标绝对路径和大小已再次列出；
- [x] `D:\2-code\rag`和旧Qdrant命名空间已明确排除。

### 清空与重建

- [x] Platform数据库、知识数据库、测试文档、日志、迁移清单和迁移备份已删除；
- [x] 删除后目标不存在或目录为空；
- [x] Platform新核心基线已建立；
- [x] Knowledge空基线已建立；
- [x] 新Qdrant profile已冻结，旧alias未修改；
- [x] 空知识库页面和API状态正确；
- [x] 当前事实源文档已更新。

### 第二期主闭环

- [x] P2-0空基线和管理服务边界完成；
- [x] P2-1身份、权限、会话和审计完成；
- [x] P2-2上传、任务和单Worker完成；
- [x] P2-3 Parse/Chunk/Index审核发布闭环完成；
- [x] 首份制度通过新流程重新导入并完成最小问答；
- [x] P2-4制度关系完成；
- [x] P2-5人工流程管理完成；
- [ ] P2-6条件能力分别完成专项审核后启用。

## 15. 当前执行状态

截至2026-08-30，本方案中的空库重建及P2-0至P2-5已经完成。首份制度已通过上传、Parse审核、Chunk审核、Index构建、Qdrant校验和管理员首次发布闭环，并完成最小真实问答。

- Platform业务库和独立Knowledge库已按新基线重建；
- Platform使用独立的 `policy_platform_dense` profile与 `policy_platform_dense_active` alias；
- 原RAG的 `policy_dense_active` 保持原目标，`D:\2-code\rag`未修改；
- 身份权限、任务中心、真实审核、制度关系、人工流程和证据绑定已经实现；
- P2-6中的4A实接、Chrome 89实机、进程内RAG暖态容量与SLA仍按条件推进；
- 当前事实和验证结果以 `docs/PHASE2_IMPLEMENTATION_STATUS_2026-08-30.md` 为准。
