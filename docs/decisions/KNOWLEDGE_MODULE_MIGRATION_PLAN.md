# 制度知识模块最终迁移方案

> 历史决策记录：其中“进程内问答”和“取消8010”的内容已经由ADR-0003取代。
> 当前仅保留管理侧解析、审核、分块、索引与目录能力的迁移结论；在线问答固定调用独立8010公开API。

> 文件说明：本文件是将 `D:\2-code\rag` 的关键能力迁入
> `D:\2-code\policy-platform` 的最终审核稿。方案面向本机测试项目，目标是保留
> 文档解析、审核、分块、索引和问答的完整能力，同时删除独立部署、制度投影、
> 大型评测体系和可重复生成的运行产物。本文件同时保留审核依据与执行范围。

## 1. 方案状态

- 状态：已于 2026-08-29 执行；验证结果见 `docs/testing/KNOWLEDGE_MIGRATION_VERIFICATION_2026-08-29.md`
- 源工程：`D:\2-code\rag`
- 目标工程：`D:\2-code\policy-platform`
- 源工程处理：迁移期间及验收后均保持不变，作为只读回退副本
- Python：固定使用 `D:\3-anaconda\envs\py312\python.exe`
- 依赖处理：只检查、不自动安装；缺少依赖时列出命令，由用户手动安装并确认
- 测试范围：只执行本方案定义的最小测试
- 配套规划：`docs/DOCUMENT_PROCESSING_MODULE_PLAN.md`

## 2. 最终决策

本次迁移采用以下确定方案：

1. RAG不再作为独立8010服务运行，而是成为后端内部的 `knowledge` 模块。
2. Platform通过进程内 `KnowledgeService` 查询知识模块，不再发起
   `POST /v1/rag/query` HTTP请求。
3. 保留现有问答结果的核心语义和版本化Citation字段，继续正确处理
   `ANSWER`、`INSUFFICIENT_EVIDENCE`、`CONFLICT`。
4. 删除Platform制度投影，制度目录、节点和PDF直接通过知识模块读取
   `policy_parser.db` 的active数据。
5. Platform聊天、Citation快照、反馈、用户和配置继续写入 `platform.db`。
6. 解析、Node、Chunk、审核和IndexRun继续写入 `policy_parser.db`。
7. 两个SQLite不合并；这是减少改造量和避免破坏现有运行记录的最简方案。
8. 完整迁移知识数据库，但只迁移必要文件；MD、JSON报告和测试产物不迁移。
9. 不重建Qdrant，不迁移Qdrant物理storage，继续使用现有collection和alias。
10. 不迁移大型评测体系、负载测试、熔断器、API工作池和历史评测结果。
11. 未来文档处理先使用统一服务和CLI；管理页面需要异步执行时再增加单进程本地Worker，
    不预先引入Celery、Redis或消息队列。
12. 当前 `platform.db` 全部为可丢弃测试数据；迁移时不编写投影表兼容删除迁移，直接重建数据库，
    并将现有三段Platform迁移压缩为一个最终基线。

## 3. 目标目录

```text
policy-platform/
├─ frontend/
│
├─ backend/
│  ├─ app/                         # Platform API、聊天、用户、反馈、配置
│  │  ├─ api/
│  │  ├─ application/
│  │  ├─ domain/
│  │  ├─ infrastructure/
│  │  └─ schemas/
│  │
│  ├─ knowledge/                   # 完整制度知识功能
│  │  ├─ parser/                   # DOCX校验、解析、结构识别、PDF页码映射
│  │  ├─ chunking/                 # Chunk生成、来源映射和审核
│  │  ├─ indexing/                 # Embedding、Qdrant、IndexRun
│  │  ├─ retrieval/                # Dense检索和Rerank
│  │  ├─ rag/                      # Context、生成、Citation、质量门禁
│  │  ├─ catalog.py                # active制度、节点、PDF查询
│  │  ├─ contracts.py              # 内部查询结果和Citation契约
│  │  ├─ service.py                # KnowledgeService统一入口
│  │  ├─ config.py                 # 知识模块配置
│  │  └─ cli.py                    # 解析、审核、分块、索引和查询命令
│  │
│  ├─ migrations/                  # Platform业务库迁移
│  ├─ tests/                       # 迁移后最小测试
│  └─ requirements.txt
│
├─ docs/
├─ scripts/
└─ var/
   ├─ platform.db
   └─ knowledge/
      ├─ policy_parser.db
      ├─ source_documents/
      ├─ accepted/
      └─ pdf/
```

不创建额外的 `knowledge_engine`、`document_pipeline` 或顶层
`backend/infrastructure`。解析流水线和在线问答是 `knowledge` 模块内部的两组能力，
不需要再增加物理层级。

迁移完成后的Platform迁移目录只保留最终基线：

```text
backend/migrations/versions/
└─ 0001_unified_platform_baseline.py
```

知识数据库的运行表和兼容逻辑不纳入Alembic。

## 4. 代码迁移白名单

### 4.1 文档解析

从 `policy_parser` 迁移以下能力：

- `ooxml.py`
- `analyzer.py`
- `render.py`
- `pipeline.py`
- `database.py` 中的解析数据访问逻辑
- `review.py`

不迁移：

- `fidelity.py`及其批量评测产物
- `exporter.py`生成的历史MD
- `platform_projection.py`
- 仅用于历史导出的辅助逻辑

### 4.2 分块与审核

迁移：

- `chunker.py`
- `chunk_review.py`
- Chunk与Node来源映射逻辑
- ChunkRun审核和active指针切换规则

不迁移：

- 历史Chunk MD/JSON
- `confirm_all_chunk_reviews.py`
- 绕过逐运行审核的批量确认入口

### 4.3 索引与检索

迁移：

- `policy_index/config.py`
- `policy_index/database.py`
- `policy_index/embedding.py`
- `policy_index/indexer.py`
- `policy_index/qdrant_store.py`
- `policy_index/retriever.py`
- `policy_index/reranker.py`
- `policy_index/rerank_retriever.py`

继续保持：

- IndexRun版本记录；
- 版本化collection；
- Qdrant alias切换；
- 构建失败不改变active索引；
- active ChunkRun变化时拒绝发布过期索引。

### 4.4 RAG

迁移 `policy_rag` 的核心实现：

- Context Builder和Token预算；
- Generator和Prompt；
- Answer Parser；
- Citation和Evidence；
- `answer_quality_gate_v2`；
- RagRuntime和端到端编排。

不迁移独立 `rag_api` 包，只将必要的公开响应转换逻辑整理到
`knowledge/contracts.py`。

### 4.5 CLI

原有多个根目录脚本合并为一个入口：

```powershell
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli import ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli parse ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli review-parse ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli chunk ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli review-chunk ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli index ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli activate-index ...
D:\3-anaconda\envs\py312\python.exe -m knowledge.cli query ...
```

不迁移 `confirm_all_reviews.py` 和 `confirm_all_chunk_reviews.py`。

## 5. 明确排除的内容

以下内容不进入新工程：

- `.policy_parser_output/test_artifacts`
- `.policy_parser_output/pytest_temp`
- `.policy_parser_output/backups`
- `.policy_parser_output/fidelity`
- `.policy_parser_output/chunks` 中的MD/JSON导出
- `.policy_parser_output/exports`
- `.policy_parser_output/reports`
- `.policy_parser_output/quarantine`
- `rag_eval/results`
- `dense_smoke_eval/results`
- `model_contract_tests/results`
- Python缓存和pytest缓存
- 历史日志
- Qdrant Docker storage
- 模型权重
- 已被当前设计替代的旧文档
- 独立8010服务、工作池、熔断器、队列容量和readiness探测
- 120题自动回归、负载测试和并发测试

旧RAG目录保持不变，因此被排除内容仍可在需要时人工查阅。

## 6. 数据迁移方案

### 6.1 必须迁移

迁移到 `var/knowledge`：

1. 完整的 `policy_parser.db`；
2. active制度对应的原始DOCX；
3. active ParseRun对应的accepted DOCX；
4. active ParseRun对应的PDF。

完整保留数据库中的历史运行记录、审核状态、Node、Chunk、IndexRun和所有ID。
只保证active运行链条所引用的文件在新工程中可访问；失败和过期运行的历史文件继续保留在
旧RAG目录。

### 6.2 不迁移

- `policy_parser.db-shm`
- `policy_parser.db-wal`
- 解析报告JSON
- 结构化Node MD
- Chunk MD和审核导出JSON
- 可重新生成的评测证据目录
- Qdrant物理文件

### 6.3 数据库复制方式

迁移时必须先停止Parser、Chunker、Indexer和旧8010进程，再执行SQLite
checkpoint和备份。不得在写入进程运行时直接复制数据库文件。

复制完成后执行：

- `PRAGMA integrity_check`；
- `PRAGMA foreign_key_check`；
- active制度数量核对；
- active Node数量核对；
- ParseRun、ChunkRun、IndexRun指针核对；
- 数据库SHA-256核对。

### 6.4 路径改写

当前数据库中的 `source_file`、`accepted_docx_path`、`pdf_path` 包含旧绝对路径。
迁移时统一改为相对 `knowledge_data_root` 的路径，例如：

```text
source_documents/制度文件.docx
accepted/制度文件__checksum__accepted.docx
pdf/制度文件__checksum.pdf
```

运行时通过以下配置解析：

```text
POLICY_KNOWLEDGE_DATA_ROOT=D:\2-code\policy-platform\var\knowledge
```

完成改写后验证每个active制度的三个文件路径和checksum。

## 7. 制度投影移除方案

删除以下运行代码：

- `DocumentProjection`
- `DocumentNodeProjection`
- `ProjectionImportService`
- 投影JSON导入逻辑
- 投影一致性验证脚本
- RAG侧 `platform_projection.py`

保留现有制度HTTP接口，但将 `DocumentService` 的数据源替换为
`KnowledgeCatalogService`：

```text
GET /api/v1/documents
GET /api/v1/documents/{document_id}
GET /api/v1/documents/{document_id}/nodes
GET /api/v1/documents/{document_id}/pdf
```

`KnowledgeCatalogService` 只读取：

- active ParseRun；
- active制度元数据；
- active Node；
- active PDF路径。

当前 `platform.db` 中的数据均为可丢弃测试数据，因此不保留旧数据库兼容链路：

1. 修改前生成一份临时备份，仅用于本次迁移失败回退；
2. 删除旧测试数据库；
3. 删除原 `0001`、`0002`、`0003` 迁移文件；
4. 创建 `0001_unified_platform_baseline.py`；
5. 使用新基线创建最终 `platform.db`。

新基线只创建用户、会话、消息、Citation快照、反馈、诊断和配置等最终需要的Platform表，
不创建 `DocumentProjection` 和 `DocumentNodeProjection`。未来开发文档处理管理功能时，
再通过新的 `0002_document_ingestion_jobs.py` 增加任务和审核业务表。

## 8. 进程内问答方案

删除：

- `app.infrastructure.knowledge.KnowledgeEngineClient`
- `knowledge_engine_url`
- 8010 HTTP请求；
- RAG API工作池；
- RAG API熔断和健康探测。

新增统一入口：

```python
class KnowledgeService:
    def query(self, question: str) -> RagQueryResult:
        ...
```

ChatService直接调用 `KnowledgeService.query()`。

内部结果继续保留：

- `ANSWER`、`INSUFFICIENT_EVIDENCE`、`CONFLICT`；
- `document_id`、`primary_node_id`；
- ParseRun、ChunkRun和IndexRun ID；
- Citation和Evidence快照；
- 实际 `quality_gate.version`；
- 生成、检索和提示词版本。

Platform只使用稳定结果字段，不依赖草稿哈希、Claim绑定和Verifier内部判定。

## 9. 文档处理预留设计

迁移阶段实现可复用的服务边界，不开发完整管理页面和任务中心：

```python
import_document(path)
parse_document(document_id)
review_parse_run(run_id, decision)
build_chunks(parse_run_id)
review_chunk_run(run_id, decision)
build_index(activate=False)
activate_index(index_run_id)
```

必须保持：

```text
latest_parse_run_id != active_parse_run_id
latest_chunk_run_id != active_chunk_run_id
latest_index_run_id != active_index_run_id
```

索引构建与索引发布分离。管理功能调用 `build_index(activate=False)`，审核或发布动作才允许
切换Qdrant alias和active IndexRun。

第一版由CLI调用这些服务。以后增加页面时，如同步请求耗时过长，再添加一个单进程本地Worker；
Worker仍调用相同服务，不重写解析和索引逻辑。

## 10. 文件保留规则

迁移后按以下规则管理文件：

- 原始DOCX：长期保留；
- active ParseRun的accepted DOCX和PDF：长期保留；
- 正在审核的latest ParseRun文件：保留；
- 失败或被拒绝运行的文件：审核期间保留，之后允许清理；
- MD和JSON导出：需要时生成，不作为正式数据源；
- 数据库运行记录：长期保留；
- Qdrant索引：视为可从active Chunk重建的数据。

制度目录和问答不读取MD、JSON导出文件。结构化数据读取SQLite，向量检索读取Qdrant，
DOCX和PDF只用于原文追溯、预览和Citation页码。

## 11. 依赖处理

执行开始时只检查当前py312环境和现有 `backend/requirements.txt`，重点检查：

- `lxml`
- `pypdf`
- `qdrant-client`
- `requests`
- `docx2pdf`，可选
- `pywin32`，使用Microsoft Word COM时可选

如果缺少依赖，停止迁移并向用户列出类似以下命令，不自动执行：

```powershell
D:\3-anaconda\envs\py312\python.exe -m pip install <缺少的包及固定版本>
```

用户确认安装完成后再继续。

## 12. 执行顺序

审核通过后按以下顺序在一次迁移任务中执行，各步骤设置检查点：

### 步骤1：环境和源数据基线

- 检查固定Python解释器；
- 检查依赖，不安装；
- 记录源代码迁移白名单SHA-256；
- 记录知识数据库SHA-256和SQLite检查结果；
- 记录active制度、Node及各类运行指针；
- 记录Qdrant alias目标和point数量；
- 记录源文件、accepted DOCX和PDF的checksum。

### 步骤2：目标工程备份

由于目标目录当前不是Git仓库，修改前为本次受影响文件创建带时间戳的迁移备份清单和归档，
排除 `node_modules`、日志、数据库运行缓存和可重建文件。旧 `platform.db` 只作为迁移失败时的
临时回退文件，不迁入最终工程。

### 步骤3：迁移并重组核心代码

- 创建 `backend/knowledge`；
- 按白名单复制并重组核心实现；
- 更新导入路径；
- 合并配置；
- 建立统一CLI；
- 不修改源RAG工程。

### 步骤4：切换进程内查询

- 建立 `KnowledgeService`；
- 将公开响应转换迁入 `knowledge/contracts.py`；
- ChatService改为进程内调用；
- 删除Platform对8010客户端的运行依赖。

### 步骤5：移除制度投影

- 增加 `KnowledgeCatalogService`；
- 制度接口改读知识数据库；
- 删除投影导入代码；
- 删除原有三段Platform迁移；
- 创建不含投影表的统一Platform基线；
- 重建空的 `platform.db`；
- 保留新基线中的聊天Citation快照表结构，不保留旧测试记录。

### 步骤6：迁移正式数据

- 停止旧知识写入进程；
- 备份SQLite到 `var/knowledge`；
- 复制active链条DOCX和PDF；
- 将数据库文件路径改为相对路径；
- 执行完整性、外键、checksum和运行指针检查。

### 步骤7：删除目标工程中的废弃代码

- 删除8010客户端和配置；
- 删除制度投影代码、脚本和文档；
- 删除不再适用的相关测试；
- 将ADR-0001标记为已被新决策替代；
- 更新PROJECT_HANDOFF、V2设计文档、README和运行说明中关于8010、制度投影和独立工程的描述。

### 步骤8：最小验证

只执行第13节列出的最小测试。全部通过后才宣布迁移完成。

## 13. 最小测试与验收

### 13.1 自动测试

保留并执行四类测试：

1. 小型DOCX解析、ParseRun审核、ChunkRun生成和审核；
2. 索引发布失败不改变active IndexRun和Qdrant alias；
3. RAG三种回答状态及Citation公开字段转换；
4. Platform聊天和制度目录通过进程内知识模块正常工作。

### 13.2 数据检查

- `PRAGMA integrity_check = ok`；
- `PRAGMA foreign_key_check`无结果；
- 20份active制度保持不变；
- 1439个active Node保持不变；
- active ParseRun、ChunkRun、IndexRun保持不变；
- active制度的DOCX、accepted DOCX、PDF均存在且checksum一致；
- Qdrant alias和point数量保持不变。

### 13.3 最小真实冒烟

外部Qdrant和模型服务可用时只执行：

- 1个真实问答；
- 最多3至5题最小冒烟；
- 1次Citation写入和历史消息回读；
- 1次制度列表、节点和PDF访问。

### 13.4 不执行

- 120题回归；
- 并发、负载和压力测试；
- 长时间稳定性测试；
- 全部制度重新解析；
- Qdrant全量重建；
- Chrome 89测试；
- PDF视觉版式核对。

## 14. 完成条件与当前状态

- [x] 运行代码不再引用 `D:\2-code\rag`；
- [x] Platform运行代码不再依赖8010；
- [x] Platform运行代码不再依赖制度投影；
- [x] Platform数据库可由单一统一基线从空目录创建；
- [x] 进程内问答契约保持三种回答状态和Citation信息；
- [x] 制度列表、详情、节点和PDF接口正常；
- [x] 两个SQLite职责清晰且检查通过；
- [x] 数据库记录中的active运行指针未发生非预期变化；
- [x] 最小自动测试通过；
- [x] 源RAG工程未被修改；
- [x] 操作文档已更新；
- [ ] 外部Qdrant与模型服务可用后的真实问答和alias在线回读。

代码、数据库和文件迁移已经完成。最后一项是外部服务联调验收：本轮Qdrant端口未监听，
因此未启动外部组件或以离线结果替代真实问答，详见迁移验证记录。

## 15. 回退方案

如果迁移验证失败：

1. 停止新后端；
2. 使用迁移前归档恢复目标工程受影响文件；
3. 恢复临时备份中的原 `platform.db`；
4. Platform重新使用旧8010配置和客户端；
5. 知识查询继续由未修改的 `D:\2-code\rag` 提供；
6. 不修改Qdrant alias和旧知识数据库。

由于源RAG工程不删除、不移动、不修改，回退不依赖重新构建解析数据或索引。

## 16. 审核确认项

开始执行前，请确认以下内容：

- [x] 同意删除制度投影，制度目录直接读取知识数据库；
- [x] 同意取消独立8010，改为进程内调用；
- [x] 同意继续保留 `platform.db` 和 `policy_parser.db` 两个数据库；
- [x] 同意丢弃现有Platform测试数据，并将Platform迁移压缩为一个最终基线；
- [x] 同意完整迁移运行记录，但只迁active链条必要文件；
- [x] 同意不迁移MD、JSON报告、评测结果、quarantine和历史备份；
- [x] 同意不重建或移动Qdrant；
- [x] 同意本轮只执行最小测试；
- [x] 同意旧RAG目录保持不变并作为回退副本。

用户已明确审核通过，迁移已按上述范围执行。未启动的外部服务联调和长耗时测试记录在迁移验证文档中，不影响代码与数据迁移结果。
