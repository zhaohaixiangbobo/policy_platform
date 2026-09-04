# ADR-0001：Platform与Knowledge Engine保持独立工程

- 状态：已被 ADR-0002 取代
- 日期：2026-08-23

## 决策

`D:\2-code\policy-platform`负责产品前端、Platform API和独立业务数据库；
`D:\2-code\rag`继续负责解析、Chunk、Index、Qdrant、Context、Citation、Generator和RAG API。

浏览器只访问Platform API。Platform API通过版本化HTTP契约访问`127.0.0.1:8010`，不得直接写
Knowledge Engine核心SQLite、Qdrant或latest/active指针。

## 结果

- 两个工程可独立测试、升级和回滚；
- Platform业务数据写入独立`platform.db`；
- M0/M1不复制或修改现有知识流水线；
- Citation和问答能力在后续里程碑按已冻结契约联调。

## 后续决定

2026-08-29，本项目明确为单机测试工程，并决定以更少的运行步骤获得完整的文档处理能力。
当前实现见 [ADR-0002](ADR-0002-UNIFIED-KNOWLEDGE-MODULE.md)；本文件仅保留最初的决策背景。
