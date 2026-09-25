# 学习自测验证记录：2026-09-24

> 文件说明：记录learning_assessment_v1最小验证及人工验收边界。

## 已执行

- `test_learning_assessment.py` 16项专项测试及 `test_portable_startup.py` 1项：17项通过。
- 覆盖最大15题、范围校验、确定性评分、提交前答案/依据隐藏、CSRF、用户隔离、制度权限、关闭接口、重复任务、重复提交、超时失败、缓存清理、乐观锁、Worker失败保留旧结果、只读取已发布正文和保留子条款。
- 使用模型替身完成创建任务→Worker→获取题目→提交→100分及证据快照的完整HTTP链路。
- 前端 `pnpm typecheck` 通过。
- 本机Platform迁移：0010→0011_learning_assessment成功，head核验完成。
- 当时空库迁移检查失败于既有0006重复列，仅隔离测试库受影响；后续已冻结历史结构并完成重放验证，见[修复记录](WORKER_AND_MIGRATION_FIX_2026-09-24.md)。

## 自动化复测

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_learning_assessment.py tests/test_portable_startup.py -q -p no:cacheprovider -p no:tmpdir
Set-Location 'D:\2-code\policy-platform'
pnpm typecheck
```

## 真实模型最小冒烟

本次已执行1题冒烟：生成阶段向10.9.7.1:8000发起请求，90秒读取超时，未完成生成/审校，未写缓存或修改索引。
随后GET /v1/models返回200；服务可达，但生成超时原因尚未确认。真实出题质量和接口完整兼容性仍待复测，不能以替身测试代替模型验收。

使用只读正式制度，生成1题或3题，不写缓存和答题记录，不改索引。选择现行有效制度ID：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m tests.manual_learning_smoke --document-id 1 --questions 1
# 三题覆盖三种题型，后续由用户按需执行
& 'D:\3-anaconda\envs\py312\python.exe' -m tests.manual_learning_smoke --document-id 1 --questions 3
```

真实模型通过并不等于人工已确认题目无语义错误。模型服务响应时间和题目合格率未承诺SLA。

## 浏览器人工验收（待执行）

1. 开启功能并重启API/学习Worker；刷新页面确认两个入口均可见。
2. 选择制度，全文生成；指定章节再生成，检查题目均来自所选范围。
3. 分别验证单选、多选、判断；网络面板确认提交前响应没有correct_answer/explanation/source_text_snapshot。
4. 暂存并刷新，检查作答恢复；提交未答题时出现确认；交卷后正确答案、解析和原文可查看。
5. 多选少选/多选不得分；仅看错题、弱项定位与原文跳转可用。
6. 新任务失败保留旧结果，新任务成功覆盖；多标签页旧检测提交应提示冲突。
7. 制度更新后本次快照不变，页面提示版本变化；不将旧节点定位到新正文。
8. 关闭开关并重启，菜单和按钮隐藏，直接接口404，普通问答和制度库仍可用。

未执行全量测试、15题批量真实生成、压力测试、24小时等待测试、Linux/Compose部署或Chrome89实机验收。
