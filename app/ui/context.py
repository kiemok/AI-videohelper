"""应用上下文：全局配置、数据库连接、分析结果与后台任务的共享中枢。"""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.ai import InsightService
from app.analysis import analysis_date_options, run_daily_analysis
from app.collect import archive_snapshots_csv, import_csv_dir, sync_sample_data
from app.config import AppSettings, ensure_dirs, load_settings, save_settings
from app.consulting import ConsultService
from app.core.logging_setup import get_logger, setup_logging
from app.core.scheduler import DailyScheduler
from app.db.base import init_db, reset_engines
from app.db.repository import clear_all_data, data_overview, latest_analysis, latest_report
from app.drama import DramaService
from app.ui.workers import TaskRunner

logger = get_logger(__name__)


class AppContext(QObject):
    """界面各页面共享的状态与操作入口。"""

    metrics_updated = Signal(dict)  # 分析结果刷新
    data_changed = Signal()  # 数据发生变化（导入/清空）
    report_updated = Signal()  # 新生成 AI 报告（看板回显刷新）
    settings_changed = Signal()  # 配置变化（大模型/数据库）
    theme_changed = Signal(str)  # 外观主题切换（浅黑/浅白/浅蓝）
    chat_message = Signal(str, str, bool)  # AI 对话消息（role, content, is_fallback）
    status_message = Signal(str)  # 状态栏提示

    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        self.settings: AppSettings = load_settings()
        setup_logging(self.settings.log_level)
        self.db_url: str = self.settings.resolved_db_url()
        init_db(self.db_url)
        self.runner = TaskRunner(self)
        self.metrics: dict[str, Any] = {}
        self.busy = False
        # AI 咨询会话：右侧常驻面板与「AI 决策助手」页共用同一份上下文
        self.chat_history: list[dict[str, str]] = []
        self.chat_session_id: int | None = None
        self.scheduler = DailyScheduler(self)
        self.scheduler.due.connect(self._on_schedule_due)
        if self.settings.schedule_enabled:
            ok, message = self.scheduler.start(self.settings.schedule_time)
            logger.info("定时任务启动：%s（%s）", ok, message)
        self.status_message.emit(f"已连接数据库：{self.db_url.split('///')[-1]}")

    # ------------------------------------------------------------------ #
    @property
    def insights(self) -> InsightService:
        """每次取用时构造，保证设置变更立即生效。"""
        return InsightService(self.settings, self.db_url)

    @property
    def consulting(self) -> ConsultService:
        """视频创作咨询（扩展方向一）。"""
        return ConsultService(self.settings, self.db_url)

    @property
    def drama(self) -> DramaService:
        """AI 短剧（扩展方向二）。"""
        return DramaService(self.settings, self.db_url)

    def db_size_text(self) -> str:
        """状态栏用：本地库文件大小 / MySQL 连接标识。"""
        if self.db_url.startswith("sqlite"):
            path = self.db_url.split("///")[-1]
            try:
                from pathlib import Path

                size = Path(path).stat().st_size
            except OSError:
                return "SQLite · 新建中"
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024 or unit == "GB":
                    return f"SQLite · {size:.1f} {unit}"
                size /= 1024
        return "MySQL · 已连接"

    def last_sync_text(self) -> str:
        """状态栏 / 顶栏用：最近一次分析生成时间（短格式，避免窄窗口挤压）。"""
        generated = (self.metrics or {}).get("generated_at")
        if not generated:
            return "分析时间：暂无"
        text = str(generated)[:16].replace("T", " ")
        return f"分析时间：{text[5:]}" if len(text) >= 16 else f"分析时间：{text}"

    def model_status(self) -> tuple[str, str]:
        """状态栏 / 顶栏用：(文本, 色调)。"""
        llm = self.settings.llm
        if llm.is_configured:
            return f"模型：{llm.provider} / {llm.resolved_model()}", "violet"
        return "模型：本地规则引擎", "muted"

    def engine_status(self) -> str:
        """状态栏用：定时任务状态。"""
        if self.scheduler.is_running:
            return f"APScheduler：运行中（每日 {self.settings.schedule_time}）"
        return "APScheduler：未启用"

    def overview(self) -> dict[str, Any]:
        return data_overview(self.db_url)

    def date_options(self, platform: str | None = None) -> list[str]:
        return analysis_date_options(self.db_url, platform)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        if message:
            self.status_message.emit(message)

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def apply_settings(self, settings: AppSettings) -> None:
        """保存配置；数据库地址变化时重建连接，外观主题变化时立即生效。"""
        db_changed = settings.resolved_db_url() != self.db_url
        theme_changed = settings.theme != self.settings.theme
        self.settings = settings
        save_settings(settings)
        if db_changed:
            reset_engines()
            self.db_url = settings.resolved_db_url()
            init_db(self.db_url)
            logger.info("数据库已切换为 %s", self.db_url)
        setup_logging(settings.log_level)
        self._sync_scheduler()
        if theme_changed:
            self.apply_theme(settings.theme, persist=False)
        self.settings_changed.emit()
        self.status_message.emit("配置已保存")

    # ------------------------------------------------------------------ #
    # 外观主题
    # ------------------------------------------------------------------ #
    def apply_theme(self, name: str, persist: bool = True) -> None:
        """切换外观主题（浅黑 / 浅白 / 浅蓝）并即时生效。

        - 重建全局 QSS 并重绘所有控件（标签/卡片底色随之更新）
        - 重新触发一次渲染，使图表/自绘组件按新令牌重新着色
        """
        from app.ui import theme as theme_module

        applied = theme_module.apply_theme_to_app(name)
        self.settings.theme = applied
        if persist:
            save_settings(self.settings)
        self.theme_changed.emit(applied)
        self.metrics_updated.emit(self.metrics or {})
        self.status_message.emit(f"已切换外观主题：{theme_module.theme_label(applied)}")

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def sync_sample_data(self, days: int = 30, response: Any = None) -> None:
        self.set_busy(True, "正在生成并导入样例数据…")

        def done(result: Any) -> None:
            self.set_busy(False, result.summary())
            self.data_changed.emit()

        self.runner.submit(
            sync_sample_data,
            done,
            lambda err: self._on_error(err, "样例数据导入失败"),
            self.db_url,
            days=days,
            export_csv=True,
        )

    def import_csv(self, directory: Any = None) -> None:
        self.set_busy(True, "正在导入 CSV 数据…")

        def done(result: Any) -> None:
            self.set_busy(False, result.summary())
            self.data_changed.emit()

        self.runner.submit(
            import_csv_dir,
            done,
            lambda err: self._on_error(err, "CSV 导入失败"),
            self.db_url,
            directory,
        )

    def archive_data(self) -> None:
        self.set_busy(True, "正在归档指标快照…")

        def done(path: Any) -> None:
            self.set_busy(False, f"归档完成：{path}" if path else "没有可归档的数据")

        self.runner.submit(
            archive_snapshots_csv,
            done,
            lambda err: self._on_error(err, "归档失败"),
            self.db_url,
        )

    def clear_data(self) -> None:
        self.set_busy(True, "正在清空业务数据…")

        def done(_: Any) -> None:
            self.set_busy(False, "数据已清空")
            self.metrics = {}
            self.data_changed.emit()
            self.metrics_updated.emit({})

        self.runner.submit(
            clear_all_data,
            done,
            lambda err: self._on_error(err, "清空数据失败"),
            self.db_url,
        )

    # ------------------------------------------------------------------ #
    # 分析
    # ------------------------------------------------------------------ #
    def run_analysis(self, stat_date: date | None = None, platform: str | None = None) -> None:
        self.set_busy(True, "正在执行本地分析…")

        def done(metrics: dict[str, Any]) -> None:
            if metrics:
                self.metrics = metrics
                self.set_busy(False, f"分析完成：{metrics.get('stat_date')}")
                self.metrics_updated.emit(metrics)
            else:
                self.set_busy(False, "没有可用数据，请先导入数据")

        self.runner.submit(
            run_daily_analysis,
            done,
            lambda err: self._on_error(err, "分析失败"),
            self.db_url,
            stat_date=stat_date,
            platform=platform,
        )

    def load_latest_metrics(self) -> dict[str, Any]:
        """启动时载入最近一次分析结果（不重算）。"""
        self.metrics = latest_analysis(self.db_url) or {}
        return self.metrics

    def latest_brief(self) -> dict[str, Any] | None:
        """最近一份「数据简报」，供看板回显（不重新调用大模型）。"""
        return latest_report(self.db_url, "daily_brief")

    # ------------------------------------------------------------------ #
    # AI 咨询（右侧常驻面板与 AI 决策助手页共用）
    # ------------------------------------------------------------------ #
    def ask_ai(self, question: str, force_local: bool = False) -> None:
        """统一的 AI 问答入口：在任意页面都可发起咨询。

        消息通过 ``chat_message`` 信号广播，所有已挂载的咨询面板会同步显示，
        因此右侧常驻面板与「AI 决策助手」页的对话内容始终一致。
        """
        question = (question or "").strip()
        if not question:
            return
        if self.busy:
            self.status_message.emit("当前仍有任务在执行，请稍候再提问")
            return

        self.set_busy(True, "AI 正在思考…")
        self.chat_message.emit("user", question, False)

        def job() -> dict[str, Any]:
            return self.insights.ask(
                question,
                self.metrics,
                list(self.chat_history),
                self.chat_session_id,
                force_local,
            )

        def done(result: dict[str, Any]) -> None:
            self.chat_session_id = result.get("session_id") or self.chat_session_id
            self.chat_history.append({"role": "user", "content": question})
            self.chat_history.append(
                {"role": "assistant", "content": result.get("content", "")}
            )
            self.chat_message.emit(
                "assistant", result.get("content", ""), bool(result.get("is_fallback"))
            )
            source = (
                "本地规则引擎"
                if result.get("is_fallback")
                else f"{result.get('provider')}/{result.get('model')}"
            )
            self.set_busy(False, f"AI 回答完成（{source}）")

        self.runner.submit(job, done, lambda error: self._on_error(error, "AI 问答失败"))

    def reset_chat(self) -> None:
        """开启新一轮 AI 会话（清空上下文，历史消息仍保存在数据库中）。"""
        self.chat_history.clear()
        self.chat_session_id = None
        self.chat_message.emit("reset", "", False)
        self.status_message.emit("已开启新的 AI 会话")

    def export_analysis(self) -> None:
        """导出当前分析报表（Markdown 汇总 + 作品榜 CSV）到 data/export/。"""
        self.set_busy(True, "正在导出分析报表…")

        def job() -> str:
            import csv
            import time as _time
            from pathlib import Path

            from app.config import DATA_DIR
            from app.db.repository import latest_report

            metrics = self.metrics or {}
            if not metrics:
                raise RuntimeError("还没有分析结果，请先执行一次分析")
            out_dir = Path(DATA_DIR) / "export"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = _time.strftime("%Y%m%d_%H%M%S")
            head = metrics.get("headline", {}) or {}

            md = [
                f"# 双平台数据分析报表 · {metrics.get('stat_date')}",
                "",
                f"- 统计口径：{metrics.get('platform') or '全平台'}｜生成时间：{metrics.get('generated_at')}",
                f"- 当日新增播放：{int(head.get('daily_views', 0)):,}"
                f"（环比 {head.get('daily_views_growth')}%）",
                f"- 累计播放：{int(head.get('total_views', 0)):,}｜当日互动：{int(head.get('daily_engagement', 0)):,}",
                f"- 当日互动率：{head.get('engagement_rate')}%｜传播健康度：{head.get('health_score')}",
                f"- 当日涨粉：{int(head.get('follower_gain', 0)):,}",
                "",
                "## 平台对比",
            ]
            for platform, data in (metrics.get("platform_compare") or {}).items():
                md.append(
                    f"- {platform}：新增播放 {int(data.get('daily_views', 0)):,}、"
                    f"互动率 {data.get('engagement_rate')}%、健康度 {data.get('health_score')}"
                )
            md += ["", "## 异常拐点"]
            for item in (metrics.get("anomalies") or [])[:20]:
                md.append(
                    f"- {item.get('stat_date')} [{item.get('platform')}] 《{item.get('title')}》：{item.get('note')}"
                )
            md += ["", "## 评论情感"]
            sentiment = metrics.get("sentiment") or {}
            md.append(
                f"- 共 {sentiment.get('total', 0)} 条，正面 {sentiment.get('positive_ratio')}%、"
                f"负面 {sentiment.get('negative_ratio')}%，平均分 {sentiment.get('avg_score')}"
            )
            md += ["", "## 热词", "、".join(f"{k['word']}({k['count']})" for k in (metrics.get("keywords") or [])[:20])]
            report = latest_report(self.db_url, "daily_brief")
            if report:
                md += ["", "## AI 数据简报", report.get("content", "")]
            md_path = out_dir / f"analysis_{stamp}.md"
            md_path.write_text("\n".join(md), encoding="utf-8")

            csv_path = out_dir / f"top_videos_{stamp}.csv"
            fields = [
                "title",
                "platform",
                "account",
                "daily_views",
                "engagement_rate",
                "growth_rate",
                "health_score",
            ]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for row in metrics.get("top_videos") or []:
                    writer.writerow({key: row.get(key) for key in fields})
            return f"已导出 {md_path.name} 与 {csv_path.name}"

        self.runner.submit(
            job,
            lambda message: self.set_busy(False, message),
            lambda error: self._on_error(error, "导出报表失败"),
        )

    # ------------------------------------------------------------------ #
    # 数据仓库（数据由用户自建仓库提供，软件只做拉取与导入）
    # ------------------------------------------------------------------ #
    def repo_status(self) -> dict[str, Any]:
        """本地仓库状态（不联网）。"""
        from app.datasource import repository_status

        return repository_status(self.settings.data_repo)

    def sync_data_repo(self) -> None:
        """拉取/更新数据仓库并导入统一模型。"""
        repo = self.settings.data_repo
        if not repo.is_configured:
            self.status_message.emit("尚未配置数据仓库：请到「数据仓库与导入」页填写仓库地址")
            return
        self.set_busy(True, "正在拉取数据仓库…")
        self.runner.submit(
            self._sync_repo_job,
            self._after_repo_sync,
            lambda error: self._on_error(error, "数据仓库同步失败"),
        )

    def _sync_repo_job(self) -> str:
        from app.datasource import import_repository, scan_repository, sync_repository
        from app.db.repository import create_repo_sync_log

        repo = self.settings.data_repo
        result = sync_repository(repo)
        if not result.ok:
            create_repo_sync_log(self.db_url, result.action or "sync", f"失败：{result.error}")
            raise RuntimeError(result.error or "同步失败")

        scan = scan_repository(result.local_dir or repo.resolved_local_dir(), repo.subdir)
        if scan.total() == 0:
            create_repo_sync_log(self.db_url, result.action, "仓库内未发现可识别数据文件")
            raise RuntimeError("仓库内未发现可识别的数据文件（支持 CSV / JSON / JSONL）")

        imported = import_repository(self.db_url, scan, source=f"数据仓库·{result.action}")
        create_repo_sync_log(self.db_url, result.action, imported.summary(), result.file_count)
        return f"{result.message}，{scan.describe()}；{imported.summary()}"

    def _after_repo_sync(self, message: str) -> None:
        self.set_busy(False, f"数据仓库已更新：{message}")
        self.data_changed.emit()

    def _after_scheduled_sync(self, message: str) -> None:
        """定时任务：仓库同步完成后接着做分析。"""
        self._after_repo_sync(message)
        self.run_analysis()

    def import_repo_local(self) -> None:
        """不联网：直接导入本地仓库目录（适合自己先 git pull 过的场景）。"""
        self.set_busy(True, "正在导入本地仓库目录…")

        def job() -> str:
            from app.datasource import import_repository, scan_repository

            repo = self.settings.data_repo
            scan = scan_repository(repo.resolved_local_dir(), repo.subdir)
            if scan.total() == 0:
                raise RuntimeError(f"目录中没有可识别的数据文件：{repo.resolved_local_dir()}")
            imported = import_repository(self.db_url, scan, source="本地仓库目录")
            return f"{scan.describe()}；{imported.summary()}"

        self.runner.submit(job, self._after_repo_sync, lambda e: self._on_error(e, "导入失败"))

    def write_repo_templates(self) -> None:
        """在仓库本地目录生成数据模板（CSV 表头 + 格式说明）。"""

        def job() -> str:
            from app.datasource import write_data_templates

            target = self.settings.data_repo.resolved_local_dir()
            written = write_data_templates(target)
            return f"已生成 {len(written)} 个模板文件 -> {target}"

        self.runner.submit(
            job,
            lambda message: self.status_message.emit(message),
            lambda error: self._on_error(error, "生成数据模板失败"),
        )

    # ------------------------------------------------------------------ #
    # 定时任务
    # ------------------------------------------------------------------ #
    def _sync_scheduler(self) -> None:
        """按当前配置启停每日定时任务。"""
        if self.settings.schedule_enabled:
            ok, message = self.scheduler.start(self.settings.schedule_time)
            if not ok:
                logger.warning("定时任务启动失败：%s", message)
        else:
            self.scheduler.stop()
            message = "定时任务已关闭"
        self.status_message.emit(message)

    def _on_schedule_due(self) -> None:
        """定时任务到点（APScheduler 线程 → Qt 主线程信号）。

        若开启了「自动拉取数据仓库」，则先拉取并导入最新数据，再执行分析，
        形成「外部爬取 → 推送仓库 → 本机拉取 → 分析」的日常闭环。
        """
        if self.busy:
            logger.warning("定时任务触发时仍有任务在执行，跳过本次")
            self.status_message.emit("定时任务触发：当前任务未完成，已跳过本次")
            return

        repo = self.settings.data_repo
        if repo.auto_pull and repo.is_configured:
            self.status_message.emit("定时任务：正在拉取数据仓库…")
            self.runner.submit(
                self._sync_repo_job,
                self._after_scheduled_sync,
                lambda error: self._on_error(error, "定时拉取数据仓库失败"),
            )
            return

        self.status_message.emit("定时任务触发：正在执行每日分析")
        self.run_analysis()

    # ------------------------------------------------------------------ #
    def _on_error(self, error: str, title: str) -> None:
        logger.error("%s: %s", title, error)
        self.set_busy(False, f"{title}：{error}")
