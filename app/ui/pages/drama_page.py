"""AI 短剧工坊页（扩展方向二）。

流程：一句话梗概 → 分集大纲 → 分集剧本 → 镜头级分镜（含文生图/文生视频提示词）。
左侧为项目表单与生成操作，右上为分集与剧本，右下为分镜表。
多模态能力（文生图/文生视频/配音/自动剪辑）以「预留」状态呈现，接入后即可启用。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.drama import GENRES
from app.ui.context import AppContext
from app.ui.widgets.cards import (
    Badge,
    ModuleCard,
    SegmentBar,
    hint_label,
    muted_label,
)
from app.ui.widgets.tables import Column, DictTableModel, configure_table

STORYBOARD_COLUMNS = [
    Column("scene_no", "镜号", 56, None, Qt.AlignCenter),
    Column("shot_type", "景别", 60, None, Qt.AlignCenter),
    Column("duration_sec", "时长", 56, lambda v: f"{int(v)}s", Qt.AlignRight | Qt.AlignVCenter),
    Column("description", "画面描述", 260),
    Column("dialogue", "台词", 180),
    Column("image_prompt", "文生图提示词（预留）", 220),
]


class DramaPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.current_project_id: int | None = None
        self._build()
        context.settings_changed.connect(self.refresh_status)

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("AI 短剧工坊")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addWidget(muted_label("梗概 → 大纲 → 剧本 → 分镜（含多模态提示词）· 多模态能力已预留接口"))
        header.addStretch(1)
        self.status_label = muted_label("")
        header.addWidget(self.status_label)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_form_card())
        splitter.addWidget(self._build_workspace())
        splitter.setSizes([360, 1000])
        root.addWidget(splitter, 1)

    def _build_form_card(self) -> QWidget:
        card = ModuleCard("短剧项目")
        card.body_layout.setSpacing(8)

        card.add_widget(muted_label("项目"))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        self.project_box = QComboBox()
        self.project_box.currentIndexChanged.connect(self._on_project_changed)
        row_layout.addWidget(self.project_box, 1)
        self.new_button = QPushButton("新建")
        self.new_button.clicked.connect(self._create_project)
        row_layout.addWidget(self.new_button)
        card.add_widget(row)

        card.add_widget(muted_label("剧名"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例如：面试当天，我拿到了老板的把柄")
        card.add_widget(self.title_edit)

        card.add_widget(muted_label("题材"))
        self.genre_box = QComboBox()
        self.genre_box.addItems(GENRES)
        card.add_widget(self.genre_box)

        card.add_widget(muted_label("目标平台 / 画幅"))
        self.platform_bar = SegmentBar(
            [("抖音", "douyin"), ("B站", "bilibili")], current="douyin"
        )
        card.add_widget(self.platform_bar)
        self.aspect_box = QComboBox()
        self.aspect_box.addItems(["9:16", "16:9", "1:1"])
        card.add_widget(self.aspect_box)

        card.add_widget(muted_label("一句话梗概"))
        self.logline_edit = QPlainTextEdit()
        self.logline_edit.setPlaceholderText("主角 + 目标 + 阻碍 + 反转")
        self.logline_edit.setMinimumHeight(72)
        card.add_widget(self.logline_edit)

        card.add_widget(muted_label("视觉风格（用于多模态提示词）"))
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("真实都市夜景 / 冷色高对比 / 手持镜头")
        card.add_widget(self.style_edit)

        counts = QWidget()
        counts_layout = QHBoxLayout(counts)
        counts_layout.setContentsMargins(0, 0, 0, 0)
        counts_layout.setSpacing(6)
        counts_layout.addWidget(QLabel("集数"))
        self.episode_spin = QSpinBox()
        self.episode_spin.setRange(1, 30)
        self.episode_spin.setValue(6)
        counts_layout.addWidget(self.episode_spin)
        counts_layout.addWidget(QLabel("镜头数"))
        self.shot_spin = QSpinBox()
        self.shot_spin.setRange(4, 60)
        self.shot_spin.setValue(12)
        counts_layout.addWidget(self.shot_spin)
        counts_layout.addStretch(1)
        card.add_widget(counts)

        self.force_local_box = QCheckBox("仅用本地模板生成")
        card.add_widget(self.force_local_box)

        for label, handler, object_name in (
            ("① 生成分集大纲", self._generate_outline, "AiButton"),
            ("② 生成分集剧本", self._generate_script, "AiButton"),
            ("③ 生成镜头分镜", self._generate_storyboard, "AiButton"),
        ):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(handler)
            card.add_widget(button)

        card.add_widget(hint_label("提示：先新建项目并填写梗概，再按 ①②③ 顺序生成。"))
        card.body_layout.addStretch(1)
        return card

    def _build_workspace(self) -> QWidget:
        splitter = QSplitter(Qt.Vertical)

        top = QSplitter(Qt.Horizontal)
        self.episode_card = ModuleCard("分集与剧本")
        episode_body = QWidget()
        episode_layout = QHBoxLayout(episode_body)
        episode_layout.setContentsMargins(0, 0, 0, 0)
        episode_layout.setSpacing(8)
        self.episode_list = QListWidget()
        self.episode_list.setObjectName("PlainList")
        self.episode_list.setMaximumWidth(220)
        self.episode_list.currentRowChanged.connect(self._on_episode_changed)
        episode_layout.addWidget(self.episode_list)
        self.script_view = QTextBrowser()
        self.script_view.setPlaceholderText("选择分集后显示大纲与剧本；点击「生成分集剧本」可产出完整分场。")
        episode_layout.addWidget(self.script_view, 1)
        self.episode_card.add_widget(episode_body, 1)
        top.addWidget(self.episode_card)

        self.roadmap_card = ModuleCard("多模态与成片能力（预留）")
        self.roadmap_card.setMaximumWidth(320)
        self.roadmap_list = QListWidget()
        self.roadmap_list.setObjectName("LogList")
        self.roadmap_list.setWordWrap(True)
        self.roadmap_card.add_widget(self.roadmap_list, 1)
        self.preview_button = QPushButton("生成关键帧（预留）")
        self.preview_button.setEnabled(False)
        self.preview_button.setToolTip("接入文生图模型后启用：分镜已保存 image_prompt")
        self.roadmap_card.add_widget(self.preview_button)
        self.clip_button = QPushButton("生成镜头片段（预留）")
        self.clip_button.setEnabled(False)
        self.clip_button.setToolTip("接入文生视频模型后启用：分镜已保存 video_prompt")
        self.roadmap_card.add_widget(self.clip_button)
        top.addWidget(self.roadmap_card)
        top.setSizes([760, 320])
        splitter.addWidget(top)

        self.storyboard_card = ModuleCard("镜头分镜表")
        self.storyboard_model = DictTableModel(STORYBOARD_COLUMNS)
        self.storyboard_table = QTableView()
        self.storyboard_table.setModel(self.storyboard_model)
        configure_table(self.storyboard_table, row_height=32, stretch_column=3)
        self.storyboard_card.add_widget(self.storyboard_table, 1)
        splitter.addWidget(self.storyboard_card)
        splitter.setSizes([420, 420])
        return splitter

    # ------------------------------------------------------------------ #
    def refresh_status(self) -> None:
        self.status_label.setText(self.context.drama.status_text())
        self._render_roadmap()

    def refresh(self) -> None:
        self._reload_projects()

    def _render_roadmap(self) -> None:
        self.roadmap_list.clear()
        for item in self.context.drama.multimodal_roadmap():
            entry = QListWidgetItem(f"● {item['name']}［{item['status']}］\n    {item['hint']}")
            self.roadmap_list.addItem(entry)

    # ------------------------------------------------------------------ #
    def _reload_projects(self) -> None:
        projects = self.context.drama.projects()
        self.project_box.blockSignals(True)
        self.project_box.clear()
        for project in projects:
            self.project_box.addItem(
                f"{project['title']}（{project['genre']} · {project['episode_count']} 集）", project["id"]
            )
        self.project_box.blockSignals(False)
        if projects:
            self.current_project_id = self.project_box.currentData() or projects[0]["id"]
            self._load_project(self.current_project_id)
        else:
            self.current_project_id = None
            self.episode_list.clear()
            self.script_view.setPlainText("尚未创建短剧项目：请在左侧填写剧名与梗概后点击「新建」。")
            self.storyboard_model.set_rows([])

    def _load_project(self, project_id: int | None) -> None:
        if not project_id:
            return
        project = self.context.drama.project(project_id)
        if not project:
            return
        self.title_edit.setText(project["title"])
        index = self.genre_box.findText(project["genre"])
        if index >= 0:
            self.genre_box.setCurrentIndex(index)
        self.platform_bar.set_current(project["target_platform"])
        aspect_index = self.aspect_box.findText(project["aspect_ratio"])
        if aspect_index >= 0:
            self.aspect_box.setCurrentIndex(aspect_index)
        self.logline_edit.setPlainText(project.get("logline") or "")
        self.style_edit.setText(project.get("style") or "")

        episodes = self.context.drama.episodes(project_id)
        self.episode_list.clear()
        for episode in episodes:
            self.episode_list.addItem(
                QListWidgetItem(f"第 {episode['episode_no']} 集 · {episode['title'][:16]}")
            )
        if episodes:
            self.episode_list.setCurrentRow(0)
            self._on_episode_changed(0)
        else:
            self.script_view.setPlainText("该项目还没有分集大纲，请点击「① 生成分集大纲」。")
        self.storyboard_model.set_rows([])

    def _on_project_changed(self, _index: int) -> None:
        self.current_project_id = self.project_box.currentData()
        self._load_project(self.current_project_id)

    def _on_episode_changed(self, row: int) -> None:
        if row < 0 or not self.current_project_id:
            return
        episodes = self.context.drama.episodes(self.current_project_id)
        if row >= len(episodes):
            return
        episode = episodes[row]
        parts = [
            f"## 第 {episode['episode_no']} 集 · {episode['title']}",
            "",
            f"**前 3 秒钩子**：{episode.get('hook') or '—'}",
            f"**结尾悬念**：{episode.get('cliffhanger') or '—'}",
            "",
            "### 大纲",
            episode.get("outline") or "（暂无）",
        ]
        if episode.get("script"):
            parts += ["", "### 剧本", episode["script"]]
        self.script_view.setMarkdown("\n".join(parts))
        scenes = self.context.drama.scenes(self.current_project_id, episode["episode_no"])
        self.storyboard_model.set_rows(scenes)
        self.storyboard_card.set_subtitle(
            f"第 {episode['episode_no']} 集 · {len(scenes)} 个镜头"
            + ("（含文生图/文生视频提示词）" if scenes else "")
        )

    # ------------------------------------------------------------------ #
    def _create_project(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.information(self, "缺少剧名", "请先填写剧名。")
            return
        project_id = self.context.drama.create(
            title=title,
            genre=self.genre_box.currentText(),
            target_platform=self.platform_bar.current_key() or "douyin",
            aspect_ratio=self.aspect_box.currentText(),
            logline=self.logline_edit.toPlainText().strip(),
            style=self.style_edit.text().strip(),
        )
        self.context.status_message.emit(f"已创建短剧项目：{title}")
        self.context.data_changed.emit()
        self.current_project_id = project_id
        self._reload_projects()

    def _guard_project(self) -> int | None:
        if not self.current_project_id:
            QMessageBox.information(self, "缺少项目", "请先新建一个短剧项目。")
            return None
        return int(self.current_project_id)

    def _set_busy(self, busy: bool, message: str) -> None:
        for child in self.findChildren(QPushButton):
            if child.objectName() in ("AiButton",) or child is self.new_button:
                child.setEnabled(not busy)
        self.context.set_busy(busy, message)

    def _generate_outline(self) -> None:
        project_id = self._guard_project()
        if project_id is None:
            return
        self._set_busy(True, "正在生成分集大纲…")
        self.context.runner.submit(
            self.context.drama.generate_outline,
            self._on_outline_done,
            self._on_error,
            project_id,
            self.episode_spin.value(),
            self.force_local_box.isChecked(),
        )

    def _on_outline_done(self, result: dict[str, Any]) -> None:
        self._set_busy(False, f"大纲已生成（{self._source_text(result)}），共 {len(result.get('episodes', []))} 集")
        self._load_project(self.current_project_id)

    def _generate_script(self) -> None:
        project_id = self._guard_project()
        row = self.episode_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "缺少分集", "请先生成大纲并选择一个分集。")
            return
        episodes = self.context.drama.episodes(project_id)
        episode_no = episodes[row]["episode_no"]
        self._set_busy(True, f"正在生成第 {episode_no} 集剧本…")
        self.context.runner.submit(
            self.context.drama.generate_script,
            self._on_script_done,
            self._on_error,
            project_id,
            episode_no,
            self.force_local_box.isChecked(),
        )

    def _on_script_done(self, result: dict[str, Any]) -> None:
        self._set_busy(False, f"剧本已生成（{self._source_text(result)}）")
        self._load_project(self.current_project_id)

    def _generate_storyboard(self) -> None:
        project_id = self._guard_project()
        row = self.episode_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "缺少分集", "请先生成大纲并选择一个分集。")
            return
        episodes = self.context.drama.episodes(project_id)
        episode_no = episodes[row]["episode_no"]
        self._set_busy(True, f"正在生成第 {episode_no} 集分镜…")
        self.context.runner.submit(
            self.context.drama.generate_storyboard,
            self._on_storyboard_done,
            self._on_error,
            project_id,
            episode_no,
            self.shot_spin.value(),
            self.force_local_box.isChecked(),
        )

    def _on_storyboard_done(self, result: dict[str, Any]) -> None:
        scenes = result.get("scenes") or []
        self._set_busy(False, f"分镜已生成（{self._source_text(result)}），共 {len(scenes)} 个镜头")
        self._on_episode_changed(self.episode_list.currentRow())

    def _on_error(self, error: str) -> None:
        self._set_busy(False, f"生成失败：{error}")

    @staticmethod
    def _source_text(result: dict[str, Any]) -> str:
        if result.get("is_fallback"):
            return "本地模板"
        return f"{result.get('provider')}/{result.get('model')}"
