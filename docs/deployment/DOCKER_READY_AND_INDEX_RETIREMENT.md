# Docker-ready 与旧索引存储退役

> 文件说明：2026-09-24，版本 docker_ready_v1 / index_storage_retirement_v1。
> 当前已实现运行准备和索引清理保护；MySQL、Linux镜像和Compose仍为待批准阶段。

## 1. 本轮实施边界

- 保留当前双SQLite运行方式、单Worker和进程内RAG，不使用原rag工程或8010。
- `scripts/run-service.py api|worker|migrate` 提供与工作目录无关的启动入口；使用调用它的解释器。
- 本机PS1入口仍固定 `D:\3-anaconda\envs\py312\python.exe`，API保留开发热重载。
- `.env`统一从工程根读取，容器/系统已注入的环境变量优先；知识模块的POLICY配置同步生效。
- Linux安装清单排除pywin32、docx2pdf；python-dotenv固定为当前已安装的1.2.1，无新增安装。
- Worker处理SIGTERM/SIGINT时等待当前阶段完成再退出。未来Compose的停止宽限期需覆盖阶段执行时间；不能据此宣称强杀时也能完成阶段。
- `.dockerignore`排除数据库、上传文件、日志、密钥和本机node_modules。

## 2. Linux部署准备

环境模板：`docs/deployment/container.env.example`。生产时通过环境注入，禁止把实际密钥复制进镜像。

未来镜像需Python 3.12、LibreOffice Writer/Headless、fontconfig及经授权的中文字体。
固定 `POLICY_DOCX_RENDER_ENGINE=libreoffice`，soffice路径按镜像实际安装位置设置。
LibreOffice与Word存在字体和分页差异，Linux真实转换须单独验收，本轮未执行。

建议挂载：

| 内容 | 容器路径 | 所有权 |
|---|---|---|
| 当前Platform SQLite | /data/platform | API、Worker，迁移MySQL后替换 |
| 知识数据库及DOCX/PDF/temp | /data/knowledge | API、Worker，共享同一卷 |
| 日志 | /data/logs | 每进程独立日志文件 |
| Qdrant存储 | /qdrant/storage | 仅Qdrant |

镜像更新只替换程序，卷保持独立。数据库升级由独立迁移步骤执行，不让每个API副本同时执行迁移。
当前知识模块仍有运行时建表/补列，下一阶段接入知识库Alembic后移出运行时路径。
前端未来使用构建出的静态文件和同源 `/api` 反向代理，不以Vite开发服务器作为生产服务。
健康探针可调用 `/api/v1/health/ready`；它不代表所有模型依赖均已完成暖态验收。

本机入口示例：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' api
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' worker
# 仅在需要升级Platform库时显式执行
& 'D:\3-anaconda\envs\py312\python.exe' 'D:\2-code\policy-platform\scripts\run-service.py' migrate
```

## 3. 旧索引复用和退役契约

历史构建成功不等于物理存储仍可用：

- 成功IndexRun复用和人工发布前，检查collection存在及exact count匹配。
- 增加知识控制表 `index_storage_retirement`，记录DELETING/DELETED、物理名称、时间和原因。
- 清理中或已清理的IndexRun拒绝再次复用/发布；不创建空collection并沿用旧verified记录。
- 当前实现采用明确拒绝策略，不提供自动恢复旧collection功能。需要原样恢复时另行实施受控恢复；新的来源快照按正常构建路径执行。
- 清理保护所有profile的active/latest、全部Qdrant Alias、显式保留ID；只接受已终结运行。
- 存在任何未结束的发布请求时停止清理，包含“已构建待确认发布”。
- 维护期间暂停Worker和发布写操作。清理工具持有Platform写锁、分阶段知识库写锁；禁止其他外部运维工具同时操作Qdrant Alias。该锁实现迁MySQL时必须重写。
- 删除前持久化DELETING；网络错误或进程中断后重复相同清单可继续。删除后确认不存在再记录DELETED。
- 不删除IndexRun、来源清单、Chunk索引记录、聊天、Citation或原始文档。它们用于历史审计，不代表旧向量仍在线。
- CLI目前不清理未登记的孤儿collection，也不启用定时自动清理。

预览与执行命令（未来使用需重新审核ID）：

```powershell
& 'D:\3-anaconda\envs\py312\python.exe' scripts/retire-index-storage.py --runs 1 2 3 4 5 6 7 --keep 8 9
# --execute永久删除明确清单中的向量存储
& 'D:\3-anaconda\envs\py312\python.exe' scripts/retire-index-storage.py --runs 1 2 3 4 5 6 7 --keep 8 9 --execute
```

## 4. 2026-09-24实际清理结果

| IndexRun | Collection | 结果 |
|---|---|---|
| 1 | policy_platform_dense_cfeaea5224cb_4ffad605 | 已删除 |
| 2 | policy_platform_dense_dda15a723244_4ffad605 | 已删除 |
| 3 | policy_platform_dense_b621e8ff037a_4ffad605 | 已删除 |
| 4 | policy_platform_dense_06885286f72d_4ffad605 | 已删除 |
| 5 | policy_platform_dense_1df584cadaeb_4ffad605 | 已删除 |
| 6 | policy_platform_dense_a3e3b5e18e05_4ffad605 | 已删除 |
| 7 | policy_platform_dense_36ad02cd1b88_4ffad605 | 已删除 |
| 8 | policy_platform_dense_253687aa1917_4ffad605 | 保留 |
| 9 | policy_platform_dense_acd380ffb89f_4ffad605 | 保留、当前Alias目标 |

执行前核验无Worker进程、无未完成发布请求。执行后 `/collections` 只返回8、9；
`policy_platform_dense_active` 仍指向9。未制作向量快照备份，不能直接撤销删除；
保留关系数据库与原文不等于拥有已删除向量的备份。未声称Docker虚拟磁盘已自动缩小。

## 5. 下一阶段建议：双库统一SQLAlchemy + Alembic + MySQL

可行，推荐保持两个逻辑库（platform、knowledge），初期可运行于同一MySQL实例。
两个库分别拥有Engine/Session、模型Metadata、Alembic迁移目录和版本表；不用跨库外键、跨库ORM关系或隐含跨库事务。
跨库和Qdrant状态仍按现有显式版本、发布状态机和幂等校验协调。

实施顺序：

1. 固定两个库的实体、唯一约束、事务与服务边界；盘点全部SQLite依赖。
2. 将知识库repository改为SQLAlchemy Core/ORM，移除sqlite3、PRAGMA、executescript、运行时业务回填以及SQLite专用SQL。并非只替换连接字符串。
3. 同步建立知识库独立Alembic基线，检查Platform既有迁移在MySQL上的兼容性。自动生成的迁移必须人工审查。
4. 用全新MySQL双库执行迁移并验证上传、审核、发布、问答；保留旧本机环境用于对照，但不导入旧测试数据。
5. 验证连接池、事务隔离、行锁/任务领取、唯一约束、NULL语义、排序规则、JSON、日期时区和发布故障恢复；知识查询连接改为请求/任务会话而非长期裸连接。
6. 完成后用一个Compose编排Web、API、Worker、迁移任务、MySQL和Qdrant。API/Worker复用镜像但各自独立容器；模型服务继续可配置为外部地址。

Alembic应在MySQL正式切换之前或与repository改造同步完成，不能等业务切库后再补。
单Compose是多个服务的统一编排，不是把所有进程塞入一个容器。
改造难度中高，主要工作在知识库SQL和事务，不在Compose；全新数据降低搬迁风险，但不会消除代码改造。
千人注册量不等于千人并发，MySQL不能消除当前单线程问答Runtime和模型吞吐瓶颈，不提前承诺容量。

参考：[SQLAlchemy MySQL方言](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)、
[Alembic自动生成及人工审查要求](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)、
[Compose应用模型](https://docs.docker.com/compose/intro/compose-application-model/)。

## 6. 最小验证与未执行项

本轮测试集中在存储复用、清理保护/重入、发布失败保持旧快照，以及跨平台入口命令。
最终12项必要测试通过（含删除断连后DELETING持久化及重试），启动入口help检查通过。
实库只读核验：IndexRun仍为9条，1—7的来源记录仍为34条；退役标记均DELETED。
保留8为325 points、9为382 points，均green，active/latest指针均为9。
未运行全量测试、真实Embedding重建、压力测试、Linux容器构建或LibreOffice版式验收。

复测：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
$env:POLICY_TEST_RUNTIME_ROOT='D:\2-code\policy-platform\var\tests\docker-ready'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_index_storage_lifecycle.py tests/test_portable_startup.py tests/test_v2_governance.py::test_alias_failure_keeps_old_metadata_and_old_index_active -q -p no:cacheprovider -p no:tmpdir
```

正式打包阶段再执行Linux启动、卷持久化、迁移、DOCX渲染与Compose停止/重启验收；届时另行确认依赖安装和视觉检查。
