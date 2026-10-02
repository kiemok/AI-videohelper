# 项目开发进度记录

> 项目：**基于B站与抖音的多源数据融合及AI驱动的内容创作决策系统**
> 当前版本：**v0.5.0（常驻右侧 AI 咨询面板 + 浅黑/浅白/浅蓝主题）**
> 更新日期：2026-10-02
> 维护方式：每完成一项任务即更新本文件（状态、验证结果、遗留问题）

---

## 一、总体状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 桌面端框架 PySide6 | ✅ 已完成 | 顶部状态条 + 侧栏导航（7 页）+ 底部状态栏 + 深色主题 |
| 界面设计系统 | ✅ 已完成 | 落地 Deep Telemetry & Intelligence Workspace（设计令牌 + QSS + 自绘组件） |
| **外观主题** | ✅ 已完成 | 浅黑 / 浅白 / 浅蓝三套令牌；顶栏与设置页可切换，即时生效并持久化 |
| **常驻 AI 咨询面板** | ✅ 已完成 | 固定在工作区右侧，任意页面都能提问；与「AI 决策助手」页共享同一会话 |
| 配置管理 | ✅ 已完成 | 本地 `config/settings.json`，API Key 只在用户本机 |
| 数据存储（SQLAlchemy 统一模型） | ✅ 已完成 | 14 张表；默认 SQLite，可按行切换 MySQL |
| **数据来源（Git 数据仓库）** | ✅ 已完成 | `app/datasource`：git clone/pull、ZIP 归档、仅本地目录；软件内**不含爬取** |
| 数据融合 | ✅ 已完成 | 标准 CSV 与平台原始 JSON/JSONL → 统一模型映射 + 幂等入库 |
| 本地分析 | ✅ 已完成 | 互动率/增长率/传播健康度/拐点检测/评论情感/热词/转化漏斗 |
| AI 解读与建议 | ✅ 已完成 | DeepSeek/通义千问（OpenAI 兼容）+ 无 Key 本地回退 |
| 交互问答 | ✅ 已完成 | 问题 + 数据上下文 → 回答，历史落库 |
| 可视化看板 | ✅ 已完成 | 趋势图（含拐点标记）/漏斗/环形图/迷你趋势条/热词标签云 |
| **视频创作咨询（扩展方向一）** | 🟡 初步框架可用 | `app/consulting/` + 咨询页：分类咨询、要点提取、历史落库 |
| **AI 短剧（扩展方向二）** | 🟡 初步框架可用 | `app/drama/` + 短剧页：大纲→剧本→分镜三级生成，多模态接口预留 |
| 任务调度（APScheduler） | ✅ 已完成（仅触发分析） | 每日定时执行分析；接入爬虫后改为「先采集再分析」 |
| MCP / 文生图 / 文生视频 | ⏸ 已预留 | 配置文件、数据字段（image_prompt/video_prompt）与模块位置已留出 |
| 自检脚本 | ✅ 已完成 | `scripts/smoke_check.py`（无界面链路）、`scripts/gui_smoke.py`（界面冒烟+截图） |

---

## 二、已完成功能明细

### 1. 项目骨架与依赖

- `requirements.txt`：PySide6、SQLAlchemy、PyMySQL、pandas、numpy、requests、APScheduler、python-dateutil。
- 安装统一使用国内镜像：
  - 清华：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
  - 阿里云：`pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`
- `.gitignore` 已排除：`.venv/`、`config/settings.json`（含 API Key）、`data/`、`logs/`、`.idea/`、`.reasonix/`。

### 2. 配置管理（`app/config.py`）

- `AppSettings` / `LLMSettings` 数据类，JSON 本地持久化，缺失/多余字段容错。
- 服务商预设：DeepSeek（`https://api.deepseek.com/v1`，`deepseek-chat`）、
  通义千问（`https://dashscope.aliyuncs.com/compatible-mode/v1`，`qwen-plus`）、自定义 OpenAI 兼容。
- 环境变量 `CCD_CONFIG_PATH` 可指定配置文件位置。
- **API Key 处理**：只写入本地 `config/settings.json`，不入库、不入 Git；设置页用密码框输入，
  并支持「显示/隐藏」与「测试大模型连接」。

### 3. 数据存储层（`app/db/`）

统一数据模型（`models.py`）：

| 表 | 用途 |
| --- | --- |
| `account` | 创作者账号（B站 UP主 / 抖音作者），统一 `platform + platform_account_id` 唯一 |
| `video` | 作品（视频/图文），含标题、标签、时长、发布时间、话题来源 |
| `video_metric_snapshot` | 每日累计指标快照（播放/点赞/评论/分享/收藏/弹幕/涨粉 + 平台原始字段留档） |
| `comment` | 评论，含情感得分与标签 |
| `analysis_result` | 本地分析结果（按 日期+平台+口径 覆盖保存） |
| `ai_report` | 大模型/本地规则生成的解读文案与建议 |
| `chat_session` / `chat_message` | 问答会话与消息历史 |
| `collect_task` | 采集任务状态（爬虫阶段启用） |

- `base.py`：按 `db_url` 缓存引擎；SQLite 打开 WAL 与外键；MySQL 使用 `pool_pre_ping`。
- `repository.py`：幂等 upsert（支持复用外部会话以批量导入）、聚合查询、数据总览、清空。

### 4. 采集与融合（`app/collect/`）

- `base.py`：`BaseCollector`（`fetch()` 契约）、`CollectTarget`、`RawBatch`、`register_collector` 注册表。
- `bilibili.py` / `douyin.py`：**骨架**，`fetch()` 抛 `NotImplementedError`；
  文件头写明后续接入所需的接口端点、签名字段与反爬注意事项。
- `sample_source.py`：离线样例数据源（确定性随机种子），生成 4 个账号 × 6 个作品 × N 天快照 + 中文评论，
  指标曲线呈「发布后 1~3 天高峰 + 长尾衰减」，部分作品含爆款突增；可导出 CSV 供人工替换。
- `fusion.py`：融合规则集中在此——账号/作品/指标/评论四类 `normalize_*`，
  兼容 Unix 秒/毫秒时间戳、`stat`/`statistics` 两种嵌套、标签的多种分隔形式，原始字段经裁剪后留档。
- `pipeline.py`：`run_collect`（走采集器并记录任务）、`sync_sample_data`（一键样例）、
  `import_csv_dir`（CSV 导回）、`archive_snapshots_csv`（历史归档到 `data/archive/`）。

### 5. 本地分析（`app/analysis/`）

- `metrics.py`：当日增量、互动率、累计互动率、收藏率、分享率、评论率、日增长率、**传播健康度**（0~100）、
  每日时序聚合、双平台对比（当日 + 近 7 日）、作品榜、账号榜、发布时段分布、KPI 汇总。
- `anomaly.py`：滚动 z-score（窗口 7，原始序列与平滑序列取较大值）+ 增长转负规则，
  输出 `spike` / `drop` / `recover` / `fade` 四类拐点，另检测整体异常日。
- `sentiment.py`：中文情感词典（正向/负向 + 强度）+ 否定词与程度副词修饰，
  最长匹配 + 区间占用，`tanh` 压缩到 [-1,1]，阈值 ±0.15 划分正/中/负；输出分布与代表性评论。
- `keywords.py`：领域词表最长匹配 + n-gram 兜底（停用词过滤、包含关系与字符二元组重叠去碎片）。
- `service.py`：`run_daily_analysis()` 一次串起所有指标并落库；自动对未评分评论做情感打分。

### 6. AI 解读与问答（`app/ai/`）

- `client.py`：OpenAI 兼容 `/chat/completions` 客户端（requests 实现，超时/重试/错误归一 + 连接测试）。
- `prompts.py`：
  - `metrics_to_context()`：把分析结果压缩成结构化中文上下文（大模型与本地规则共用）；
  - 四类报告提示词模板（数据简报 / 选题建议 / 标题优化 / 发布时间建议）与问答模板；
  - **本地规则回退**：无 Key 或调用失败时，用同一份上下文生成可读的解读、建议与问答答案，并显式标注来源。
- `insights.py`：`InsightService` 统一入口，结果落库（`ai_report`）、问答写入会话历史。

### 7. 桌面端界面（`app/ui/`）

- `main_window.py`：左侧导航（看板/数据管理/分析详情/AI 助手/设置）+ 页面栈 + 菜单（数据、运行、帮助）+ 状态栏。
- `context.py`：`AppContext` 作为共享中枢（配置、数据库、分析结果、后台任务、Qt 信号，
  含 `metrics_updated` / `data_changed` / `settings_changed` / `report_updated` / `status_message`）。
- `workers.py`：`QThreadPool` + `QRunnable` 封装，耗时任务不阻塞界面。
- `pages/dashboard.py`：KPI 卡片、近 30 天双轴趋势图、双平台对比柱状图、作品 TOP 榜、最近 AI 简报回显。
- `pages/data_page.py`：样例数据同步（可选天数）、CSV 导入、快照归档、清空数据、作品/账号列表、采集器状态。
- `pages/analysis_page.py`：指标明细、整体异常日、作品级拐点表、情感环形图、代表性评论、热词词云。
- `pages/ai_page.py`：四类建议一键生成 + 数据问答（Markdown 渲染），可勾选「仅本地规则生成」。
- `pages/settings_page.py`：存储/大模型/任务调度/采集目标四组设置 + 连接测试 + 定时任务状态显示。
- `widgets/`：KPI 卡片、分区卡片、QtCharts 图表（趋势/对比/环形）、QPainter 自绘词云、dict 表格模型。
- `theme.py`：深色主题 QSS（统一配色常量，B站粉 / 抖音青 区分平台）。

### 8. 任务调度与日志

- `core/scheduler.py`：APScheduler 后台调度器，`CronTrigger` 每日固定时间触发，
  通过 Qt 信号回到主线程；界面正在忙时自动跳过本次执行。
- `core/logging_setup.py`：控制台 + 滚动文件（`logs/app.log`）+ 告警通道（`logs/alerts.log`，ERROR 及以上）。

---

## 三、验证记录（2026-09-28 实测）

### 1. 后端全链路自检

```powershell
.\.venv\Scripts\python.exe scripts\smoke_check.py
```

结果（关键输出）：

- 数据导入：账号 4｜作品 24｜指标快照 388~435｜评论 242~257｜平台分布 bilibili/douyin 各 14
- 数据总览：分析日期区间 2026-08-30 ~ 2026-09-28
- 分析结果示例：`当日新增播放 105,647`、`当日互动率 12.03%`、`传播健康度 51.46`、`当日涨粉 2,415`
- 异常拐点：作品级 7 个、整体异常日 6 个（z-score 检测生效）
- 评论情感：正面 27.2% / 负面 7.5%，平均分 0.13（词典法）
- AI 解读：未配置 Key → 自动走本地规则引擎，数据简报与问答均正常输出
- 历史归档：`data/archive/snapshots_2026-09-28.csv`

### 2. 界面冒烟测试（真实 windows 平台 + 离屏平台均通过）

```powershell
.\.venv\Scripts\python.exe scripts\gui_smoke.py           # 离屏，适合无人值守
$env:QT_QPA_PLATFORM="windows"; .\.venv\Scripts\python.exe scripts\gui_smoke.py --no-import
```

结果：完成「同步数据 → 执行分析 → 逐页截图 → 生成 AI 简报 → 数据问答 → 再截图」全流程，
每轮输出 10 张截图。**在真实 windows 平台连续运行 3 轮全部通过**（exit=0、无 faulthandler
崩溃日志），中文字体、图表、词云、表格渲染均正常。

> 小提示：调用脚本时不要用 ``| Select-Object -First N`` 这类会**提前关闭管道**的写法，
> 否则 Python 写入已关闭的 stdout 会异常退出（exit=1），看起来像"程序失败"——
> 排查过程中踩过这个坑，改用 ``Out-File`` 落盘再读取即可。

### 3. 幂等性

重复执行导入/分析不会产生重复记录（`(platform, platform_video_id)`、
`(video_id, stat_date)`、`(platform, platform_comment_id)` 唯一约束 + upsert）。

### 4. 缺陷修复验证（2026-09-28）

| 缺陷 | 现象 | 根因 | 修复 | 验证方式 |
| --- | --- | --- | --- | --- |
| **图表刷新导致进程崩溃** | 真实 windows 平台刷新图表后进程以 `0xC0000005`（访问违规）退出，faulthandler 定位到主线程事件循环 | `QChart.removeAllSeries()` / 直接 `removeAxis()` 会**销毁**底层 C++ 对象，而 Python 侧仍持有包装对象，刷新若干次后形成悬垂指针 | `app/ui/widgets/charts.py` 新增 `_reset_chart()`：改用 `removeSeries()` / `removeAxis()`（二者只**释放所有权**、不删除），再 `setParent(owner)` 交由 Qt 父子关系统一回收 | 图表连续刷新 40 次无崩溃；真实平台完整流程连续 3 轮通过 |
| **后台任务回调偶发丢失** | 界面偶发一直停在"处理中"，`busy` 不释放（冒烟测试等待 240s 超时中止） | `QThreadPool` 在 `run()` 返回后立即删除 `QRunnable`，承载信号的 `TaskSignals` 可能先于"投递到主线程的回调"被 Python 回收，信号因此丢失 | `app/ui/workers.py`：`setAutoDelete(False)`（生命周期交给 Python）+ `TaskRunner` 在回调真正执行完之前持有 task 强引用 | 连续提交 12 / 20 个后台任务，回调 12/12、20/20 全部到达；界面流程连续 3 轮通过 |

---

## 四、关键设计决策

1. **存储先用 SQLite、预留 MySQL**：桌面端零配置即可运行；`db_url` 一行切换 MySQL，
   表结构由 SQLAlchemy 统一生成，两种后端字段一致。理由：本机无 MySQL 服务时也能演示与自测。
2. **爬虫后置、接口先行**：先定义 `BaseCollector` 契约与融合映射，让「采集 → 分析 → AI → 看板」
   全链路可用离线样例数据跑通；接入爬虫时只需实现 `fetch()` 并注册。
3. **无 Key 也能用**：大模型调用与本地规则引擎共用同一份数据上下文，
   用户未配置 Key 或网络异常时自动回退并在文案顶部标注来源，避免演示中断。
4. **情感分析用词典法**：完全离线、可解释、零额外依赖（不引入分词模型），
   便于在论文中说明算法与调参；后续可平滑替换为模型打标（保持函数契约）。
5. **指标口径显式化**：互动率、增长率、传播健康度的权重与参考上限集中在
   `metrics.py` 的 `HEALTH_WEIGHTS` / `HEALTH_REFERENCE`，便于做消融/对比实验。

---

## 五、已知限制与遗留问题

| 项 | 说明 |
| --- | --- |
| 爬虫未实现 | B站/抖音采集器仅为骨架，真实数据需在下一阶段接入（含限速、代理、重试与告警） |
| 采集目标配置 | 设置页的 `collect_targets` 仅占位，待爬虫接入后提供增删界面 |
| 定时任务 | 目前只触发「分析」；接入爬虫后应改为「采集 + 融合 + 分析」 |
| 样例数据为模拟值 | 指标数量级与真实平台不同，仅用于验证链路与界面 |
| 词云仍有个别碎片 | 领域词表 + n-gram 去碎片已做过滤，真实语料下建议扩充词表 |
| 无自动化单元测试 | 当前以两个自检脚本代替；后续可补 pytest 覆盖指标与融合映射 |
| 未打包分发 | 需要 PyInstaller 打包为 exe（下一阶段） |
| 报表未导出 | 分析结果与 AI 文案暂未提供 PDF/Excel 导出 |

---

## 六、下一步计划

1. **接入 B站采集器**：`x/space/wbi/arc/search`（wbi 签名 + Cookie）、`x/web-interface/view`、
   `x/v2/reply/wbi/main`；实现 `fetch()` 并验证融合链路。
2. **接入抖音采集器**：Playwright 登录态抓包 + 签名方案，配合代理 IP 池与 1~3s 随机间隔限速。
3. **定时采集+分析**：`DailyScheduler` 触发采集流水线，写入 `collect_task` 并在界面展示任务状态。
4. **报告导出**：数据简报导出 Markdown/PDF，明细导出 Excel。
5. **MCP 扩展**：接入 `mcp` SDK，把外部工具服务器暴露给问答模块。
6. **多模态预留落地**：文生图（封面草稿）、文生视频扩展接口。
7. **测试与打包**：补 pytest 单测，PyInstaller 打包。

---

## 七、环境与依赖版本（当前验证环境）

- 操作系统：Windows（amd64）
- Python：3.14.6（虚拟环境 `.venv`）
- PySide6 6.11.2（含 PySide6-Addons → QtCharts）
- SQLAlchemy 2.1.1、PyMySQL 1.2.3
- pandas 3.0.6、numpy 2.5.3
- requests 2.34.2、APScheduler 3.11.3、python-dateutil 2.9.0.post0

> 说明：代码兼容 Python 3.9+ 写法（`from __future__ import annotations`），
> 但当前只在 Python 3.14 + PySide6 6.11 上做过完整验证。

---

## 八、v0.2.0 设计系统与扩展模块落地（2026-09-29）

### 8.1 设计系统落地

来源：`stitch_modular_extensible_ui_platform/deep_telemetry_intelligence_workspace/DESIGN.md`
（Google Stitch 导出），核心是「深色精密极简 + 目标性发光」。

| 项目 | 落地实现 |
| --- | --- |
| 颜色令牌 | `app/ui/theme.py`：canvas `#0F1117`、surface1-3 `#181B26/#1E2235/#252A40`、border `#2B3045`、青 `#00AEEC`、紫 `#8B5CF6`、珊瑚 `#FE2C55` |
| 字体 | 标题/正文用系统 UI 字体（设计稿的 Geist 本机不可用）；数字与表格用等宽字体（JetBrains Mono → Cascadia Mono → Consolas 依次回退） |
| 控件样式 | QSS 统一：卡片 8px 圆角 + 1px 结构边框（不用阴影）、控件 4px 圆角、按钮三种语义（主 / AI / 危险）、分段控件、徽标与状态点、表头 10px 等宽、行高 28~30 |
| 自绘组件 | `MiniBars`（KPI 迷你趋势）、`FunnelBars`（转化漏斗）、`SentimentBar`（情感极性条）、`TopicCloud`（热词标签云）、`LogoWidget`（品牌标识）、`NavDelegate`（导航图标 + 徽标自绘） |
| 主窗口骨架 | 顶部状态条（Logo / 库体积 / 模型引擎 / 上次分析 + 立即同步 + 一键全量分析）、侧栏（7 项导航 + 插件与扩展插槽）、底部状态栏（库体积 / APScheduler / QThreadPool） |

### 8.2 扩展方向一：视频创作咨询（`app/consulting/`）

- 数据表：`consult_session`、`consult_record`
- 能力：按 6 类主题（综合 / 账号定位 / 脚本结构 / 标题封面 / 增长策略 / 商业化）输出
  「直接结论 → 依据（引用数据）→ 执行方案 → 风险提示」，并自动抽取要点标签；
  历史咨询可回溯；无 API Key 时走本地规则模板。
- 页面：`app/ui/pages/consulting_page.py`

### 8.3 扩展方向二：AI 短剧（`app/drama/`）

- 数据表：`drama_project`、`drama_episode`、`drama_scene`
- 能力：一句话梗概 → 分集大纲 → 分集剧本 → 镜头级分镜
  （镜号 / 景别 / 时长 / 画面 / 台词 / 中英文文生图与文生视频提示词），支持覆盖再生成。
- 多模态预留：`generate_keyframe()` / `generate_clip()` 已按接口占位（抛 `NotImplementedError` 并说明），
  分镜表中的 `image_prompt` / `video_prompt` / `duration_sec` 即为其输入；界面以「预留」徽标呈现路线图
  （文生图关键帧 / 文生视频片段 / 配音字幕 / 自动剪辑）。
- 页面：`app/ui/pages/drama_page.py`

### 8.4 本轮验证与修复

- `python -m compileall app scripts` → 通过（无语法问题）
- `scripts/gui_smoke.py`（**真实 windows 平台**）：同步数据 → 分析 → 7 页截图 → AI 简报 → 数据问答
  → 创作咨询生成 → 新建短剧项目 → 生成大纲（6 集）→ 生成剧本 → 生成分镜（12 镜头）→ 再截图，
  **exit=0，共 14 张截图**，无异常与崩溃日志
- `scripts/smoke_check.py`：后端全链路与 CSV 幂等校验继续通过
- 修复缺陷：短剧分镜的本地回退返回结构化列表而非文本，导致解析报错
  （`'list' object has no attribute 'splitlines'`）→ 新增 `_storyboard_to_markdown()`
  统一渲染为表格文本后再解析，本地/大模型两条路径行为一致

---

## 九、v0.3.0 数据来源改造（2026-09-29）

### 9.1 改动目标

软件内**不再实现或配置任何爬取功能**。数据改由用户在外部定期采集后推送到**自建 Git 仓库**，
软件只负责「拉取 → 扫描 → 融合导入 → 分析」。

### 9.2 新增模块 `app/datasource/`

| 文件 | 职责 |
| --- | --- |
| `sync.py` | 同步方式：`git clone --depth 1` / `git pull --ff-only` / ZIP 归档下载 / 仅本地目录；`auto` 模式 git 失败自动回退 ZIP；仓库状态查询（commit、数据文件数、最近更新时间）；Windows 下静默执行 git（不弹控制台窗口） |
| `loader.py` | 仓库扫描与解析：按文件名/目录名自动归类 accounts / videos / snapshots / comments；同时支持**标准 CSV（统一字段）**与**平台原始 JSON/JSONL**（走 `fusion` 归一化）；作品内嵌 `snapshots` / `stats` 数组会被解析为每日快照；分片文件可用文件名日期兜底 |
| `templates.py` | 生成数据模板（CSV 表头 + 示例行）与 `DATA_FORMAT.md` 格式说明，用户照格式推送即可 |

### 9.3 移除的爬取相关代码

- 删除 `app/collect/bilibili.py`、`app/collect/douyin.py`（B站/抖音采集器骨架）
  与 `app/collect/base.py`（采集器契约与注册表）；
- 新增 `app/collect/contracts.py` 承接 `RawBatch` / `ImportResult` 数据契约（避免循环导入）；
- `pipeline.run_collect()` 移除；`collect_task` 表改为记录「数据仓库同步」结果（`create_repo_sync_log`）；
- 「数据源与抓取」页重构为 **「数据仓库与导入」页**：仓库配置表单、状态徽标、
  拉取/仅导入本地目录/生成模板/载入演示数据、同步记录 Tab；采集器卡片与"抓取单条"等入口全部移除。

### 9.4 配置扩展

`AppSettings.data_repo`（`DataRepoSettings`）：`url` / `branch` / `local_dir` / `subdir` /
`mode`（auto · git · zip · local）/ `auto_pull`；
配置读取支持嵌套 dataclass 递归构造，旧配置文件（无 `data_repo` 字段）可平滑升级。

### 9.5 定时任务联动

`_on_schedule_due()`：若开启 `auto_pull` 且已配置仓库 → 先「拉取 + 导入」再「分析」，
形成「外部爬取 → 推送仓库 → 本机拉取 → 分析」的日常闭环；未配置仓库时仍只触发分析。

### 9.6 验证结果

- **`scripts/repo_check.py`（新增，端到端）**：临时目录建 Git 仓库 → 写入标准 CSV 与平台原始 JSON/JSONL
  → `git clone` 拉取（commit `686fcd0`、9 个数据文件）→ 扫描分类
  （accounts:1 / videos:3 / snapshots:3 / comments:2）→ 导入结果
  **账号 4｜作品 5｜指标快照 12｜评论 4**（含 CSV 与 raw JSON 两种格式）→ 重复导入行数不变（幂等）
  → 归档地址转换（GitHub / Gitee）正确 → **exit=0**
- `scripts/smoke_check.py`：**exit=0**（既有分析与 AI 链路未受影响）
- `scripts/gui_smoke.py`：**exit=0**，14 张截图（7 个页面 + 简报/问答/咨询/短剧流程）

---

### 9.7 界面适配修复（v0.3.1）

| 问题 | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| **数据仓库页显示不完整 / 被压缩** | 窗口高度或宽度不足时，仓库配置表单被压扁（输入框显示成 `…`、控件重叠），右侧内容被裁切 | 页面没有滚动容器；且 `top` / `middle` 区域 `stretch=0`，布局把空间优先给了 Tab 区；窗口默认尺寸（1480×940）可能超过屏幕被系统强制缩小 | ① 「数据仓库与导入」页外层包 `QScrollArea`（垂直不足出滚动条、横向按需）；② 各卡片设最小高度（仓库 340 / 存储 300 / 映射 300 / Tab 360）保证内容完整；③ 主窗口按屏幕可用区自适应初始尺寸，并设最小 900×620；④ 窄窗口优化：工具栏精简为 3 个主按钮（「导出数据快照」「重启本地引擎」移入「数据」菜单）、顶栏状态胶囊与页内说明改为短文案且不换行 |

验证：在 **1024×680 / 1280×720 / 1440×900** 三种窗口尺寸下渲染「数据仓库与导入」页，
仓库地址/分支/数据子目录/本地缓存目录/获取方式/自动拉取/保存按钮全部完整可见，无裁切与压扁。

---

## 十、v0.4.0 外观主题与背景融合修复（2026-09-29）

### 10.1 修复「文字背后有不融合的黑色背景块」

**根因**：全局 QSS 写的是 `QWidget { background-color: canvas; }`，
于是**每个 QLabel 与容器**都会自己铺一层画布色（深色主题下 `#101319`），
而卡片底色是 `surface1`（`#171B24`）——两者不同色，卡片里的文字后面就出现一块块更暗的方形背景。

**修复**：全局 `QWidget` 背景改为 `transparent`，只为真正需要底色的容器显式设色：
- 画布级：`QMainWindow` / `#TitleBar` / `#SideBar` / `QStatusBar` / `#SegmentBar` → canvas
- 卡片级：`#ModuleCard` / `QGroupBox` / 输入控件 / 表格 / 文本区 / 列表 → surface1
- 浮层：`QMenu` / `QToolTip` → surface1-2

标签与普通容器不再绘制背景，因而与卡片自然融合。

**验证**：深色主题下采样 KPI 卡片内部颜色分布，97% 以上为卡片底色 `#171B24`，
画布色像素仅出现在卡片之间的间隙（属正常间隙，不是文字背后的色块）。

### 10.2 新增外观主题：浅黑 / 浅白 / 浅蓝

- `app/ui/theme.py` 重构为**多主题令牌系统**：`THEMES` 内含三套完整令牌
  （canvas、surface1-3、border、text 三级、on_accent、青/紫/珊瑚信号色、平台与情感色、logo 底），
  `apply_theme()` **原地更新** `COLORS` 等字典并重建 QSS；`apply_theme_to_app()` 负责重建样式并重绘全部控件。
- 浅色主题自动放大半透明填充（`_alpha()`），保证亮底上的选中/悬浮态依然可辨。
- 关键改造：把原先**模块级缓存的颜色**改为**运行时取色**
  （`charts._health_color()` / `_grid_color()`、`theme.tone_color()`、`dashboard._KIND_TONE` 只存色调名），
  否则切换主题后图表、徽标、拐点日志的颜色不会跟着变。
- 入口：**顶栏「浅黑 / 浅白 / 浅蓝」分段控件** + **设置页「外观主题」分组**；
  切换即时生效并写入 `AppSettings.theme`，下次启动自动沿用。
- 预览图（本地生成，`data/` 已 gitignore）：`data/screenshots/theme_dark.png`、`theme_light.png`、`theme_blue.png`。

### 10.3 验证

- 三套主题像素采样：**dark** 平均亮度 31.8（画布 `#101319`）／
  **light** 241.3（画布 `#f4f6fa`、卡片 `#ffffff`）／**blue** 236.4（画布 `#e9f2fb`、卡片 `#f8fbff`）
- `scripts/gui_smoke.py` **exit=0**（14 张截图）、`scripts/repo_check.py` **exit=0**

---

### 10.4 修复（v0.4.1）

| 问题 | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| **咨询类型显示英文** | 「视频创作咨询」页的分类按钮显示 `general / positioning / script …` | `consulting/prompts.py` 中 `CATEGORIES` 定义为 `(内部 key, 显示标签)`，而 `SegmentBar` 期望 `(显示标签, key)`——顺序写反了 | 统一 `CATEGORIES` 为 **(label, key)** 顺序并加注释；`CATEGORY_LABELS` 改为由 key→label 推导，避免再次错位 |
| **保存配置会把主题重置为浅黑** | 在浅白 / 浅蓝主题下配置并保存 API Key，界面自动跳回浅黑 | `SettingsPage.collect_settings()` 用 `AppSettings(...)` **重建**配置对象时未传 `theme`，于是取默认值 `dark`；`apply_settings()` 判定"主题变化"便切回浅黑（同理也会丢 `data_repo`） | 改用 `dataclasses.replace(当前配置, ...)` 只覆盖表单字段——由其它入口维护的字段不再丢失；主题以 `AppContext.settings.theme` 为准，UI 值仅作兜底 |

**验证**：连续四轮（浅白 → 浅蓝 → 浅黑 → 浅蓝）切换后各保存一次配置，主题均保持不变，
设置页 UI 与配置同步；咨询分类按钮全部为中文且内部 key 仍为 `general/positioning/...`。

---

### 10.5 标签与词云透明化 + 表格列宽修复（v0.4.2）

**需求**：各标签与词云的显示背景改为透明。

| 元素 | 改动 |
| --- | --- |
| 通用徽标 `QLabel#Badge`（卡片头的"实时 / 情感 / AI / 仓库 / 接口预留"等） | 填充色 → `transparent`，仅保留 1px 色调边框与文字色 |
| 行内胶囊 `chip()`（咨询要点、热词胶囊） | 同上 |
| 顶栏状态胶囊 `QLabel#Pill` | 填充 → `transparent`，保留圆角边框 |
| 侧栏导航徽标（`NavDelegate` 自绘） | 去掉填充，仅描边 |
| 表格平台标签（`PlatformBadgeDelegate` 自绘） | 去掉填充，仅描边 |
| 核心热词词云（`TopicCloud`） | 去掉每个词的圆角底色与边框，改为**纯文字**形态（仅用字号与颜色表达权重） |

**顺带修复（发现于验证过程）**：表格列宽从未真正应用 `Column.width`
—— Qt 一律使用默认 100px/列，列数多时总宽超出视口，`Stretch` 列被挤到最小，
作品标题只能显示成 `--`。现已在 `configure_table()` 中按列定义应用宽度，
分析页排行表列宽恢复为 `[56, 230, 76, 96, 88, 68, 62, 62]`（标题列 230px），标题完整可见。

**验证**：浅黑与浅白两套主题下截图确认标签无填充底色、词云为纯文字且对比度正常；
表格列宽实测与定义一致。

---

## 十二、v0.5.0 常驻 AI 咨询面板（2026-10-02）

**需求**：AI 决策助手固定在面板最右边，在什么页面都能进行咨询。

### 12.1 实现

| 层次 | 改动 |
| --- | --- |
| `AppContext` | 新增共享会话状态 `chat_history` / `chat_session_id`、`chat_message(role, content, is_fallback)` 信号与统一入口 `ask_ai()` / `reset_chat()` |
| `widgets/ai_chat.py`（新增） | `AiChatPanel`：可复用的咨询面板（对话区 + 输入框 + 快捷问题 + 仅本地规则开关 + 模型/上下文状态行），支持 `compact` 紧凑模式 |
| 主窗口 | 工作区改为 `QSplitter`：**左侧页面栈 + 右侧常驻 AI 咨询面板**（默认 380px，可拖动、最小 300）；顶栏新增 **「AI 咨询」开关按钮** 控制显示/隐藏 |
| AI 决策助手页 | 内置对话区改为复用同一个 `AiChatPanel`，删除原有重复的问答代码 |

**关键设计**：两个面板**共享同一会话**——提问统一走 `AppContext.ask_ai()`，
消息通过 `chat_message` 信号广播，因此在任意位置提问，右侧面板与 AI 助手页的对话内容始终一致；
会话上下文（历史与 session_id）由上下文持有，`新会话`按钮可随时重置。

### 12.2 验证

- 停留在「数据仓库与导入」页用右侧面板提问 → 返回真实 DeepSeek 回答（日志确认模型调用成功）
- 右侧面板与 AI 助手页面板文本**完全一致**（脚本比对 `True`）
- `scripts/gui_smoke.py` **exit=0**（冒烟流程已改为"在看板页用右侧面板提问"，即验证任意页面可咨询）
- `scripts/repo_check.py` **exit=0**、`scripts/smoke_check.py` **exit=0**

---

## 十三、变更记录

| 日期 | 版本 | 内容 |
| --- | --- | --- |
| 2026-09-28 | v0.1.0 | 完成基础功能：项目骨架、配置管理、统一数据模型与融合导入、本地分析、AI 解读与问答、桌面端看板与设置页、任务调度、日志与告警、两个自检脚本；补充 README 与本进度文档 |
| 2026-09-28 | v0.1.0-fix | 修复图表刷新崩溃与后台任务回调偶发丢失两个缺陷；看板新增「最新 AI 解读」回显；分析页指标表高度、作品榜列宽与热词词表优化；`data/` 整目录加入 .gitignore |
| 2026-09-29 | v0.2.0 | 全面应用 Deep Telemetry 设计系统（设计令牌 / QSS / 自绘组件 / 主窗口骨架），7 个页面按设计稿重构；新增「视频创作咨询」与「AI 短剧工坊」两个扩展模块（后端服务 + 数据表 + 页面）；分析层新增分平台趋势与转化漏斗指标；导出分析报表（Markdown + CSV）；修复短剧分镜解析缺陷 |
| 2026-09-29 | v0.3.0 | **数据来源改造**：移除软件内爬取功能（删除 B站/抖音采集器与注册表），新增 `app/datasource`（git/ZIP/本地目录同步 + 仓库扫描解析 + 数据模板）；「数据源与抓取」页重构为「数据仓库与导入」；配置新增 `data_repo`；定时任务支持"先拉取仓库再分析"；新增 `scripts/repo_check.py` 端到端验证 |
| 2026-09-29 | v0.3.1 | 修复「数据仓库与导入」页在小窗口下被压缩/裁切的问题：页面套滚动区 + 卡片最小高度 + 主窗口按屏幕自适应（最小 900×620）；窄窗口下工具栏与顶栏文案优化（次要操作移入菜单） |
| 2026-09-29 | v0.4.0 | 修复文字背后出现不融合黑色背景块（全局 QWidget 背景改为 transparent，只给需要底色的容器设色）；新增「浅黑/浅白/浅蓝」三套外观主题（令牌参数化 + 运行时取色 + 顶栏与设置页切换 + 配置持久化）；三种主题像素级验证通过 |
| 2026-10-02 | v0.4.1 | 修复「视频创作咨询」分类按钮显示英文（CATEGORIES 顺序 (label,key) 统一）；修复保存配置时主题被重置为浅黑（collect_settings 改用 dataclasses.replace，避免丢失 theme/data_repo 等字段）；新增 `scripts/png_clean.py` 清理 PNG iCCP 块以消除 libpng 警告 |
| 2026-10-02 | v0.4.2 | 各标签（徽标 / 行内胶囊 / 顶栏状态胶囊 / 侧栏导航徽标 / 表格平台标签）与词云改为**透明背景**（词云改为纯文字形态）；修复表格列宽未按定义应用导致 Stretch 列被挤没、标题只显示 `--` 的问题（`configure_table` 现按 `Column.width` 真正设宽） |
| 2026-10-02 | v0.5.0 | 新增**右侧常驻 AI 咨询面板**（`widgets/ai_chat.py` + `QSplitter` 工作区 + 顶栏开关），任意页面都能提问；会话状态上提到 `AppContext`（`ask_ai()` / `chat_message` 信号），右侧面板与 AI 决策助手页共享同一会话、内容实时同步 |
