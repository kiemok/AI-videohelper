# 基于B站与抖音的多源数据融合及AI驱动的内容创作决策系统

> 毕业设计项目 · 纯桌面端架构 · PySide6 + SQLAlchemy + 大模型 API

一个面向短视频创作者的桌面端智能助手：把 **B站** 与 **抖音** 两个平台的异构数据
融合为统一数据模型，在**本地**完成指标计算、异常拐点检测与评论情感分析，
再调用**用户自己配置**的大模型 API（DeepSeek / 通义千问 / 任意 OpenAI 兼容服务）
把分析结果转成通俗的数据解读与可执行的创作建议，并通过桌面端看板可视化呈现。

- 所有分析与数据存储都在本地完成（默认 SQLite，可一行切换到 MySQL）
- 数据来自**你自己维护的 Git 数据仓库**（外部爬虫定期推送），软件只拉取与导入——**不含任何爬虫代码**
- 大模型 API Key 只保存在**用户本机**配置文件，不入库、不上传
- 未配置 API Key 时自动降级为**本地规则引擎**，全链路依然可完整演示

当前版本：**v0.2.0（基础功能 + 设计系统 + 扩展模块框架）** — 详见 [`docs/PROGRESS.md`](docs/PROGRESS.md)

> 界面采用 `stitch_modular_extensible_ui_platform` 的
> **Deep Telemetry & Intelligence Workspace** 设计系统（深色精密极简 + 信号色发光），
> 并已为后续「视频创作咨询」与「AI 短剧」两个方向预留模块框架与页面。

---

## 一、技术栈

| 分层 | 选型 |
| --- | --- |
| 桌面端 | Python 3.9+（本项目在 3.14 上验证）、PySide6（含 QtCharts 图表） |
| 数据来源 | **用户自建 Git 数据仓库**：`git clone/pull` 或 ZIP 归档下载，软件仅拉取导入（无爬虫） |
| 数据格式 | 标准 CSV（统一模型字段）与平台原始 JSON/JSONL 双支持，自动融合映射 |
| 任务调度 | APScheduler（每日定时执行分析） |
| 数据存储 | SQLAlchemy 2.x 统一模型 → SQLite（默认）/ MySQL（PyMySQL 驱动） |
| 数据处理 | Pandas、NumPy |
| 大模型 | DeepSeek / 通义千问（OpenAI 兼容 `/chat/completions`），预留文生图/文生视频扩展点 |
| 可视化 | PySide6 原生 QtCharts（趋势/对比/环形图）+ QPainter 自绘漏斗、迷你趋势条、热词标签云 |
| 界面设计系统 | Deep Telemetry & Intelligence Workspace（青 `#00AEEC` / 紫 `#8B5CF6` / 珊瑚 `#FE2C55`） |
| 外观主题 | 内置「浅黑 / 浅白 / 浅蓝」三套主题，顶栏或设置页一键切换，切换即时生效并本地持久化 |
| MCP 工具 | 官方 `mcp` SDK（stdio / SSE），可接入任意 MCP 服务器作为 AI 咨询的外部工具 |
| 自定义技能 | Markdown + YAML 头部的技能包（`skills/` 目录），勾选启用后注入咨询提示词 |
| 界面自适应 | 自研组件 `ToolbarRow` / `ResponsiveSplitter` / `PageScrollArea` / `ResponsiveKpiRow`：标签与按钮固定尺寸、空间不足整体隐藏、窄窗口自动上下堆叠 |

---

## 二、目录结构

```
毕设/
├─ app/
│  ├─ main.py                  # 程序入口（python -m app.main）
│  ├─ config.py                # 配置管理：本地 settings.json、服务商预设、平台定义
│  ├─ core/
│  │  ├─ logging_setup.py      # 日志 + 告警通道（logs/app.log、logs/alerts.log）
│  │  └─ scheduler.py          # APScheduler 每日定时任务（信号回主线程）
│  ├─ db/
│  │  ├─ base.py               # 引擎缓存 / 建表 / 事务会话（SQLite、MySQL 兼容）
│  │  ├─ models.py             # 统一数据模型（账号、作品、指标快照、评论、分析、报告、会话）
│  │  └─ repository.py         # 数据访问层（upsert、聚合查询、总览统计）
│  ├─ datasource/              # 数据来源：用户自建 Git 数据仓库
│  │  ├─ sync.py               # git clone/pull、ZIP 归档下载、本地目录模式、状态查询
│  │  ├─ loader.py             # 仓库扫描与解析（标准 CSV / 平台原始 JSON·JSONL）
│  │  └─ templates.py          # 生成数据模板与格式说明（DATA_FORMAT.md）
│  ├─ collect/                 # 数据契约与融合导入
│  │  ├─ contracts.py          # RawBatch / ImportResult 契约
│  │  ├─ fusion.py             # 异构字段 → 统一模型 的融合映射规则
│  │  ├─ sample_source.py      # 离线演示数据源（无仓库时体验用，可导出 CSV）
│  │  └─ pipeline.py           # 批量导入流水线 + 快照归档
│  ├─ analysis/                # 本地分析
│  │  ├─ metrics.py            # 互动率、增长率、传播健康度等指标
│  │  ├─ anomaly.py            # 拐点检测（滚动 z-score + 增长转负）
│  │  ├─ sentiment.py          # 中文评论情感（词典 + 否定/程度修饰）
│  │  ├─ keywords.py           # 热词提取（领域词表 + n-gram 去碎片）
│  │  └─ service.py            # 分析编排：算指标 → 存结果 → 供界面/AI 复用
│  ├─ ai/
│  │  ├─ client.py             # OpenAI 兼容客户端（请求/重试/测试连接）
│  │  ├─ prompts.py            # 上下文构建、提示词模板、本地规则回退文案
│  │  └─ insights.py           # 解读/选题/标题/发布时间/问答 服务（含落库）
│  ├─ skills/                  # 自定义技能（Markdown + YAML 头部技能包）
│  │  └─ loader.py             # 技能解析 / 加载 / 保存 / 内置示例 / 提示词拼接
│  ├─ mcp/                     # MCP 外部工具接入
│  │  └─ client.py             # stdio / SSE 客户端、工具发现与调用、工具集合缓存
│  ├─ consulting/              # 扩展方向一：视频创作咨询│  │  ├─ service.py            # 咨询生成（分类方法论 + 数据上下文 + 本地回退）
│  │  ├─ prompts.py            # 咨询提示词、六类方法论、要点抽取
│  │  └─ repository.py         # 咨询会话 / 记录读写
│  ├─ drama/                   # 扩展方向二：AI 短剧
│  │  ├─ service.py            # 大纲 → 剧本 → 分镜 三级生成 + 多模态接口占位
│  │  ├─ prompts.py            # 编剧提示词、题材/景别字典、本地模板
│  │  └─ repository.py         # 项目 / 分集 / 分镜读写
│  └─ ui/
│     ├─ main_window.py        # 主窗口（导航 + 页面栈 + 菜单 + 状态栏）
│     ├─ context.py            # AppContext：配置、数据库、后台任务、信号中枢
│     ├─ workers.py            # QThreadPool 后台任务封装
│     ├─ theme.py              # 深色主题 QSS
│     ├─ pages/                # 看板 / 数据管理 / 分析详情 / AI 助手 / 设置
│     └─ widgets/              # KPI 卡片、图表、表格模型
├─ data/                       # 本地数据库、样例 CSV、归档（已 gitignore）
├─ docs/PROGRESS.md            # 开发进度记录（必读）
├─ logs/                       # 运行日志（已 gitignore）
├─ scripts/
│  ├─ smoke_check.py           # 无界面端到端自检（导入→分析→AI）
│  └─ gui_smoke.py             # 界面冒烟测试（离屏渲染 + 逐页截图）
├─ config/settings.json        # 本地配置（含 API Key，已 gitignore，自动生成）
└─ requirements.txt
```

---

## 三、快速开始

### 1. 环境要求

- Windows 10/11（macOS/Linux 亦可）、Python 3.9+
- 不需要预装 MySQL：默认使用本地 SQLite 单文件数据库

### 2. 安装依赖（使用国内镜像加速）

```powershell
# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 清华镜像（推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 3. 运行

```powershell
.\.venv\Scripts\python.exe -m app.main
```

首次使用：进入「数据管理」页 → 点击 **同步样例数据** → 点击 **执行分析**，
看板、分析详情、AI 助手即可看到完整结果。

### 4. 自检脚本（无需人工点击）

```powershell
# 后端全链路自检：初始化库 → 导入样例/CSV → 分析 → AI 解读 → 问答 → 归档
.\.venv\Scripts\python.exe scripts\smoke_check.py

# 界面冒烟：离屏渲染主窗口，跑一遍流程并逐页截图（输出到系统临时目录）
.\.venv\Scripts\python.exe scripts\gui_smoke.py
```

---

## 四、功能页面

界面为**顶部状态条 + 左侧工作台导航 + 底部状态栏**的桌面工作台结构
（顶栏显示本地库体积 / 模型引擎 / 上次分析时间，底栏显示调度与线程池状态）。

| 页面 | 内容 |
| --- | --- |
| 📊 数据看板 | KPI 四卡（总播放 / 互动率 / 净增粉 / 传播健康度，含迷你趋势条）、双平台播放与互动趋势（B站青 / 抖音珊瑚 + 健康度虚线 + 拐点标记）、平台流量与价值转化漏斗、作品 TOP 榜（**可上下拖动分隔条缩放高度**）、一键导出报表 |
| ◍ 内容与评论分析 | 平台筛选 / 关键词搜索 / 排序切换、作品综合排行、评论区情感极性与情绪分布、核心热词标签云 |
| ✦ AI 决策助手 | 模型引擎状态条、智能数据决策简报、爆款选题与建议矩阵（选题/标题/发布时机）、**AI 快速创作洞察摘要**（与数据看板共用同一组件，可就地生成 / 刷新）。对话咨询统一由窗口右侧的常驻 AI 面板承担 |
| ⛭ 技能与工具 | **自定义技能**（勾选启用 / 新建 / 编辑 / 删除 / 写入内置示例 / 打开目录，Markdown 文件即技能）与 **MCP 服务器**（stdio / SSE 配置、连接测试、工具列表）；咨询时模型可调用工具获取更精确数据 |
| ☰ 视频创作咨询 | **扩展方向一**：按账号定位/脚本结构/标题封面/增长策略/商业化分类咨询，输出「结论 + 依据 + 执行方案 + 风险提示」，历史记录可回溯 |
| ▶ AI 短剧工坊 | **扩展方向二**：梗概 → 分集大纲 → 分集剧本 → 镜头级分镜（含中英文文生图/文生视频提示词），多模态能力预留接口 |
| ⛁ 数据仓库与导入 | 仓库配置（地址/分支/本地目录/获取方式/每日自动拉取）、拉取与更新、仅导入本地目录、生成数据模板、载入演示数据；本地存储遥测、统一实体映射表、作品/账号/快照/同步记录清单 |
| ⚙ 调度与设置 | **外观主题（浅黑 / 浅白 / 浅蓝）**、数据库连接（SQLite/MySQL）、大模型服务商与 API Key、温度与超参、代理、每日定时任务、日志级别、连接测试 |

所有耗时操作（导入、分析、大模型请求）都通过 `QThreadPool` 在工作线程执行，
界面通过 Qt 信号更新，不会卡死。

---

## 五、指标口径（与论文一致）

对每个作品、每一天，基于**累计指标快照**计算增量与派生指标：

| 指标 | 定义 |
| --- | --- |
| 当日新增播放 `daily_views` | 相邻两日累计播放量之差（首日取累计值） |
| 当日互动 `daily_engagement` | Δ点赞 + Δ评论 + Δ分享 + Δ收藏 + Δ弹幕 |
| **当日互动率** | 当日互动 / 当日新增播放 |
| 累计互动率 | 累计互动 / 累计播放 |
| 日增长率 `growth_rate` | 当日新增播放 / 前一日累计播放 |
| **传播健康度** `health_score` | `100 × (0.40·min(1, 互动率/0.10) + 0.20·min(1, 收藏率/0.025) + 0.20·min(1, 分享率/0.012) + 0.20·min(1, 增长率/0.20))` |
| 异常拐点 | 7 日滚动窗口 z-score，`abs(z) ≥ 2`：`spike` 放量 / `drop` 衰减 / `recover` 回升 / `fade` 增长转负 |
| 评论情感 | 词典法 + 否定词/程度副词修饰，得分经 `tanh` 压缩到 [-1,1]，阈值 ±0.15 划分正/中/负 |

> 权重与参考上限集中在 `app/analysis/metrics.py` 的 `HEALTH_WEIGHTS` / `HEALTH_REFERENCE`，
> 情感词表集中在 `app/analysis/sentiment.py`，都便于按论文口径调参并做对比实验。

---

## 六、配置说明

配置文件默认位于 `config/settings.json`（已加入 `.gitignore`），也可用环境变量
`CCD_CONFIG_PATH` 指定其它位置。

### 大模型 API Key（用户本地保存）

设置页 → 「大模型 API」：

1. 选择服务商：`DeepSeek` / `通义千问(DashScope)` / `自定义(OpenAI 兼容)`
2. 填入自己的 API Key（密码框，可点「显示」查看）
3. 若服务商有自定义网关，填写 `Base URL` 与 `模型名`；否则留空使用预设：
   - DeepSeek：`https://api.deepseek.com/v1`，`deepseek-chat`
   - 通义千问：`https://dashscope.aliyuncs.com/compatible-mode/v1`，`qwen-plus`
4. 点击 **测试大模型连接** 验证，然后 **保存配置**

> Key 只写入本机的 `config/settings.json`，不会写入数据库、不会提交到 Git。
> 未配置 Key（或调用失败）时，系统自动回退到本地规则引擎并在输出顶部标注。

### 切换到 MySQL

设置页 → 「数据存储」→ 将连接串改为：

```
mysql+pymysql://root:你的密码@127.0.0.1:3306/content_decision?charset=utf8mb4
```

点击 **测试数据库连接** 通过后保存即可（表结构会自动创建，字段与 SQLite 版本一致）。

---

### 自定义技能与 MCP 工具（扩展 AI 咨询）

在「**技能与工具**」页维护，两者都会作用于 AI 咨询（右侧常驻面板与 AI 决策助手页共用）：

**1. 自定义技能（Skill）** —— 每个技能就是一个 Markdown 文件：

```markdown
---
name: 抖音三秒钩子专家
description: 为抖音短视频设计前 3 秒钩子与开场节奏
scenario: 需要提升完播率、开头吸引力时启用
tags: [抖音, 钩子, 完播率]
---

（正文 = 注入大模型的专家提示词，写清要求、输出格式与禁止事项）
```

- 存放目录默认 `<项目根>/skills/`（可在设置里改），点「写入内置示例」会生成 4 个示例技能；
- 在列表中**勾选**即启用，启用后其提示词会注入咨询的 system prompt（可多选叠加）；
- 支持在界面新建 / 编辑 / 删除，也可直接用编辑器改文件后点「重新加载技能」。

**2. MCP 外部工具** —— 让模型能调用外部工具取更精确的数据：

| 字段 | 说明 |
| --- | --- |
| 传输 | `stdio`（本地命令启动）或 `SSE`（远程地址） |
| 命令 / 参数 | stdio 模式：可执行文件 + 参数，例如 `.venv\Scripts\python.exe` + `scripts/sample_mcp_server.py` |
| 地址 | SSE 模式：服务器 URL |
| 超时 | 单次调用超时（秒） |

- 保存后点「测试连接」可看到该服务器的工具列表，点「刷新工具连接」汇总全部已启用服务器的工具；
- 咨询时工具会以 function calling 形式提供，模型自主决定调用，**最多 3 轮**工具调用后收尾；
- 仓库自带示例服务器 `scripts/sample_mcp_server.py`（纯 Python，无需 node），
  提供「查作品排行 / 查评论样本 / 读最新指标」三个工具，可直接用它验证整条链路。

> 工具名会自动生成 ASCII 别名（如 `server1__query_top_videos`）以符合模型服务端的命名要求，
> 界面上仍显示中文服务器名与中文工具描述。

---

### 界面自适应（窗口缩放不变形）

所有页面的顶部标签与按钮都遵循「**完整显示，或整体隐藏**」的规则，窗口中不会出现
半截文字、被压扁的输入框或拉伸变形的按钮：

- **工具栏**：自适应组件 `ToolbarRow`（`app/ui/widgets/toolbar.py`）——控件按自然尺寸固定，
  布局无法压缩或拉伸它；宽度不足时按优先级（辅助说明 → 常规控件 → 重要控件）逐个**整体隐藏**；
  标题与主操作按钮永不隐藏。
- **内容区**：`ResponsiveSplitter`——窗口够宽时左右并排，太窄时自动**上下堆叠**，
  每一栏都能拿到完整宽度；页面套 `PageScrollArea`，只保留纵向滚动。
- **KPI 卡片行**：`ResponsiveKpiRow`——窄窗口下自动从 4 列换成 2 列，卡片标题不被裁切。

| 窗口宽度（示例） | 顶栏 | 页面工具栏 | 内容区 |
| --- | --- | --- | --- |
| 1920 / 最大化 | 全部状态胶囊 + 主题切换 + 全部操作 | 全部筛选与按钮 | 左右并排 |
| 1480 | 全部 | 隐藏辅助说明文字 | 左右并排 |
| 1280 | 精简（隐藏次要胶囊） | 再隐藏搜索框 / 排序 | 上下堆叠 |
| 1080 | 品牌 + 主操作 | 仅标题 + 主操作 | 上下堆叠（KPI 2 列） |

**窗口最小尺寸**：最小宽度 = 侧栏(232) + 页面区最小(520) + AI 面板最小(300) + 拖动手柄(6) = **1058px**
（收起 AI 面板时为 752px）。即**右侧 AI 咨询面板缩到最小时，窗口就无法再继续缩小**，
避免页面与工具栏被压缩变形；屏幕可用宽度不足时最小宽度会自动收敛到屏幕内。

**看板「作品表现 TOP」区域缩放**：趋势/漏斗区与「作品表现 TOP」之间有一条**可上下拖动**的分隔条 ——
向上拖大即可看到更多作品行（最多占页面 80%），向下拖小则让上方图表区更大（各自都有最小高度兜底）。
比例默认 45%，拖动松手后自动写入本地配置，下次启动沿用。

---

## 七、数据仓库（数据来源）

软件内**不包含任何爬取功能**：数据由你在外部定期采集后推送到自建 Git 仓库，软件只负责拉取与导入。

### 使用步骤

1. 建一个 Git 仓库（Gitee / GitHub / 自建 Git 均可），把爬虫产出的数据放进去并推送；
2. 打开软件 →「数据仓库与导入」页 → 填 **仓库地址 / 分支 / 获取方式**（自动 · 仅 git · 仅 ZIP · 仅本地目录）；
3. 点 **「拉取 / 更新数据」**：软件 `git clone/pull`（或下载 ZIP 归档）→ 自动扫描 → 融合归一化 → 写入本地统一模型；
4. 勾选 **「每日定时任务触发时先自动拉取仓库」** 后，定时任务会先拉取数据再执行分析；
5. 不想联网时，可先自己 `git pull`，再用 **「仅导入本地目录」** 把目录内容导入。

### 支持的仓库数据格式（两种可混用）

**A. 标准 CSV（统一模型字段）**

```
accounts.csv                    platform,platform_account_id,nickname,follower_count,...
videos.csv                      platform,platform_video_id,account_platform_id,title,...
snapshots/YYYY-MM-DD.csv        platform,platform_video_id,stat_date,view_count,like_count,...
comments/YYYY-MM-DD.csv         platform,platform_comment_id,platform_video_id,content,...
```

**B. 平台原始 JSON / JSONL（爬虫导出原样即可）**

```
bilibili/videos.json     [{ "bvid": "BV1xx", "title": "...", "stat": {...}, "owner": {...} }]
bilibili/comments.jsonl  每行一个 { "rpid": ..., "message": ..., "member": {...} }
douyin/videos.json       [{ "aweme_id": "...", "desc": "...", "statistics": {...}, "author": {...} }]
```

- 文件按 `accounts / videos / snapshots / comments` 关键字自动归类（目录名或文件名命中即可）；
- 原始字段由 `app/collect/fusion.py` 自动映射为统一模型，**无需手动改字段名**；
- 作品对象内若带 `snapshots` / `stats` 数组，会被解析为该作品的每日指标快照；
- 点「生成数据模板」可把模板与 `DATA_FORMAT.md` 写到本地仓库目录，照格式填数据即可。

> 没有仓库时，可用 **「载入演示数据」** 体验完整功能（离线生成的模拟数据，非真实平台数据）。
> 端到端验证脚本：`scripts/repo_check.py`（建仓库 → 两种格式 → git 拉取 → 幂等导入）。

---

## 八、后续计划

1. **仓库数据管道增强**：支持 Parquet/分块增量、仓库内数据版本对比（diff 两次提交的指标变化）、导入校验报告。
2. **数据仓库自动化**：软件侧提供「拉取后自动归档 + 变更摘要」；外部爬虫与仓库推送由你维护。
3. **多模态落地**：短剧分镜已保存 `image_prompt` / `video_prompt` 与镜头时长，
   接入文生图 / 文生视频 / TTS 后可串联「关键帧 → 镜头片段 → 配音 → 自动剪辑」。
4. **创作咨询增强**：接入账号画像与历史内容向量化检索（RAG），让咨询建议更贴合个人风格。
5. **MCP 扩展**：接入 `mcp` SDK，把外部工具服务器（检索、图表生成等）暴露给 AI 助手。
6. **打包分发**：PyInstaller 打包为免安装 exe。

细节与最新进度见 [`docs/PROGRESS.md`](docs/PROGRESS.md)。
