# Docker + LibreOffice授权字体适配

## 当前部署状态（2026-10-12，优先于下文历史记录）

用户已构建正式镜像，P4 已应用 Knowledge `k0004_render_metadata`，API/两类 Worker 已使用
`sha256:2afc423ad3169024d1880d0f88b339a6169fb10c2e26007edbe4350c696cab5a` 并启用只读字体挂载。
版本 26.8.1.1、字体门禁、两类 Worker 启动及 8088 代理 `/api/v1/health/ready` 返回 ok 已核验。
字体覆盖显式指定 API command，防止覆盖 entrypoint 后丢失镜像 CMD；2 项字体部署回归通过。
6 份历史制度、6 条旧 PDF 校验值及 active IndexRun 1 未变，旧转换 JSON 均保留 NULL。
迁移前 Knowledge 自定义格式备份位于 `var/backups/uno-k0004-20261012/knowledge.dump`；
这是本机单库迁移前备份，不等同于全系统灾备或恢复演练。Platform 未迁移，未发布索引。
后续上传到 Citation 真实闭环及 ARM64 实机验收仍待执行。

文件说明：2026-10-11，本地amd64验证。字体只读挂载，不进Git或镜像。字体匹配通过；Word版式一致性尚未通过，不能据此放行P4/P5。

## 使用方式与边界

宿主目录由部署者提供，当前为`D:\docker-fonts`。不修改Dockerfile安装字体，镜像继续提供fontconfig、LibreOffice及Noto基础字体。新增`deploy/compose.fonts.yaml`覆盖配置对API、两类Worker和初始化容器一致挂载：

- 授权字体目录 → `/usr/local/share/fonts/policy`，只读。
- `deploy/fonts/99-policy-fonts.conf` → fontconfig配置，只读。
- 启动脚本刷新可写`/tmp/policy-font-cache`，然后原样exec服务命令，不改变业务参数。

```powershell
cd D:\2-code\policy-platform
$env:POLICY_FONT_DIR='D:/docker-fonts'
docker compose -f compose.yaml -f deploy/compose.fonts.yaml config --quiet
# 下面是后续启用命令；本轮仅隔离试转，未对运行中的业务服务启用字体覆盖。
# 先确认没有入库/发布任务，再在维护窗口执行。
docker compose -f compose.yaml -f deploy/compose.fonts.yaml up -d api ingestion-worker learning-worker
```

启用后所有up/recreate/run命令须持续使用相同`-f`参数，避免下一次普通up撤掉字体。生产替换宿主路径，沿用只读挂载；字体文件在部署目录外受控提供。`create_host_path:false`防止缺目录时静默创建；`.gitignore`与`.dockerignore`排除TTF/TTC/OTF，shell脚本固定LF。字体授权由用户确认，未检查或更改授权范围。

本轮仅新增部署配置和测试，不修改解析器、入库状态机、PDF转换函数或原DOCX，不更新现有ParseRun及字体指纹，不切换Alias，不重新发布。已知`font_environment_hash()`目前仅记录OS信息的问题另行保留，不能认为它已能追踪字体包版本。

## 实际匹配结果

| 请求字体                     | 实际家族 / 文件                                             | 结论                         |
| ---------------------------- | ----------------------------------------------------------- | ---------------------------- |
| 宋体                         | SimSun / simsun.ttc                                         | 匹配                         |
| 黑体                         | SimHei / simhei.ttf                                         | 匹配                         |
| 仿宋                         | FangSong / simfang.ttf                                      | 匹配                         |
| 仿宋_GB2312、FangSong_GB2312 | FangSong_GB2312 / fangsong_GB2312.ttf                       | 匹配，未混同普通仿宋         |
| 楷体                         | KaiTi / simkai.ttf                                          | 匹配                         |
| 楷体_GB2312、KaiTi_GB2312    | KaiTi / simkai.ttf                                          | 显式替代，不等于原GB2312字体 |
| 方正小标宋简体               | FZXiaoBiaoSong-B05S / FZXBSJW.TTF                           | 匹配                         |
| Times New Roman              | Times New Roman / times.ttf（另含timesbd、timesi、timesbi） | 匹配，2026-10-12补齐         |

使用UID10001、无网络临时容器执行fc-cache及fc-match，9个请求均命中预期文件。启动不要求写字体目录或以root运行。

## 代表性文件与视觉结果

对已发布的accepted DOCX作只读样本，业务知识卷只读挂载，试转文件位于`var/font-review/adapted-20261011`。每份保留原字节哈希；复用现有`render_docx_to_pdf(..., engine='libreoffice')`，未修改原文件。Word16.0以只读方式导出同一accepted DOCX作本机基准；这不是把DOCX缓存页数字段当作页数。

| 样本                      | LibreOffice7.4.7.2 | Word16.0 | 结果                 |
| ------------------------- | ------------------ | -------- | -------------------- |
| 制度1《监督执纪工作规则》 | 27页               | 26页     | 分页不一致           |
| 制度3《监督执纪工作指引》 | 24页               | 16页     | 分页及行距明显不一致 |

`pdffonts`实测两份PDF均嵌入FZXBSJW--GB1-0、FangSong_GB2312、SimHei；第二份还嵌入KaiTi，emb/sub/uni均为yes。西文仍有DejaVuSerif替代，宿主字体目录未提供Times New Roman、Calibri、Arial等。

2026-10-12补充：用户确认Times New Roman为必需字体，已将本机`C:\Windows\Fonts`的times.ttf、timesbd.ttf、timesi.ttf、timesbi.ttf复制到`D:\docker-fonts`（授权与其他字体相同，由用户确认），不改fontconfig、不进镜像。在实验镜像LibreOffice 26.8.1.1中隔离复测：两份样本PDF的页码字体由替代字体变为TimesNewRomanPSMT（与Word参考PDF同名），页数和全文文本不变，像素差异仅在页脚页码处。注意，`fc-match`不能代表LibreOffice实际使用的字体：缺TNR时7.4实际用DejaVuSerif，26.8.1.1实际用安装包自带的LiberationSerif，而fc-match都报DejaVu Serif。所以应以PDF实际嵌入的字体为准。Calibri、Arial在样本中未实际使用，暂未补齐。运行中的P4业务容器未挂载字体目录，本次补齐不影响它们；以后通过`compose.fonts.yaml`启用时自动生效。详见`var/font-review/compat-20261011/REPORT.md`第8.5节。

视觉抽样查看两份首页，以及第二份第3页的楷体段落，并与Word截图对照：标题已恢复小标宋形态，正文已恢复仿宋，未见原先Noto JP替代字形；但标题行间距、正文换行及页边界不同。程序全页文本抽取比较未发现同页完全一致的页面（仅作为分页差异信号，不等于内容丢失）。没有宣称全部页面视觉核查完成。

样本1正文相邻基线中位数两引擎约31.2pt，但行内折行及标题垂直位置不同。样本2Word约21pt，LibreOffice约31.2pt；原XML有`spacing line=420 lineRule=exact`（21pt）及`docGrid linePitch=312`（15.6pt）、snapToGrid设置。31.2pt与网格双倍间距一致，是后续兼容性排查线索，不将其未经隔离实验断言为唯一根因。

因此：字体适配成立，严格Word等版式尚不成立。不可覆盖旧PDF或继续使用旧页码证据声称相同版式。需单独决定是否开展LibreOffice网格/兼容性适配，以及是否补齐西文字体；当前不改业务逻辑。

## 测试与复查入口

- `backend/tests/test_container_fonts.py`：2项最小测试通过，校验映射/只读挂载边界/字体排除与LF。
- `backend/tests/manual_container_fonts.py`：隔离容器真实执行2份试转、9个字体匹配，并生成`font-report.json`。
- `backend/tests/manual_font_layout_compare.py`：本机已有PyMuPDF执行两份Word/LO PDF比较，输出`layout-comparison.json`及抽样PNG。它是人工验收工具，不是后端运行依赖。
- pdffonts由用户手动安装至当前API诊断容器，试转PDF临时复制至`/tmp/font-review-sample-1.pdf`和`...-2.pdf`；不属于镜像新运行依赖。
- 未执行全量/压力/ARM64验收；未重转6份正式PDF。2026-10-12按用户要求向`D:\docker-fonts`新增4个Times New Roman文件，未改动原有字体。

所有输出为本地核对资料，禁止将其中内容作为已发布业务版本。旧PDF与原文保留。
# 2026-10-12：UNO 业务接入状态

代码已接入，尚未重建正式业务镜像或执行数据库迁移；当前运行中的容器保持原状。
转换配置 `lo-uno-compress-v1`；正式 Dockerfile 固定 LibreOffice 26.8.1.1，按 amd64/arm64 校验安装包。
字体通过 `deploy/compose.fonts.yaml` 只读挂载，源码和镜像均不包含授权字体。

## 当前转换规则

- 容器内 `POLICY_LIBREOFFICE_UNO_PYTHON=/opt/libreoffice26.8/program/python` 启用独立 UNO 子进程。
- `POLICY_DOCX_RENDER_TIMEOUT_SECONDS=180` 控制启动、加载和导出的整体期限；Linux 超时清理整个进程组。
- 原文声明 `compressPunctuation` 时设置压缩为 1，其余声明保持导入值；不修改 DOCX，不经过 FODT。
- 每次使用独立临时目录、配置和管道；禁用宏和外部链接更新；有效且有页 PDF 通过同文件系统硬链接原子保存。
- PDF 名称加入 ParseRun ID；目标已存在则拒绝覆盖。转换失败保留原流程的待复核问题，不自动批准。
- 转换前检查宋体、黑体、仿宋、仿宋_GB2312、楷体、楷体_GB2312、方正小标宋及 Times New Roman。
  楷体_GB2312 允许 KaiTi；错误匹配阻止本次转换，不阻止 API 阅读和问答。
- 每次重新计算字体内容与实际加载 fontconfig 内容 SHA-256，不缓存外置字体状态；无授权字体挂载的新镜像不能执行 DOCX 转换。
- Windows 未配置 UNO 路径时保留原有引擎选择，Linux UNO 字体门禁不用于 Windows Word。

## 结构迁移与启用

Knowledge 新 head 为 `k0004_render_metadata`，只增加 nullable Text 列 `parse_run.render_metadata_json`，不回填旧数据。
该 JSON 保存 profile、声明、压缩前后值和字体环境。`render_engine=libreoffice_uno` 保持单一含义；
`render_engine_version` 保存完整版本；`font_environment_hash=fe2:<完整SHA256>` 标识新算法。
Platform head 不变。正式重建会安装固定的 LO 系统依赖和现有 requirements，须由用户手动执行。

在维护窗口等待 Worker 完成当前任务后停止应用，按以下顺序启用（不要执行 down -v）：

```powershell
Set-Location 'D:\2-code\policy-platform'
$env:POLICY_FONT_DIR='D:\docker-fonts'
docker compose --progress plain build api
docker compose --profile tools run --rm migrate python scripts/migrate-knowledge-pg.py --env-file /run/config/migration.env
# 核对目标数据库、current/head、待执行列及当次指纹，然后执行：
docker compose --profile tools run --rm migrate python scripts/migrate-knowledge-pg.py --env-file /run/config/migration.env --execute-plan '<当次指纹>'
docker compose -f compose.yaml -f deploy/compose.fonts.yaml up -d api ingestion-worker learning-worker
```

不要初始化/重置现有管理员、数据库或 Qdrant。迁移后旧镜像回退需先评估严格 revision 检查，不能直接降级启动。
首次镜像构建预计 10—30 分钟，受约 210MB 安装包及依赖网络影响，BuildKit 输出构建进度。

## 验证边界

最小测试命令（不访问数据库或模型）：

```powershell
Set-Location 'D:\2-code\policy-platform\backend'
& 'D:\3-anaconda\envs\py312\python.exe' -m pytest tests/test_render_uno.py tests/test_container_fonts.py tests/test_compose_p4.py -q -p no:cacheprovider
```

已在现有实验镜像中运行新业务 UNO 子程序，字体门禁通过，样本声明压缩从 0 变为 1，产生 PDF。
2026-10-12：上述 3 个测试文件共 19 项通过；Alembic 只读 heads 检查为单一 k0004_render_metadata。
首次沙箱测试因 Windows 临时目录权限失败，授权沙箱外重跑通过；未运行全量测试或数据库迁移。
尚待正式业务镜像重建、受控迁移、上传至 Citation 闭环及 UOS ARM64 实机验收；不据此宣称 P4/P5 放行。
本轮没有新增视觉版式验收，版式依据用户已有隔离报告；后续需要视觉核对时单独确认。

