"""视频创作咨询页（扩展方向一）。

布局：左侧咨询输入（分类 + 问题 + 创作者补充信息 + 快捷模板），
右侧建议正文与要点，底部为历史咨询记录。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.consulting import CATEGORIES, CATEGORY_LABELS
from app.ui.context import AppContext
from app.ui.export_helper import ExportActions, ExportPayload
from app.ui.widgets.responsive import PageScrollArea, ResponsiveSplitter
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import (
    ModuleCard,
    SegmentBar,
    chip,
    hint_label,
    hstack,
    muted_label,
)

QUICK_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("下一条拍什么", "结合当前数据，我这一周应该优先做哪几个选题？请给出理由与预期指标。"),
    ("开头怎么改", "我的内容前 3 秒留存可能不够，请根据数据给出 3 个具体的开头改写方案。"),
    ("标题优化", "请帮我把最近表现最好的作品标题改写成更适合抖音和B站的两个版本。"),
    ("账号定位", "请判断我当前账号的定位是否清晰，并给出双平台的差异化表达建议。"),
    ("增长瓶颈", "我的播放和涨粉表现如何？当前最大的增长瓶颈是什么，怎么突破？"),
    ("商业化", "根据互动率和评论意图，判断我现在的变现方向是否合适。"),
)


class ConsultingPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._last_result: dict[str, Any] = {}
        self._build()
        context.settings_changed.connect(self.refresh_status)
        context.metrics_updated.connect(lambda _m: self.refresh_status())

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = PageScrollArea()
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        header = ToolbarRow()
        title = header.add(QLabel("视频创作咨询"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")
        header.add(
            muted_label("把数据结论翻译成可执行的创作方案 · 支持账号定位/脚本/标题/增长/商业化"),
            ToolbarRow.LOW,
        )
        header.add_stretch()
        self.status_label = header.add(muted_label(""), ToolbarRow.NORMAL)
        root.addWidget(header)

        splitter = ResponsiveSplitter(
            threshold=820,
            horizontal_sizes=[520, 760],
            vertical_sizes=[560, 620],
            stacked_min_height=1200,
        )
        splitter.addWidget(self._build_input_card())
        splitter.addWidget(self._build_output_card())
        root.addWidget(splitter, 3)

        self.history_card = ModuleCard("历史咨询记录")
        self.history_list = QListWidget()
        self.history_list.setObjectName("LogList")
        self.history_list.setWordWrap(True)
        self.history_list.itemClicked.connect(self._on_history_clicked)
        self.history_card.add_widget(self.history_list, 1)
        root.addWidget(self.history_card, 2)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_input_card(self) -> QWidget:
        card = ModuleCard("咨询输入")
        card.body_layout.setSpacing(10)

        card.add_widget(muted_label("咨询类型"))
        self.category_bar = SegmentBar(list(CATEGORIES), current="general")
        card.add_widget(self.category_bar)

        card.add_widget(muted_label("你的问题"))
        self.question_edit = QPlainTextEdit()
        self.question_edit.setPlaceholderText("例如：这周该优先做哪几个选题？我的开头是不是太平了？")
        self.question_edit.setMinimumHeight(120)
        card.add_widget(self.question_edit, 1)

        card.add_widget(muted_label("创作者补充信息（可选）"))
        self.profile_edit = QLineEdit()
        self.profile_edit.setPlaceholderText("账号方向、目标受众、可投入产能等")
        card.add_widget(self.profile_edit)

        card.add_widget(muted_label("快捷模板"))
        templates = QWidget()
        template_layout = QVBoxLayout(templates)
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(6)
        for index in range(0, len(QUICK_TEMPLATES), 3):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            for label, _text in QUICK_TEMPLATES[index : index + 3]:
                button = QPushButton(label)
                button.setObjectName("Segment")
                button.clicked.connect(lambda _checked=False, key=label: self._apply_template(key))
                row_layout.addWidget(button)
            row_layout.addStretch(1)
            template_layout.addWidget(row)
        card.add_widget(templates)

        self.force_local_box = QCheckBox("仅用本地规则引擎（不调用大模型 API）")
        card.add_widget(self.force_local_box)

        self.generate_button = QPushButton("生成咨询建议")
        self.generate_button.setObjectName("AiButton")
        self.generate_button.clicked.connect(self._generate)
        card.add_widget(self.generate_button)
        return card

    def _build_output_card(self) -> QWidget:
        card = ModuleCard("咨询建议")
        self.output_view = QTextBrowser()
        self.output_view.setPlaceholderText("生成后在此显示：直接结论 / 依据 / 执行方案 / 风险提示")
        card.add_widget(self.output_view, 1)

        self.material_label = muted_label("RAG 参考素材：暂无（生成建议时自动检索本地作品与评论）")
        self.material_label.setWordWrap(False)
        card.add_widget(self.material_label)
        self.material_list = QListWidget()
        self.material_list.setObjectName("LogList")
        self.material_list.setWordWrap(True)
        self.material_list.setMaximumHeight(132)
        card.add_widget(self.material_list)

        self.highlights_row = QWidget()
        self.highlights_layout = QHBoxLayout(self.highlights_row)
        self.highlights_layout.setContentsMargins(0, 0, 0, 0)
        self.highlights_layout.setSpacing(6)
        self.highlights_layout.addStretch(1)
        card.add_widget(self.highlights_row)
        card.add_widget(ExportActions(self._export_payload, self.context.status_message.emit))
        return card

    # ------------------------------------------------------------------ #
    def refresh_status(self) -> None:
        service = self.context.consulting
        has_data = bool(self.context.metrics)
        rag = "RAG 检索已启用" if self.context.settings.consulting_rag_enabled else "RAG 检索已关闭"
        self.status_label.setText(
            f"数据上下文：{'已就绪' if has_data else '暂无（请先执行分析）'}"
            f"｜{service.status_text()}｜{rag}"
        )
        self.refresh()

    def refresh(self) -> None:
        records = self.context.consulting.history(limit=40)
        self.history_list.clear()
        if not records:
            self.history_list.addItem(QListWidgetItem("暂无咨询记录"))
            return
        for record in records:
            source = "本地规则" if record.get("is_fallback") else f"{record.get('provider')}/{record.get('model')}"
            item = QListWidgetItem(
                f"[{str(record.get('created_at'))[:16]}] {record.get('question', '')[:60]}\n"
                f"    来源：{source}"
            )
            item.setData(Qt.UserRole, record)
            self.history_list.addItem(item)

    # ------------------------------------------------------------------ #
    def _apply_template(self, key: str) -> None:
        for label, text in QUICK_TEMPLATES:
            if label == key:
                self.question_edit.setPlainText(text)
                break

    def _set_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled(not busy)
        self.generate_button.setText("生成中…" if busy else "生成咨询建议")

    def _generate(self) -> None:
        question = self.question_edit.toPlainText().strip()
        if not question:
            self.output_view.setPlainText("请先填写你的问题，或点击上方快捷模板。")
            return
        self._set_busy(True)
        self.context.set_busy(True, "正在生成创作咨询建议…")
        self.context.runner.submit(
            self.context.consulting.advise,
            self._on_done,
            self._on_error,
            question,
            self.category_bar.current_key() or "general",
            self.context.metrics,
            self.profile_edit.text(),
            self.force_local_box.isChecked(),
            use_rag=self.context.settings.consulting_rag_enabled,
        )

    def _on_done(self, result: dict[str, Any]) -> None:
        self._set_busy(False)
        self._last_result = result
        source = "本地规则引擎" if result.get("is_fallback") else f"{result.get('provider')}/{result.get('model')}"
        self.context.set_busy(False, f"咨询建议已生成（{source}）")
        self.output_view.setMarkdown(result.get("answer", ""))
        self._render_highlights(result.get("highlights") or [])
        self._render_materials(result.get("materials") or [])
        self.refresh()

    def _on_error(self, error: str) -> None:
        self._set_busy(False)
        self.context.set_busy(False, f"咨询生成失败：{error}")
        self.output_view.setPlainText(f"生成失败：{error}")

    # ------------------------------------------------------------------ #
    # 导出：咨询建议（含问题、类型、RAG 素材与生成方式）
    # ------------------------------------------------------------------ #
    def _export_payload(self) -> ExportPayload | None:
        answer = self.output_view.toMarkdown().strip()
        if not answer or not self._last_result:
            return None
        result = self._last_result
        category = str(result.get("category") or self.category_bar.current_key() or "general")
        label = CATEGORY_LABELS.get(category, category)
        materials = result.get("materials") or []
        parts = [
            f"## 咨询问题\n{result.get('question') or ''}",
            f"## 咨询类型\n{label}",
            f"## 建议正文\n{answer}",
        ]
        if materials:
            parts.append(
                "## RAG 检索素材（BM25）\n"
                + "\n".join(
                    f"{index}. [{item.get('kind')}] {item.get('text')}（BM25 {item.get('score')}）"
                    for index, item in enumerate(materials, 1)
                )
            )
        provider = (
            "本地规则引擎"
            if result.get("is_fallback")
            else f"{result.get('provider')} / {result.get('model')}"
        )
        return ExportPayload(
            title="视频创作咨询建议",
            stem=f"创作咨询_{label}",
            body="\n\n".join(parts),
            meta={"咨询类型": label, "生成方式": provider, "检索素材": f"{len(materials)} 条"},
        )

    def _render_highlights(self, highlights: list[str]) -> None:
        while self.highlights_layout.count() > 1:
            item = self.highlights_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, text in enumerate(highlights[:6]):
            self.highlights_layout.insertWidget(index, chip(text, "cyan" if index % 2 else "violet"))

    def _render_materials(self, materials: list[dict[str, Any]]) -> None:
        """展示本次 RAG 检索命中的素材（BM25 得分 + 原文摘要）。"""
        self.material_list.clear()
        if not materials:
            self.material_label.setText(
                "RAG 参考素材：本次未命中"
                + ("（已在设置中关闭检索增强）" if not self.context.settings.consulting_rag_enabled else "")
            )
            return
        self.material_label.setText(
            f"RAG 参考素材：命中 {len(materials)} 条（BM25 检索本地数据仓库，已注入提示词）"
        )
        for material in materials:
            kind = material.get("kind", "素材")
            text = str(material.get("text") or "")[:120]
            score = material.get("score")
            self.material_list.addItem(QListWidgetItem(f"[{kind}] {text}（BM25 {score}）"))

    def _on_history_clicked(self, item: QListWidgetItem) -> None:
        record = item.data(Qt.UserRole)
        if not isinstance(record, dict):
            return
        self.question_edit.setPlainText(record.get("question", ""))
        self.output_view.setMarkdown(record.get("answer", ""))
        self._render_highlights(record.get("highlights") or [])
        self._render_materials([])
