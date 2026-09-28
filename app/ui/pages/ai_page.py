"""AI 决策助手页（对齐设计稿 `ai 决策助手`）。

- 顶部：模型引擎状态条（引擎 / 上下文挂载 / 离线规则引擎）
- 左栏：智能数据决策简报 + 爆款选题与建议矩阵
- 右栏：创作顾问 Copilot 对话（结合实时数据上下文）
- 底部：标题优化实验室 / 最佳发布时机决策 快捷入口
"""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.cards import Badge, ModuleCard, Pill, StatusDot, hint_label, muted_label

QUICK_QUESTIONS: tuple[str, ...] = (
    "抖音和B站哪个平台互动更好？",
    "我这一周应该优先做哪几个选题？",
    "为什么上周视频播放量下降了？",
    "评论区主要在意什么？",
)


class AiPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.session_id: int | None = None
        self.history: list[dict[str, str]] = []
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
        left = QSplitter(Qt.Vertical)
        left.addWidget(self._build_brief_card())
        left.addWidget(self._build_topic_card())
        left.setSizes([420, 320])
        splitter.addWidget(left)
        splitter.addWidget(self._build_chat_card())
        splitter.setSizes([860, 520])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_footer())
        self._append_chat(
            "assistant",
            "你好，我是你的内容创作助手。你可以问我关于播放、互动率、健康度、评论口碑、选题方向的问题。",
        )

    def _build_engine_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("AI 决策助手")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.model_dot = StatusDot(COLORS["text_muted"])
        self.model_pill = Pill("模型引擎：未配置")
        self.context_pill = Pill("上下文：未挂载")
        self.local_pill = Pill("离线规则引擎：就绪", "cyan")
        layout.addWidget(self.model_dot)
        layout.addWidget(self.model_pill)
        layout.addWidget(self.context_pill)
        layout.addWidget(self.local_pill)
        layout.addStretch(1)

        self.force_local_box = QCheckBox("仅用本地规则生成（不调用 API）")
        layout.addWidget(self.force_local_box)

        self.brief_button = QPushButton("生成数据简报")
        self.brief_button.setObjectName("PrimaryButton")
        self.brief_button.clicked.connect(lambda: self._generate("daily_brief"))
        layout.addWidget(self.brief_button)
        return bar

    def _build_brief_card(self) -> QWidget:
        card = ModuleCard("智能数据决策简报", "DeepSeek / 本地规则 综合生成")
        self.brief_badge = Badge("待生成", "muted")
        card.add_header_widget(self.brief_badge)
        self.report_view = QTextBrowser()
        self.report_view.setPlaceholderText("点击顶部「生成数据简报」——将基于当日双平台分析结果产出结论与行动建议。")
        card.add_widget(self.report_view, 1)
        return card

    def _build_topic_card(self) -> QWidget:
        card = ModuleCard("爆款选题生成与建议矩阵")
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
        return card

    def _build_chat_card(self) -> QWidget:
        card = ModuleCard("创作顾问 Copilot", "已融合 B站 + 抖音双端数据")
        card.add_header_widget(Badge("RAG 上下文", "violet"))
        self.chat_view = QTextBrowser()
        card.add_widget(self.chat_view, 1)

        self.chat_hint = muted_label("")
        card.add_widget(self.chat_hint)

        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)
        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText("基于当前多平台数据向 AI 提问，例如：分析为什么上周视频播放量下降了？")
        self.question_edit.returnPressed.connect(self._ask)
        input_layout.addWidget(self.question_edit, 1)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.clicked.connect(self._ask)
        input_layout.addWidget(self.send_button)
        card.add_widget(input_row)

        quick = QWidget()
        quick_layout = QHBoxLayout(quick)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(6)
        for question in QUICK_QUESTIONS[:2]:
            button = QPushButton(question)
            button.setObjectName("Segment")
            button.clicked.connect(lambda _checked=False, text=question: self._ask_preset(text))
            quick_layout.addWidget(button)
        quick_layout.addStretch(1)
        card.add_widget(quick)
        return card

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for label, key in (("标题优化实验室", "title_optimize"), ("最佳发布时机决策", "publish_time")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=key: self._generate(name))
            layout.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(hint_label("生成结果会同步写入报告库，并在「数据看板」的 AI 摘要中回显"))
        return bar

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
        self.send_button.setEnabled(not busy)
        self.brief_button.setEnabled(not busy)
        self.chat_hint.setText(message)
        self.context.set_busy(busy, message)

    # ------------------------------------------------------------------ #
    def _generate(self, report_type: str) -> None:
        metrics = self.context.insights.current_metrics(self.context.metrics)
        force_local = self.force_local_box.isChecked()
        self._set_busy(True, "正在生成…")

        def done(result: dict[str, Any]) -> None:
            self._set_busy(False, f"生成完成（{result.get('provider')}/{result.get('model')}）")
            if report_type == "daily_brief":
                self.report_view.setMarkdown(result.get("content", ""))
                self.brief_badge.setText("已生成")
                self.brief_badge.set_tone("cyan" if not result.get("is_fallback") else "muted")
            else:
                self.topic_view.setMarkdown(result.get("content", ""))
            self.refresh_status()
            self.context.report_updated.emit()

        self.context.runner.submit(
            self._dispatch, done, lambda error: self._set_busy(False, f"生成失败：{error}"),
            report_type, metrics, force_local,
        )

    def _dispatch(self, report_type: str, metrics: dict[str, Any], force_local: bool) -> dict[str, Any]:
        service = self.context.insights
        if report_type == "daily_brief":
            return service.daily_brief(metrics, force_local=force_local)
        if report_type == "topic_suggestion":
            return service.suggest_topics(metrics, force_local=force_local)
        if report_type == "title_optimize":
            return service.optimize_titles(metrics=metrics, force_local=force_local)
        return service.suggest_publish_time(metrics, force_local=force_local)

    # ------------------------------------------------------------------ #
    def _ask_preset(self, question: str) -> None:
        self.question_edit.setText(question)
        self._ask()

    def _ask(self) -> None:
        question = self.question_edit.text().strip()
        if not question:
            return
        self.question_edit.clear()
        self._append_chat("user", question)
        self._set_busy(True, "正在思考…")

        def done(result: dict[str, Any]) -> None:
            self.session_id = result.get("session_id") or self.session_id
            self.history.append({"role": "user", "content": question})
            self.history.append({"role": "assistant", "content": result.get("content", "")})
            self._append_chat("assistant", result.get("content", ""))
            self._set_busy(False, f"回答完成（{result.get('provider')}/{result.get('model')}）")

        def failed(error: str) -> None:
            self._append_chat("assistant", f"生成失败：{error}")
            self._set_busy(False, "生成失败")

        self.context.runner.submit(
            self.context.insights.ask,
            done,
            failed,
            question,
            self.context.metrics,
            list(self.history),
            self.session_id,
            self.force_local_box.isChecked(),
        )

    def _append_chat(self, role: str, content: str) -> None:
        prefix = "🧑 我" if role == "user" else "🤖 Copilot"
        self.chat_view.append(f"<p><b>{prefix}</b></p>")
        if role == "user":
            self.chat_view.append(html.escape(content).replace("\n", "<br/>"))
        else:
            document = QTextDocument()
            document.setMarkdown(content)
            self.chat_view.append(document.toHtml())
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
