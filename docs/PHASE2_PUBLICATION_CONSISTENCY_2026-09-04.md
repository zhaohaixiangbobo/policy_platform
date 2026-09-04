# 第二期发布一致性与元数据迁移实施记录

> 文件说明：记录 2026-09-04 完成的发布来源冻结、任务协调、元数据草稿保护、显式历史迁移和实际数据修复。

## 1. 最终规则

1. 每个索引发布请求在 `index_publication_source` 中冻结 `document_id`、`parse_run_id`、
   `chunk_run_id` 和 `metadata_revision_id`；首次入库同时绑定 `job_id`，纯元数据修订不制造虚构 Job。
2. Worker 只推进发布请求明确绑定的 Job。绑定 Job 不是预期状态时，在调用索引构建或 Alias
   切换前失败，禁止其他失败任务搭车上线。
3. IndexRun 构建完成后，Worker 将实际 `index_run_source` 与全部冻结来源逐项比较。任一版本不一致，
   发布请求失败且不得进入确认发布。
4. 只有 Alias 切换并回读核验成功，发布请求、对应元数据审核请求和绑定 Job 才进入 `PUBLISHED`。
5. 失败请求通过原请求重试，保留冻结来源和审计链，不新建一份语义相同的发布请求。

## 2. 元数据草稿规则

- 新上传文档由正常建档流程创建 `policy_series`，数据库连接初始化不再回填业务元数据。
- 首次 `PARSE_EXTRACTED` 草稿必须绑定已批准的 active ParseRun。
- `MANUAL_CORRECTION` 和 `REPEAL` 只允许从已经审核的元数据创建。
- `REPEAL` 只允许针对已经正式发布且当前为 `effective` 的制度版本。
- 当前存在其他类型待处理草稿时返回冲突；Platform 元数据请求的类型或 Job 不一致时同样返回冲突，
  不再静默复用草稿或抢占审核请求。

## 3. 显式数据迁移

历史正式制度元数据迁移已从 `ParserDatabase.__init__()` 移到：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts\migrate-knowledge-metadata.py
```

迁移版本为 `20260904_historical_published_metadata_v1`，结果记录在知识库
`knowledge_data_migration` 表。它只处理 active IndexRun 已引用、尚无元数据修订且拥有 active ParseRun
的历史正式文档；新上传和待审核文档不在迁移范围内。重复执行只返回已记录结果。

## 4. 受控一致性修复

检查命令默认只读：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts\repair-phase2-consistency.py
```

确认计划后才执行：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts\repair-phase2-consistency.py --apply
```

脚本只在 active IndexRun 的 Document、ParseRun、ChunkRun、MetadataRevision 与 Platform 任务完全匹配时，
把索引/发布阶段失败的 Job 协调为 `PUBLISHED`。清理对象必须同时满足：`BACKFILL/DRAFT`、
`parse_run_id IS NULL`、没有批准/生效指针、没有 Platform 审核请求，且仍是文档 latest 草稿。
脚本不调用 Embedding、Qdrant 或 Alias。

## 5. 本次实际数据结果

- Platform Alembic 已升级到 `0005_index_publication_job`。
- 显式知识迁移已登记，当前没有需要迁移的历史正式文档，计数为 0。
- doc 8 的 Job `ee8311b5-840d-4e02-b714-c53e7c3b9e4a` 已依据 active IndexRun 5
  的精确来源，从 `FAILED` 协调为 `PUBLISHED`，并补齐 `index_run_id=5` 和发布来源绑定。
- 已删除未被审核请求引用的异常草稿 rev 5、6、7、8、9、11、12，并清空对应文档 3、4、5、6、7、9、10
  的 `latest_metadata_revision_id`。这些草稿按用户要求未备份，后续 ParseRun 审核通过时会走正常首次元数据草稿路径。
- active IndexRun 仍为 5；本次没有重建向量或切换 Alias。

## 6. 日志与验证

Worker 记录任务、文档和 Run 标识、阶段、耗时、错误码及重试属性；空闲轮询不刷日志。
默认日志为 `logs/worker.log`，采用 10 MB、5 个历史文件的滚动策略，可通过
`PLATFORM_WORKER_LOG_*` 环境变量配置。

本次只执行了定点后端测试、Python 编译检查、前端类型检查/构建以及修复后的只读数据库核对；
没有执行真实 Embedding、Qdrant、Alias、压力或长时间稳定性测试。
