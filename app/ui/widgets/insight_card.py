"""AI 快速创作洞察摘要卡片：数据看板与 AI 决策助手页共用。

- 内容来自最近一次「数据简报」（``context.latest_brief()``，落库在 ``ai_report`` 表）
- ``action="goto_ai"``：按钮跳转到「AI 决策助手」页深入解读（数据看板使用）
- ``action="generate"``：按钮就地生成 / 刷新一份简报（AI 决策助手页使用）
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QPushButton, QTextBrowser, QWidget

from app.ui.context import AppContext
from app.ui.widgets.cards import Badge, ModuleCard

#: 「AI 决策助手」页在导航中的位置（用于跳转）
_AI_PAGE_ROW = 2


class InsightBriefCard(ModuleCard):
    def __init__(
        self, context: AppContext, action: str = "goto_ai", parent: QWidget | None = None
    ) -> None:
        super().__init__("AI 快速创作洞察摘要", "", parent=parent)
        self.context = context
        self.action = action

        self.badge = Badge("待生成", "muted")
        self.add_header_widget(self.badge)

        self.view = QTextBrowser()
        self.view.setPlaceholderText("尚未生成洞察摘要，点击下方按钮即可基于当日分析结果生成。")
        self.add_widget(self.view, 1)

        self.button = QPushButton()
        self.button.setObjectName("AiButton")
        if action == "generate":
            self.button.setText("生成 / 刷新洞察摘要")
            self.button.clicked.connect(self.generate)
        else:
            self.button.setText("进入 AI 助手深入解读 →")
            self.button.clicked.connect(self._goto_ai)
        self.add_widget(self.button)

        context.report_updated.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """回显最近一份简报（不重新调用大模型）。"""
        report = self.context.latest_brief()
        if report and report.get("content"):
            is_fallback = bool(report.get("is_fallback"))
            source = (
                "本地规则引擎"
                if is_fallback
                else f"{report.get('provider')}/{report.get('model')}"
            )
            self.view.setMarkdown(report["content"])
            self.set_subtitle(f"{str(report.get('generated_at'))[:16]}｜{source}")
            self.badge.setText("已生成")
            self.badge.set_tone("muted" if is_fallback else "cyan")
        else:
            self.view.setPlainText(
                "还没有 AI 洞察摘要：点击下方按钮生成（结果会写入报告库，并在数据看板同步回显）。"
            )
            self.set_subtitle("")
            self.badge.setText("待生成")
            self.badge.set_tone("muted")

    # ------------------------------------------------------------------ #
    def generate(self) -> None:
        """就地生成 / 刷新简报（落库后所有展示位通过 report_updated 同步）。"""
        metrics = self.context.insights.current_metrics(self.context.metrics)
        self._set_busy(True)
        self.context.set_busy(True, "正在生成洞察摘要…")

        def job() -> dict[str, Any]:
            return self.context.insights.daily_brief(metrics)

        def done(result: dict[str, Any]) -> None:
            self._set_busy(False)
            source = (
                "本地规则引擎"
                if result.get("is_fallback")
                else f"{result.get('provider')}/{result.get('model')}"
            )
            self.context.set_busy(False, f"洞察摘要已生成（{source}）")
            self.context.report_updated.emit()

        def failed(error: str) -> None:
            self._set_busy(False)
            self.context.set_busy(False, f"生成失败：{error}")

        self.context.runner.submit(job, done, failed)

    def _set_busy(self, busy: bool) -> None:
        if self.action != "generate":
            return
        self.button.setEnabled(not busy)
        self.button.setText("生成中…" if busy else "生成 / 刷新洞察摘要")

    def _goto_ai(self) -> None:
        window = self.window()
        if hasattr(window, "nav"):
            window.nav.setCurrentRow(_AI_PAGE_ROW)
