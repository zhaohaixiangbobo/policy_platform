# 统一工作平台门户

## 2026-10-12：运行时外部入口（portal_runtime_config_v1）

部署已启用：实际8088配置接口200、Cache-Control:no-store；外部入口均保留禁用默认值。之后修改宿主JSON刷新即可；真实外站跳转/SSO在提供地址后验证，本次没有访问外站。

五个外部模块支持宿主文件配置，无新增数据库或后台接口。首次需要重建web镜像并重建web容器使目录挂载生效。
以后修改 `deploy/portal/portal-config.json` 并刷新工作台即可，无需重建镜像、重启Nginx。
本机Vite开发修改 `frontend/public/runtime/portal-config.json`；两文件分别对应部署与开发环境。

配置示例（其余模块保留现有配置）：

```json
{
  "version": 1,
  "modules": {
    "discipline": { "enabled": true, "url": "https://discipline.example/", "openMode": "newTab" }
  }
}
```

模块ID：`meetings`会议、`discipline`纪检、`inspection`巡察、`supervision`穿透监管、`documents`文书。
`enabled=false`、空地址或未配置模块均保留建设中页面；不是隐藏卡片。制度入口不能由此配置覆盖。
`openMode`允许newTab（默认）或sameTab。名称、图标、顺序及门户总开关仍属于构建配置。
只允许完整HTTP/HTTPS地址，拒绝地址内账号密码、脚本协议和协议相对地址；外链不附加本平台token，使用noopener/noreferrer。
运行配置通过 `/runtime/portal-config.json` 无缓存读取，超时5秒或校验错误时提示并保持占位；不会沿用失效的外部地址。
这是浏览器可读取的公开导航配置，不得存储密钥、带令牌链接或其他秘密。外部系统权限及4A/SSO须另行对接。
运维配置由受控宿主文件管理，不放开浏览器写权限；目录挂载支持原子替换文件，不将宿主字体或业务数据打进镜像。

当前同时包含P4后端连接池更新，本次用户手动构建：

```powershell
cd D:\2-code\policy-platform
docker compose --progress plain build api web
```

完成后等待任务空闲，再沿用字体和运维覆盖启动：

```powershell
$env:POLICY_FONT_DIR='D:/docker-fonts'
docker compose -f compose.yaml -f deploy/compose.fonts.yaml -f deploy/compose.operations.yaml up -d --wait --wait-timeout 60
```

没有依赖变更、数据库迁移或权限模型变更。门户8项最小测试通过；完整浏览器外链跳转等待新镜像部署后检查，不访问尚未配置的外部系统。

以下保留原门户路由及认证说明；原“所有入口写在config.ts”仅指默认站内路径和视觉文案。

> 文件说明：platform_portal_v1 的路由、认证兼容、开关与验收说明。2026-10-10；代码已实现，完整登录态及桌面实屏验收待完成。

## 范围与路由

平台名称：天津烟草行业内部监督贯通协同工作平台。现有制度业务仍在原路径运行，不迁移数据库、不调整业务 API、不新增账号体系。

| 路径 | 门户开启时 |
|---|---|
| `/login` | 新平台登录，默认进入 `/portal` |
| `/portal/login` | 原制度登录界面，默认进入 `/` |
| `/portal` | 已认证用户的六模块工作台 |
| `/` | 原制度首页 |
| `/portal/modules/:moduleId` | 五个模块建设中页面，须登录 |

模块文案统一维护于 `frontend/src/portal/config.ts`，顺序为制度管理、会议管理、纪检工作流程管控、巡察工作流程管控、业务穿透式监管、文书智能生成。除制度模块外不实现业务功能。

门户背景位于 `frontend/public/portal-background.png`，来自用户提供的城市天际线图片；标题、说明、图标和箭头由组件渲染。门户不显示公司 Logo、用户名或复杂菜单，仅保留退出图标。制度原有导航保持，普通页面、问答页和管理页顶部增加返回工作台及账号入口。

## 认证与权限

- 复用 AuthProvider 和原 `/api/v1/auth` 服务；两个登录页共用用户、角色与 HttpOnly 会话 Cookie，不新增 Token 转换。
- 原会话 Cookie 路径为 `/`；同源下可自然跨前端路由共享。CSRF 机制与后端权限检查保持。
- 直接访问受保护页面时保存站内路径、查询参数及锚点；登录和强制改密后回跳。回跳值经过站内路径校验，排除外站及登录循环。
- 门户要求已认证；制度模块保留原 API 权限，前端使用 `knowledge.document.read` 显示模块无权限提示，后台继续要求 `admin.access`。
- 接口返回 401 时清理前端登录状态，由路由守卫转到登录页；登录失败的 401 不触发全局会话事件。403 仍表示权限不足。
- 返回工作台只跳转路由，不清除会话；退出调用原后端登出服务。
- 原先直接收藏 `/login` 的用户会看到新平台登录，旧界面现为 `/portal/login`。这是已确认的入口调整。

## 部署与回滚

现有 Vite `/api` 代理保持不变。生产服务器必须将前端 `/portal`、`/portal/login` 和模块深链接回落到 SPA 的 `index.html`；API 请求仍按原代理处理。此轮未修改生产服务器配置。

开关属于前端构建配置：在 `frontend/.env.local` 设置 `VITE_PORTAL_ENABLED=false`，开发服务重启、生产重新构建部署后生效。关闭后 `/login` 使用原制度登录，默认进入原 `/admin/jobs`，门户与占位路由不注册，返回工作台入口隐藏；`/` 和所有制度业务路由不变。重新设为 `true` 即恢复。项目根目录的后端环境文件不会自动代替 Vite 前端环境文件。

## 验证记录与手工验收

已通过：前端 typecheck、production build、`node frontend/tests/portal.test.mjs` 的 4 项最小测试（模块配置、回跳安全、认证权限守卫、路由与会话适配）。构建仍有大 chunk 提示，不影响构建成功。

浏览器已确认新平台登录和原制度登录页面能够打开；1440×900 下新登录页 DOM 无横向溢出。以下仍需完整手工验收，不以单元测试替代：

1. 未登录访问 `/portal`、制度详情和后台：应登录回跳；未登录 API 仍应拒绝。
2. 分别从两个登录入口登录，默认目标分别为门户与制度首页；必须改密账号保持正确回跳。
3. 门户进入制度、返回门户、刷新页面，均保留会话；五个占位页及未知模块提示正常。
4. USER / REVIEWER / ADMIN 的原业务权限、后台入口保持；退出及会话过期后不能继续访问受保护页面。
5. 在 1920×1080、1440×900、1366×768 核对三列两行卡片、标题、建筑遮挡及顶部导航；暂未完成登录后门户的三尺寸实屏验收。
6. 关闭开关并重启或重构建后验证原登录和业务可用。

最小复验命令（项目根目录）：

```powershell
node frontend/tests/portal.test.mjs
pnpm --filter @policy-platform/frontend typecheck
pnpm --filter @policy-platform/frontend build
```

未运行全量后端测试、压力测试或真实业务写入测试；本次不修改制度、索引、资料及学习数据。
