"""AI 决策助手页（对齐设计稿 `ai 决策助手`）。

- 顶部：模型引擎状态条（引擎 / 上下文挂载 / 离线规则引擎）
- 左栏：爆款选题生成与建议矩阵（选题建议 / 标题优化 / 发布时机）
- 右栏：AI 快速创作洞察摘要（与数据看板共用组件；对话由窗口右侧常驻面板承担）

注：「智能数据决策简报」已按需求移除 —— 同类的"数据解读"能力由右侧的
「AI 快速创作洞察摘要」与右侧常驻 AI 咨询面板承担；大模型 API 配置改由
右侧 AI 咨询面板顶部的 ⚙ 图标打开（设置页仍保留同一份配置）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.insight_card import InsightBriefCard
from app.ui.export_helper import ExportActions, ExportPayload
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import ModuleCard, Pill, StatusDot


class AiPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._last_reports: dict[str, dict[str, Any]] = {}
        self._last_topic_kind = ""
        self._build()
        context.settings_changed.connect(self.refresh_status)
        context.metrics_updated.connect(lambda _metrics: self.refresh_status())

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        root.addWidget(self._build_engine_bar())

        splitter = QSplitter(Qt.Horizontal)
        # 左栏：爆款选题与建议矩阵（原「智能数据决策简报」已移除，此处独占左栏）
        splitter.addWidget(self._build_topic_card())
        # 右栏：AI 快速创作洞察摘要（与「数据看板」共用同一组件与同一份简报数据）；
        # 对话咨询由窗口右侧的常驻 AI 面板承担，此处不再重复嵌入聊天窗口。
        self.insight_card = InsightBriefCard(self.context, action="generate")
        splitter.addWidget(self.insight_card)
        splitter.setSizes([860, 520])
        root.addWidget(splitter, 1)

    def _build_engine_bar(self) -> QWidget:
        bar = ToolbarRow(spacing=10)
        title = bar.add(QLabel("AI 决策助手"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")

        self.model_dot = StatusDot(COLORS["text_muted"])
        self.model_pill = Pill("模型引擎：未配置")
        self.context_pill = Pill("上下文：未挂载")
        self.local_pill = Pill("离线规则引擎：就绪", "cyan")
        bar.add(self.model_dot, ToolbarRow.HIGH)
        bar.add(self.model_pill, ToolbarRow.HIGH)
        bar.add(self.context_pill, ToolbarRow.NORMAL)
        bar.add(self.local_pill, ToolbarRow.NORMAL)
        bar.add_stretch()

        self.force_local_box = QCheckBox("仅用本地规则生成（不调用 API）")
        bar.add(self.force_local_box, ToolbarRow.NORMAL)
        return bar

    def _build_topic_card(self) -> QWidget:
        card = ModuleCard("爆款选题生成与建议矩阵", "选题建议 / 标题优化 / 发布时机")
        self.action_buttons: dict[str, QPushButton] = {}
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        for key, label, object_name in (
            ("topic_suggestion", "选题建议", "AiButton"),
            ("title_optimize", "标题优化", "AiButton"),
            ("publish_time", "发布时机", "AiButton"),
        ):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(lambda _checked=False, name=key: self._generate(name))
            self.action_buttons[key] = button
            row_layout.addWidget(button)
        row_layout.addStretch(1)
        card.add_widget(row)

        self.topic_view = QTextBrowser()
        self.topic_view.setPlaceholderText("生成后在此显示选题矩阵 / 标题优化 / 发布时间建议。")
        card.add_widget(self.topic_view, 1)
        card.add_widget(ExportActions(self._topic_payload, self.context.status_message.emit))
        return card

    # ------------------------------------------------------------------ #
    def refresh_status(self) -> None:
        status = self.context.insights.status()
        has_metrics = bool(self.context.metrics)
        self.model_pill.update_pill(
            f"模型引擎：{status['provider_label']} / {status['model']}"
            if status["configured"]
            else "模型引擎：本地规则",
            "violet" if status["configured"] else "muted",
        )
        self.model_dot.set_color(COLORS["violet"] if status["configured"] else COLORS["text_muted"])
        self.context_pill.update_pill(
            f"上下文：已挂载 {self.context.metrics.get('stat_date')} 数据"
            if has_metrics
            else "上下文：未挂载（请先执行分析）",
            "cyan" if has_metrics else "muted",
        )

    def _set_busy(self, busy: bool, message: str) -> None:
        for button in self.action_buttons.values():
            button.setEnabled(not busy)
        self.context.set_busy(busy, message)

    # ------------------------------------------------------------------ #
    def _generate(self, report_type: str) -> None:
        metrics = self.context.insights.current_metrics(self.context.metrics)
        force_local = self.force_local_box.isChecked()
        self._set_busy(True, "正在生成…")

        def done(result: dict[str, Any]) -> None:
            self._set_busy(False, f"生成完成（{result.get('provider')}/{result.get('model')}）")
            self._last_reports[report_type] = result
            self._last_topic_kind = report_type
            self.topic_view.setMarkdown(result.get("content", ""))
            self.refresh_status()
            self.context.report_updated.emit()

        self.context.runner.submit(
            self._dispatch, done, lambda error: self._set_busy(False, f"生成失败：{error}"),
            report_type, metrics, force_local,
        )

    def _dispatch(self, report_type: str, metrics: dict[str, Any], force_local: bool) -> dict[str, Any]:
        service = self.context.insights
        if report_type == "topic_suggestion":
            return service.suggest_topics(metrics, force_local=force_local)
        if report_type == "title_optimize":
            return service.optimize_titles(metrics=metrics, force_local=force_local)
        return service.suggest_publish_time(metrics, force_local=force_local)

    # ------------------------------------------------------------------ #
    # 导出（复制 / 导出 Markdown，统一走 data/export）
    # ------------------------------------------------------------------ #
    _REPORT_LABELS = {
        "topic_suggestion": "爆款选题建议",
        "title_optimize": "标题优化建议",
        "publish_time": "最佳发布时机建议",
    }

    def _export_meta(self, report_type: str) -> dict[str, str]:
        result = self._last_reports.get(report_type) or {}
        metrics = self.context.metrics or {}
        if result.get("is_fallback"):
            generated = "本地规则引擎"
        elif result.get("provider"):
            generated = f"{result.get('provider')} / {result.get('model')}"
        else:
            generated = "—"
        return {
            "数据口径": str(metrics.get("stat_date") or "—"),
            "数据窗口": f"近 {metrics.get('window_days') or '—'} 天",
            "生成方式": generated,
        }

    def _topic_payload(self) -> ExportPayload | None:
        content = self.topic_view.toMarkdown().strip()
        if not content or not self._last_topic_kind:
            return None
        label = self._REPORT_LABELS.get(self._last_topic_kind, "AI 生成结果")
        stat_date = str((self.context.metrics or {}).get("stat_date") or "今日")
        return ExportPayload(
            title=label,
            stem=f"{label}_{stat_date}",
            body=content,
            meta=self._export_meta(self._last_topic_kind),
        )

    # ------------------------------------------------------------------ #
    # 问答（提问与显示均由共享的 AiChatPanel 负责，见 app/ui/widgets/ai_chat.py）
    # ------------------------------------------------------------------ #
