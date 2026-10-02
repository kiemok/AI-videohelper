"""AI 咨询面板：可嵌入任意位置，并与「AI 决策助手」页共用同一会话。

- 右侧常驻面板（``compact=True``）：任何页面都能直接提问，不打断当前操作
- AI 决策助手页（``compact=False``）：完整版，附带快捷问题与状态行

消息通过 ``AppContext.chat_message`` 信号广播，因此两个入口的对话内容始终一致；
提问统一走 ``AppContext.ask_ai()``，会话上下文（history / session_id）也由上下文持有。
"""

from __future__ import annotations

import html

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QWidget,
)

from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.cards import Badge, ModuleCard, muted_label

#: 快捷提问：覆盖"双平台对比 / 选题 / 归因 / 口碑"四类高频问题
QUICK_QUESTIONS: tuple[str, ...] = (
    "抖音和B站哪个平台互动更好？",
    "我这一周应该优先做哪几个选题？",
    "为什么上周视频播放量下降了？",
    "评论区主要在意什么？",
)


class AiChatPanel(ModuleCard):
    def __init__(
        self, context: AppContext, compact: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            "AI 咨询" if compact else "创作顾问 Copilot",
            "已融合 B站 + 抖音数据",
            parent=parent,
        )
        self.context = context
        self.compact = compact

        self.badge = Badge("RAG 上下文", "violet")
        self.add_header_widget(self.badge)
        if compact:
            new_chat = QPushButton("新会话")
            new_chat.setObjectName("Segment")
            new_chat.setToolTip("清空对话上下文，开启新一轮咨询")
            new_chat.clicked.connect(context.reset_chat)
            self.add_header_widget(new_chat)

        self.view = QTextBrowser()
        self.view.setPlaceholderText("向 AI 提问：回答会结合当前分析结果与评论数据。")
        self.add_widget(self.view, 1)

        self.status_label = muted_label("")
        self.add_widget(self.status_label)

        input_row = QWidget()
        row_layout = QHBoxLayout(input_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText("例如：为什么上周视频播放量下降了？")
        self.question_edit.returnPressed.connect(self.ask)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.clicked.connect(self.ask)
        row_layout.addWidget(self.question_edit, 1)
        row_layout.addWidget(self.send_button)
        self.add_widget(input_row)

        quick_row = QWidget()
        quick_layout = QHBoxLayout(quick_row)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(6)
        picks = QUICK_QUESTIONS[:2] if compact else QUICK_QUESTIONS[:3]
        for question in picks:
            button = QPushButton(question if len(question) <= 14 else question[:13] + "…")
            button.setObjectName("Segment")
            button.setToolTip(question)
            button.clicked.connect(
                lambda _checked=False, text=question: self.ask_preset(text)
            )
            quick_layout.addWidget(button)
        quick_layout.addStretch(1)
        self.add_widget(quick_row)

        self.force_local_box = QCheckBox("仅用本地规则生成（不调用大模型 API）")
        self.add_widget(self.force_local_box)

        context.chat_message.connect(self._on_chat_message)
        context.settings_changed.connect(self.refresh_status)
        context.metrics_updated.connect(lambda _metrics: self.refresh_status())
        context.skills_changed.connect(self.refresh_status)

        self._append_system(
            "你好，我是你的内容创作助手。在任意页面都可以向我提问，"
            "回答会结合当前的双平台分析结果与评论数据。"
        )
        self.refresh_status()

    # ------------------------------------------------------------------ #
    def ask_preset(self, question: str) -> None:
        """用快捷问题发起咨询。"""
        self.question_edit.setText(question)
        self.ask()

    def ask(self) -> None:
        """提交输入框中的问题（走 AppContext 统一入口）。"""
        question = self.question_edit.text().strip()
        if not question:
            return
        self.question_edit.clear()
        self.context.ask_ai(question, self.force_local_box.isChecked())

    def refresh_status(self) -> None:
        status = self.context.insights.status()
        has_metrics = bool(self.context.metrics)
        model = (
            f"{status['provider_label']} / {status['model']}"
            if status["configured"]
            else "本地规则引擎"
        )
        context_text = self.context.metrics.get("stat_date") if has_metrics else "未挂载"
        skills = len(self.context.settings.skills_enabled or [])
        tools = self.context.toolbox_summary()
        self.status_label.setText(
            f"模型：{model}｜数据上下文：{context_text}｜技能 {skills} 个｜{tools}"
        )
        self.badge.setText("RAG 上下文" if has_metrics else "未挂载数据")
        self.badge.set_tone("violet" if has_metrics else "muted")

    # ------------------------------------------------------------------ #
    def _on_chat_message(self, role: str, content: str, is_fallback: bool) -> None:
        if role == "reset":
            self.view.clear()
            self._append_system("已开启新的会话，请提出你的问题。")
            return
        if role == "user":
            self._append_user(content)
        elif role == "assistant":
            self._append_assistant(content, is_fallback)

    def _append_system(self, text: str) -> None:
        self.view.append(
            f"<p style='color:{COLORS['text_muted']}'>{html.escape(text)}</p>"
        )

    def _append_user(self, text: str) -> None:
        self.view.append("<p><b>🧑 我</b></p>")
        self.view.append(html.escape(text).replace("\n", "<br/>"))
        self._scroll_to_bottom()

    def _append_assistant(self, text: str, is_fallback: bool) -> None:
        prefix = "🤖 Copilot" + ("（本地规则引擎）" if is_fallback else "")
        self.view.append(f"<p><b>{prefix}</b></p>")
        document = QTextDocument()
        document.setMarkdown(text)
        self.view.append(document.toHtml())
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
