# 配套资料 M4 最小验证记录

> 文件说明：记录本轮实际执行结果与未覆盖范围；2026-09-26。

## 已执行

- 固定工具链：Node22.23.2、pnpm11.22.0、D:\3-anaconda\envs\py312\python.exe，无依赖安装。
- `backend`目录：`& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_materials.py -q`，23项通过。
- 根目录：`pnpm --filter @policy-platform/frontend typecheck`，通过。
- 根目录：`node frontend/tests/material-upload-http.test.mjs`，14项通过。
- 根目录：`pnpm --filter @policy-platform/frontend build`，通过，仍有500kB包体积提示。
- 根目录：`& 'D:\3-anaconda\envs\py312\python.exe' scripts/export-openapi.py`，契约已刷新。

新增测试覆盖已发布版本推荐、管理员新草稿隔离、下架隐藏、无权限403、纯类型词无推荐、原文偶然命中只允许独立搜索、资料自身标签主题匹配。
其余测试覆盖既有导入、图片、版本、批量操作与搜索，不运行全量后端测试。
沙箱最初阻止Node测试子进程和esbuild启动（EPERM）；测试改为直接执行测试文件，build经授权在沙箱外完成。不是代码构建错误。

## 未执行与手工验收

### UI精简补充

执行 `node frontend/tests/material-recommendation-ui.test.mjs`：3项通过，覆盖双类Tab切换、单类/空结果和引用折叠代码约束；typecheck通过。测试为隔离组件与静态约束验证，不等于浏览器实屏验收。
手工补测：8条引用默认3条、展开收起；正文E4等仍可定位；用“收到违规宴请的信访举报后怎么办理？有没有流程图和相关案例？”观察两个页签，切换不重新请求。

未运行真实模型问答、压力/性能/全量测试、浏览器实屏验收。没有新建/修改真实资料，没有数据库迁移和知识索引重建。
重启现有后端、刷新前端后，在ALL模式问“信访举报流程是什么”，检查答案下方资料卡片、图片放大、案例详情。
检查无关问题不出现图片、纯“有哪些流程图”不乱推荐、SELECTED模式不展示推荐。检查资料更新/下架后刷新聊天页面和详情的权限行为。
这些是用户手工体验验收，不宣称已验证真实问答效果。独立搜索和管理草稿入口应继续使用。

实现边界见[当前M4文档](../SUPPORTING_MATERIALS_M4.md)。
