# 学习检测：提交后辅助资料

> 2026-10-11：共用检索升级至 [material_search_v3](SUPPORTING_MATERIALS_V3.md)。原文不独立触发推荐，出题/评分/访问边界未变。

> 文件说明：learning_materials_v1，2026-10-09适配 supporting_materials_v2 / material_search_v2，出题评分不变。

## 界面

2026-09-27入口视觉补充：浅蓝底、蓝色边框与文字，流程/案例图标及hover/focus状态，替代不明显的纯文本按钮；检索规则不变。

提交后，在“查看制度依据”同一行并列显示“相关流程图（1）”“相关案例（1）”。无结果隐藏，各类最多1条，左侧Space允许换行。右侧上一题/下一题保持原行为。
点击打开资料详情抽屉，案例显示人员与问题信息、处理结果（空值“未公布”）、案情描述；图片支持放大。辅助资料不作为本题出题或评分依据。
切题使用检测ID与题目ID作为组件key，清空旧推荐/抽屉；请求失败隐藏，不影响结果或切题。不新增缓存，返回题目重新查询当前发布状态。

## 接口

GET `/api/v1/learning-assessments/{assessment_id}/questions/{question_id}/materials`

要求学习开关启用、knowledge.document.read与material.read权限；沿用本人槽位及制度权限检查。
检测已过期、被替换、属于其他用户或题目不存在返回404；未提交409；权限不足403；模块关闭404。
服务端从冻结题目取knowledge_point和source_text_snapshot，按中文标点分短句，复用material_search_v2；knowledge_point中的“正文条款 N”“第X条”等编号先剔除，只保留条款标题，避免占用匹配词名额。案情原文命中不能独立触发推荐。不从前端接收自由查询，不用错误选项、用户答案、模型解析或整份制度标题扩大主题。
推荐仍仅已发布资料，按既有评分排序后每类取1条。返回items、search_version和reference_only，详情和附件继续鉴权。
没有额外模型调用，不改题目生成、评分、数据结构、24小时规则和制度原文快照。

## 限制

推荐是主题参考，不证明资料为当前制度官方附件。条款快照中泛化内容可能无法命中；“认真组织学习”不应仅凭制度大标题推荐信访流程。
匹配仍使用统一服务最多10个检索项，长条款后部主题可能漏检，后续以样本评估优化，不放宽为同领域全部推荐。
配套资料取当前发布修订，不是生成题目时的快照；资料更新后详情可能提示重新查询。

## 验证

最小命令（backend目录）：
`& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_learning_assessment.py -k 'learning_material_access or program_scoring or answer_projection' -q`

3项通过：访问限制与取材、原评分、提交前答案投影。无真实数据库、模型和索引修改。
前端typecheck/build通过（保留现有大包体积警告）；`node frontend/tests/material-recommendation-ui.test.mjs` 5项通过，含学习并列入口及问答展示回归。OpenAPI已导出；浏览器实屏、真实模型、压力和全量测试未执行。
手工：完成检测后切换到信访相关题，检查并列入口、详情、大图、切题与窄屏换行；无关题无推荐。模块关闭/检测过期后入口不可通过API获取。
