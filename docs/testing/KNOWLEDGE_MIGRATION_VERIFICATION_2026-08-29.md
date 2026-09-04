# 知识模块迁移验证记录（2026-08-29）

> 文件说明：记录从 `D:\2-code\rag` 迁入统一工程后的代码、数据库、文件和最小测试结果。
> 本文是当日历史快照；其中进程内问答结论已由ADR-0003取代，当前Platform通过独立8010公开API问答。

## 1. 结论

代码与 active 数据迁移完成。Platform 现在通过进程内 `KnowledgeService` 和 `KnowledgeCatalogService` 使用知识能力，不依赖 8010 或制度投影。原 RAG 工程的 42 个纳入清单的源代码文件与迁移前哈希完全一致。

迁移前目标工程备份位于：

```text
D:\2-code\policy-platform\var\migration_backup\20260829_172156
```

## 2. 数据校验

| 项目 | 结果 |
|---|---:|
| Knowledge SQLite integrity_check | `ok` |
| Knowledge foreign_key_check | 0 |
| Document | 20 |
| ParseRun | 72 |
| Node | 5037 |
| ChunkRun | 30 |
| Chunk | 869 |
| IndexRun | 3 |
| active Document | 20 |
| active Node | 1439 |
| active IndexRun | 3 |
| active 索引计数 | 579 / 579 / 579 |
| active alias 记录 | `policy_dense_active` |
| 迁移文件 | 60 |
| 文件哈希异常 | 0 |
| 绝对 source_file 路径 | 0 |

源知识数据库 SHA-256：

```text
dadd29b5cca6c2a32171398abf6961ba5a6823f971b056e5ade7a1b225f8bd11
```

迁移后知识数据库 SHA-256：

```text
151f997e8964f846b9dd9b5d588516ec57107a15b2db839627bbbed3eb856e94
```

两者哈希不同是预期结果：目标数据库保留全部运行记录，但将 active 文件路径改为相对路径，并清空未迁移历史运行的文件路径。逐文件记录见 `var/knowledge/migration_manifest.json`。

Platform 数据库从空库建立，`integrity_check=ok`、外键错误为 0，只包含平台业务表和 `alembic_version`，不包含制度投影表。Alembic 当前版本为 `0001_unified_platform_baseline (head)`，`alembic check` 无待生成操作。

## 3. 已执行的最小测试

1. 后端：`pytest tests -q -p no:cacheprovider -p no:tmpdir`，7 项通过。
2. 前端：`pnpm typecheck` 和生产构建通过；Vite 仅提示主包超过 500 kB，未影响构建。
3. CLI：`python -m knowledge.cli --help`，成功列出 import、parse、review-parse、chunk、review-chunk、index 和 query。
4. OpenAPI：已重新生成 `docs/api/openapi.json`。
5. Platform API 进程内冒烟：ready、制度列表、详情、Node、PDF 均为 HTTP 200；列表返回 20 份制度，抽样制度返回 109 个 Node，PDF 类型为 `application/pdf`。
6. 数据：两个 SQLite 完整性、外键、运行计数、active 指针、相对路径及 60 个迁移文件 SHA-256 均已复核。
7. 源工程：迁移清单内 42 个源代码文件哈希差异为 0，源知识数据库哈希与迁移前一致。

## 4. 本轮未执行

- 真实 RAG 问答：本机 Qdrant 6333 未监听，未启动或修改外部服务。
- Qdrant alias 在线回读和重建。
- Embedding、Reranker、Generator 契约联调。
- 120 题回归、负载、并发、压力和长时间稳定性测试。
- 全部制度重新解析或重新索引。
- Chrome 89 实机测试和 PDF 视觉版式核对。

这些项目属于外部服务或长耗时验收，不影响本次代码、数据库与 active 文件迁移结论。需要真实问答时，先启动 Qdrant 和模型服务，再执行少量固定问题即可。
