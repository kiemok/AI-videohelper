"""每日定时任务（APScheduler）。

基础功能阶段：到点后触发一次「本地分析」（爬虫接入后将先采集再分析）。
调度器跑在后台线程，通过 Qt 信号把「该干活了」通知回主线程，
由主线程安全地调用界面与数据库操作。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core.logging_setup import get_logger

logger = get_logger(__name__)


def parse_hhmm(text: str) -> tuple[int, int] | None:
    """解析 ``HH:MM``，非法输入返回 None。"""
    try:
        hour_text, minute_text = str(text).strip().split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


class DailyScheduler(QObject):
    """按每天固定时间触发一次的轻量调度器。"""

    due = Signal()  # 到点了（接收者应执行采集/分析）

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scheduler = None

    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    def start(self, time_text: str) -> tuple[bool, str]:
        """启动每日任务；返回 (是否成功, 说明文本)。"""
        parsed = parse_hhmm(time_text)
        if parsed is None:
            return False, f"时间格式不正确（需要 HH:MM）：{time_text!r}"
        hour, minute = parsed
        self.stop()

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as exc:  # 依赖缺失时不影响主流程
            return False, f"未安装 APScheduler，定时任务不可用：{exc}"

        scheduler = BackgroundScheduler(daemon=True, timezone="Asia/Shanghai")
        scheduler.add_job(
            self._on_tick,
            CronTrigger(hour=hour, minute=minute),
            id="daily-analysis",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info("每日定时任务已启动：%02d:%02d", hour, minute)
        return True, f"已启动：每天 {hour:02d}:{minute:02d} 自动执行"

    def stop(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as exc:  # noqa: BLE001 - 关闭失败不影响退出
                logger.warning("关闭定时任务失败: %s", exc)
            self._scheduler = None

    def next_run_text(self) -> str:
        if not self._scheduler:
            return "未启用"
        jobs = self._scheduler.get_jobs()
        if not jobs or jobs[0].next_run_time is None:
            return "未启用"
        return jobs[0].next_run_time.strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------ #
    def _on_tick(self) -> None:
        """后台线程回调：只发信号，实际逻辑在主线程执行。"""
        logger.info("定时任务触发：准备执行每日分析")
        self.due.emit()
