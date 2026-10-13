# 配套资料库M1—M3验证记录

> 文件说明：记录已执行最小验证及尚待用户执行的真实界面验收。

## 已执行

最终最小后端验证：12项通过（17.80秒）；前端HTTP封装3项通过；typecheck通过，最终build通过（28.91秒）。

- `tests/test_materials.py`：隔离内存数据库和var/tests独立图片目录。覆盖七列导入、原文逐字一致、批内及跨批重复、确认幂等、错误行/公式、行数限制/XML实体拒绝、日期校验、发布必填、版本隔离、历史版本、无改动保存、版本冲突、批量回滚、搜索/分页/筛选/标题排序、未开放类型拒绝、权限/CSRF、预览所有者/过期、真实图片格式与重复、附件越权。
- `tests/test_migration_replay.py`：隔离空库和增量重放；最终ORM对比；历史迁移独立性；仅隔离库执行降级重放。
- 前端typecheck与生产build；build既有500KB分块告警保留，不做无关打包改造。
- 导出 `docs/api/openapi.json`。
- 本机Platform数据库执行0011→0012加表迁移；不导入、发布或修改用户资料，不操作知识库或Qdrant。

复测命令：

```powershell
Set-Location D:\2-code\policy-platform\backend
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_materials.py tests/test_migration_replay.py -p no:cacheprovider -p no:tmpdir -o addopts='' -q
Set-Location D:\2-code\policy-platform
node frontend/tests/material-upload-http.test.mjs
pnpm typecheck
pnpm --filter @policy-platform/frontend build
```

## 浏览器待验收

### 2026-09-26：导入后列表空白修复

只读核对本机存在6条案例草稿、1条图片草稿及1条已确认导入批次，数据已入库。
根因：前端将未选择日期序列化为date_from=&date_to=，FastAPI日期校验返回两个422错误；HTTP封装将detail对象数组直接传入Error，显示为[object Object],[object Object]。
修复：列表请求仅省略未选择的日期参数，保留state空值代表全部状态；HTTP封装统一提取业务错误和FastAPI校验数组的字段/消息，未知对象用稳定提示，不显示input原始值。
已执行7项前端HTTP/参数回归、1项隔离后端日期契约回归、typecheck及build（44.01秒），均通过。无需重导、迁移或发布真实资料；筛选“草稿”可查看导入内容。仍未完成浏览器实屏验收。

浏览器工具返回空浏览器清单和连接错误，因此未宣称实屏、缩放或点击交互已通过。
重启后端、刷新登录会话后访问 `/materials`，按1920/1440/1366桌面宽度核对：

1. 顶部导航显示配套资料库；普通用户没有上传/导入/管理按钮。
2. 使用下载的模板填两条人工核对的测试案例，预览、确认导入，默认进入草稿。
3. 重复导入同一文件，提示重复且不新增；有公式/缺失原文时禁止确认。
4. 管理员补齐来源后发布，普通用户能搜索原文关键词、筛选和查看详情。
5. 修改发布资料标题，保存草稿；普通用户仍看到旧标题；发布新修订后切换。
6. 图片上传后可放大、拖动、原尺寸查看；无自动解析出的虚构文字。
7. 下架后普通用户详情与图片地址不可用；管理员能看历史内容。
8. 搜索与分页后选择项清空，批量发布/下架结果刷新；无假数据卡片。

未执行：24条真实案例导入、真实资料发布、模型调用、视觉模型、检索质量评测、压力测试和全量后端测试。所有这类数据操作需用户按实际资料确认后进行。
