"""技能与工具页：管理自定义 Skill 与 MCP 外部工具。

- 左栏：自定义技能（勾选启用 → 提示词注入 AI 咨询；可新建 / 编辑 / 删除 / 重新加载）
- 右栏：MCP 服务器（stdio / SSE 配置、启用开关、连接测试）与可用工具列表
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from app.config import McpServerSettings
from app.skills import Skill, ensure_builtin_skills, slugify
from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.responsive import PageScrollArea, ResponsiveSplitter
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import (
    Badge,
    ModuleCard,
    SegmentBar,
    hint_label,
    muted_label,
)

_TRANSPORTS: tuple[tuple[str, str], ...] = (("本地命令（stdio）", "stdio"), ("远程 SSE", "sse"))


class SkillsPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._skills: list[Skill] = []
        self._current_slug: str | None = None
        self._servers: list[McpServerSettings] = []
        self._server_index: int = -1
        self._templates: list[Any] = []
        self._prompt_key: str = ""
        self._loading = False
        self._build()
        context.skills_changed.connect(self.refresh)

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
        root.addWidget(self._build_toolbar())
        root.addWidget(
            hint_label(
                "技能（Skill）：每个技能是一个 Markdown 文件（YAML 头部 + 提示词正文），"
                "勾选启用后会注入 AI 咨询的 system prompt；"
                "MCP：把外部工具服务器接入咨询，模型可自行调用工具取更精确的数据。"
            )
        )

        splitter = ResponsiveSplitter(
            threshold=820,
            horizontal_sizes=[720, 640],
            vertical_sizes=[560, 540],
            stacked_min_height=1120,
        )
        splitter.addWidget(self._build_skill_panel())
        splitter.addWidget(self._build_mcp_panel())
        root.addWidget(splitter, 1)
        root.addWidget(self._build_prompt_card())
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_toolbar(self) -> QWidget:
        bar = ToolbarRow(spacing=8)
        title = bar.add(QLabel("技能与工具"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")
        self.dir_label = bar.add(muted_label(""), ToolbarRow.LOW)
        bar.add_stretch()

        reload_button = QPushButton("重新加载技能")
        reload_button.clicked.connect(self.refresh)
        bar.add(reload_button, ToolbarRow.HIGH)

        builtin_button = QPushButton("写入内置示例")
        builtin_button.clicked.connect(self._install_builtin)
        bar.add(builtin_button, ToolbarRow.HIGH)

        tools_button = QPushButton("刷新工具连接")
        tools_button.clicked.connect(self._refresh_tools)
        bar.add(tools_button, ToolbarRow.NORMAL)

        open_button = QPushButton("打开技能目录")
        open_button.clicked.connect(self._open_skills_dir)
        bar.add(open_button, ToolbarRow.NORMAL)
        return bar

    # ------------------------------------------------------------------ #
    # 技能
    # ------------------------------------------------------------------ #
    def _build_skill_panel(self) -> QWidget:
        card = ModuleCard("自定义技能", "勾选启用 → 注入 AI 咨询")
        self.skill_badge = Badge("0 个已启用", "cyan")
        card.add_header_widget(self.skill_badge)

        body = ResponsiveSplitter(
            threshold=620,
            horizontal_sizes=[260, 440],
            vertical_sizes=[220, 320],
            stacked_min_height=560,
        )

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.skill_list = QListWidget()
        self.skill_list.setObjectName("PlainList")
        self.skill_list.itemClicked.connect(self._on_skill_selected)
        self.skill_list.itemChanged.connect(self._on_skill_checked)
        left_layout.addWidget(self.skill_list, 1)

        skill_buttons = ToolbarRow(spacing=6)
        new_button = QPushButton("新建")
        new_button.clicked.connect(self._new_skill)
        skill_buttons.add(new_button, ToolbarRow.HIGH)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self._delete_skill)
        skill_buttons.add(delete_button, ToolbarRow.NORMAL)
        skill_buttons.add_stretch()
        left_layout.addWidget(skill_buttons)
        body.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.skill_name_edit = QLineEdit()
        self.skill_name_edit.setPlaceholderText("技能名称，例如：抖音三秒钩子专家")
        self.skill_desc_edit = QLineEdit()
        self.skill_desc_edit.setPlaceholderText("一句话描述（可选）")
        self.skill_scenario_edit = QLineEdit()
        self.skill_scenario_edit.setPlaceholderText("适用场景（可选），例如：需要提升完播率时启用")
        self.skill_tags_edit = QLineEdit()
        self.skill_tags_edit.setPlaceholderText("标签，用逗号分隔（可选）")
        self.skill_prompt_edit = QPlainTextEdit()
        self.skill_prompt_edit.setPlaceholderText("技能正文 = 注入大模型的专家提示词（写清要求、格式与禁止事项）")
        for widget in (
            self.skill_name_edit,
            self.skill_desc_edit,
            self.skill_scenario_edit,
            self.skill_tags_edit,
        ):
            right_layout.addWidget(widget)
        right_layout.addWidget(self.skill_prompt_edit, 1)

        save_button = QPushButton("保存技能")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_skill)
        right_layout.addWidget(save_button)
        body.addWidget(right)
        body.setSizes([260, 440])

        card.add_widget(body, 1)
        return card

    # ------------------------------------------------------------------ #
    # MCP
    # ------------------------------------------------------------------ #
    def _build_mcp_panel(self) -> QWidget:
        card = ModuleCard("MCP 服务器", "外部工具接入")
        self.mcp_badge = Badge("0 个已启用", "muted")
        card.add_header_widget(self.mcp_badge)

        body = QSplitter(Qt.Vertical)

        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(6)

        self.server_list = QListWidget()
        self.server_list.setObjectName("PlainList")
        self.server_list.setMaximumHeight(110)
        self.server_list.currentRowChanged.connect(self._on_server_selected)
        upper_layout.addWidget(self.server_list)

        self.server_name_edit = QLineEdit()
        self.server_name_edit.setPlaceholderText("服务器名称，例如：本地数据助手")
        self.transport_bar = SegmentBar(list(_TRANSPORTS), current="stdio")
        self.server_command_edit = QLineEdit()
        self.server_command_edit.setPlaceholderText("stdio 命令，例如：<项目>\\.venv\\Scripts\\python.exe")
        self.server_args_edit = QLineEdit()
        self.server_args_edit.setPlaceholderText("参数（空格分隔），例如：scripts/sample_mcp_server.py")
        self.server_url_edit = QLineEdit()
        self.server_url_edit.setPlaceholderText("SSE 地址（传输选“远程 SSE”时填写）")
        self.server_timeout_spin = QSpinBox()
        self.server_timeout_spin.setRange(5, 300)
        self.server_timeout_spin.setValue(30)
        self.server_enabled_box = QCheckBox("启用该服务器（其工具会出现在 AI 咨询中）")

        for widget in (
            self.server_name_edit,
            self.server_command_edit,
            self.server_args_edit,
            self.server_url_edit,
        ):
            upper_layout.addWidget(widget)
        timeout_row = QWidget()
        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(6)
        timeout_layout.addWidget(QLabel("传输"))
        timeout_layout.addWidget(self.transport_bar)
        timeout_layout.addWidget(QLabel("超时(秒)"))
        timeout_layout.addWidget(self.server_timeout_spin)
        timeout_layout.addStretch(1)
        upper_layout.addWidget(timeout_row)
        upper_layout.addWidget(self.server_enabled_box)

        buttons = ToolbarRow(spacing=6)
        new_button = QPushButton("新增服务器")
        new_button.clicked.connect(self._new_server)
        buttons.add(new_button, ToolbarRow.NORMAL)

        save_button = QPushButton("保存")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_server)
        buttons.add(save_button, ToolbarRow.REQUIRED)

        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self._delete_server)
        buttons.add(delete_button, ToolbarRow.HIGH)

        test_button = QPushButton("测试连接")
        test_button.clicked.connect(self._test_server)
        buttons.add(test_button, ToolbarRow.HIGH)
        buttons.add_stretch()
        upper_layout.addWidget(buttons)
        self.mcp_status = muted_label("")
        upper_layout.addWidget(self.mcp_status)
        body.addWidget(upper)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(6)
        lower_layout.addWidget(muted_label("当前可用工具（来自已启用的服务器）"))
        self.tool_list = QListWidget()
        self.tool_list.setObjectName("LogList")
        self.tool_list.setWordWrap(True)
        lower_layout.addWidget(self.tool_list, 1)
        body.addWidget(lower)
        body.setSizes([420, 260])

        card.add_widget(body, 1)
        return card

    # ------------------------------------------------------------------ #
    # 数据刷新
    # ------------------------------------------------------------------ #
    def refresh_status(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """重新加载技能列表与 MCP 服务器列表。"""
        self._loading = True
        directory = self.context.skills_directory()
        self.dir_label.setText(f"技能目录：{directory}")

        self._skills = self.context.all_skills()
        enabled = set(self.context.settings.skills_enabled or [])
        self.skill_list.clear()
        for skill in self._skills:
            item = QListWidgetItem(f"{skill.name}　{skill.description[:24]}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if skill.slug in enabled else Qt.Unchecked)
            item.setData(Qt.UserRole, skill.slug)
            self.skill_list.addItem(item)
        self.skill_badge.setText(f"{len(enabled & {s.slug for s in self._skills})} / {len(self._skills)} 个已启用")

        self._servers = self.context.mcp_servers()
        self.server_list.clear()
        for server in self._servers:
            state = "已启用" if server.enabled else "未启用"
            self.server_list.addItem(f"[{state}] {server.name or server.command or '未命名'}　{server.describe()}")
        active = sum(1 for server in self._servers if server.enabled)
        self.mcp_badge.setText(f"{active} / {len(self._servers)} 个已启用")
        self.mcp_badge.set_tone("cyan" if active else "muted")
        self._loading = False

        if self._skills and self.skill_list.currentRow() < 0:
            self.skill_list.setCurrentRow(0)
            self._on_skill_selected(self.skill_list.item(0))
        self._refresh_prompts()

    # ------------------------------------------------------------------ #
    # 提示词模板（覆盖内置角色设定，不改代码也能调优）
    # ------------------------------------------------------------------ #
    def _build_prompt_card(self) -> QWidget:
        card = ModuleCard("提示词模板", "覆盖内置角色提示词 · 保存后立即生效")
        self.prompt_badge = Badge("0 项已自定义", "muted")
        card.add_header_widget(self.prompt_badge)

        body = ResponsiveSplitter(
            threshold=620,
            horizontal_sizes=[300, 620],
            vertical_sizes=[200, 320],
            stacked_min_height=540,
        )

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.prompt_list = QListWidget()
        self.prompt_list.setObjectName("PlainList")
        self.prompt_list.currentRowChanged.connect(self._on_prompt_selected)
        left_layout.addWidget(self.prompt_list, 1)

        buttons = ToolbarRow(spacing=6)
        export_button = QPushButton("写入默认模板")
        export_button.clicked.connect(self._export_prompts)
        buttons.add(export_button, ToolbarRow.HIGH)
        open_button = QPushButton("打开模板目录")
        open_button.clicked.connect(self._open_prompt_dir)
        buttons.add(open_button, ToolbarRow.NORMAL)
        buttons.add_stretch()
        left_layout.addWidget(buttons)
        body.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.prompt_hint = muted_label("选择左侧模板后可在此编辑")
        right_layout.addWidget(self.prompt_hint)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "在这里编辑角色提示词：描述模型的角色、语气与必须遵守的规则；保存后立即生效，无需重启。"
        )
        right_layout.addWidget(self.prompt_edit, 1)

        actions = ToolbarRow(spacing=6)
        save_button = QPushButton("保存模板")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_prompt)
        actions.add(save_button, ToolbarRow.REQUIRED)
        reset_button = QPushButton("恢复内置默认")
        reset_button.clicked.connect(self._reset_prompt)
        actions.add(reset_button, ToolbarRow.HIGH)
        actions.add_stretch()
        right_layout.addWidget(actions)
        body.addWidget(right)

        card.add_widget(body, 1)
        return card

    def _refresh_prompts(self) -> None:
        from app.prompts_store import load_templates

        self._templates = load_templates()
        self.prompt_list.clear()
        overridden = 0
        for template in self._templates:
            mark = "● 已自定义" if template.overridden else "○ 内置默认"
            self.prompt_list.addItem(f"{template.name}　{mark}")
            overridden += int(template.overridden)
        self.prompt_badge.setText(f"{overridden} / {len(self._templates)} 项已自定义")
        self.prompt_badge.set_tone("cyan" if overridden else "muted")
        if self._templates and self.prompt_list.currentRow() < 0:
            self.prompt_list.setCurrentRow(0)

    def _on_prompt_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._templates):
            return
        template = self._templates[row]
        self._prompt_key = template.key
        self.prompt_edit.setPlainText(template.content)
        self.prompt_hint.setText(f"{template.description}｜文件：{template.path.name}")

    def _save_prompt(self) -> None:
        if not self._prompt_key:
            return
        text = self.prompt_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "内容为空", "提示词不能为空；如需恢复默认请点「恢复内置默认」。")
            return
        from app.prompts_store import save_template

        path = save_template(self._prompt_key, text)
        self.mcp_status.setText(f"提示词模板已保存：{path.name}（下次调用即生效）")
        self._refresh_prompts()

    def _reset_prompt(self) -> None:
        if not self._prompt_key:
            return
        from app.prompts_store import reset_template

        removed = reset_template(self._prompt_key)
        self.mcp_status.setText("已恢复内置默认" if removed else "当前就是内置默认，无需恢复")
        self._refresh_prompts()

    def _export_prompts(self) -> None:
        from app.prompts_store import ensure_default_files

        written = ensure_default_files()
        self.mcp_status.setText(
            f"已写出 {len(written)} 个默认模板文件，可用编辑器直接修改"
            if written
            else "模板文件已存在（未覆盖你改过的内容）"
        )
        self._refresh_prompts()

    def _open_prompt_dir(self) -> None:
        from app.prompts_store import default_prompt_dir

        directory = default_prompt_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            import os

            os.startfile(str(directory))  # noqa: S606 - Windows 桌面端打开目录
        except OSError as exc:
            self.mcp_status.setText(f"打开目录失败：{exc}")

    # ------------------------------------------------------------------ #
    # 技能操作
    # ------------------------------------------------------------------ #
    def _on_skill_checked(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        slug = str(item.data(Qt.UserRole) or "")
        if slug:
            self.context.set_skill_enabled(slug, item.checkState() == Qt.Checked)

    def _on_skill_selected(self, item: QListWidgetItem) -> None:
        slug = str(item.data(Qt.UserRole) or "")
        skill = next((s for s in self._skills if s.slug == slug), None)
        if skill is None:
            return
        self._current_slug = skill.slug
        self.skill_name_edit.setText(skill.name)
        self.skill_desc_edit.setText(skill.description)
        self.skill_scenario_edit.setText(skill.scenario)
        self.skill_tags_edit.setText("，".join(skill.tags))
        self.skill_prompt_edit.setPlainText(skill.prompt)

    def _new_skill(self) -> None:
        self._current_slug = None
        self.skill_list.clearSelection()
        self.skill_name_edit.clear()
        self.skill_desc_edit.clear()
        self.skill_scenario_edit.clear()
        self.skill_tags_edit.clear()
        self.skill_prompt_edit.setPlainText(
            "你是……专家。请遵守：\n1. 结合提供的数据引用具体数字，不要空谈；\n2. 给出可直接执行的步骤；\n3. 禁止编造数据。"
        )
        self.mcp_status.setText("已进入新建模式：填写后点「保存技能」")

    def _save_skill(self) -> None:
        name = self.skill_name_edit.text().strip()
        prompt = self.skill_prompt_edit.toPlainText().strip()
        if not name or not prompt:
            QMessageBox.information(self, "信息不足", "技能名称与正文提示词都不能为空。")
            return
        tags = [t.strip() for t in self.skill_tags_edit.text().replace("，", ",").split(",") if t.strip()]
        slug = self._current_slug or slugify(name)
        skill = Skill(
            slug=slug,
            name=name,
            description=self.skill_desc_edit.text().strip(),
            scenario=self.skill_scenario_edit.text().strip(),
            tags=tags,
            prompt=prompt,
        )
        self.context.save_skill(skill)
        self.context.set_skill_enabled(slug, True)
        self._current_slug = slug
        self.mcp_status.setText(f"技能「{name}」已保存并启用")
        self.refresh()

    def _delete_skill(self) -> None:
        if not self._current_slug:
            return
        skill = next((s for s in self._skills if s.slug == self._current_slug), None)
        if skill is None:
            return
        answer = QMessageBox.question(
            self, "删除技能", f"确定删除技能「{skill.name}」？该操作会删除对应的 .md 文件。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.context.delete_skill(skill)
        self._current_slug = None
        self.mcp_status.setText(f"技能「{skill.name}」已删除")
        self.refresh()

    def _install_builtin(self) -> None:
        written = ensure_builtin_skills(self.context.skills_directory())
        self.mcp_status.setText(
            f"已写入 {len(written)} 个内置示例技能" if written else "内置示例技能已存在，无需重复写入"
        )
        self.refresh()

    def _open_skills_dir(self) -> None:
        directory = self.context.skills_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            import os

            os.startfile(str(directory))  # noqa: S606 - Windows 桌面端打开目录
        except OSError as exc:
            self.mcp_status.setText(f"打开目录失败：{exc}")

    # ------------------------------------------------------------------ #
    # MCP 操作
    # ------------------------------------------------------------------ #
    def _on_server_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        self._server_index = row
        server = self._servers[row]
        self.server_name_edit.setText(server.name)
        self.transport_bar.set_current(server.transport or "stdio")
        self.server_command_edit.setText(server.command)
        self.server_args_edit.setText(" ".join(server.args or []))
        self.server_url_edit.setText(server.url)
        self.server_timeout_spin.setValue(int(server.timeout or 30))
        self.server_enabled_box.setChecked(bool(server.enabled))

    def _collect_server(self) -> McpServerSettings:
        args_text = self.server_args_edit.text().strip()
        return McpServerSettings(
            name=self.server_name_edit.text().strip(),
            enabled=self.server_enabled_box.isChecked(),
            transport=str(self.transport_bar.current_key() or "stdio"),
            command=self.server_command_edit.text().strip(),
            args=args_text.split() if args_text else [],
            url=self.server_url_edit.text().strip(),
            timeout=int(self.server_timeout_spin.value()),
        )

    def _new_server(self) -> None:
        self._server_index = -1
        self.server_list.clearSelection()
        self.server_name_edit.setText("本地数据助手")
        self.transport_bar.set_current("stdio")
        self.server_command_edit.setText(str(Path(".venv/Scripts/python.exe").resolve()))
        self.server_args_edit.setText("scripts/sample_mcp_server.py")
        self.server_url_edit.clear()
        self.server_timeout_spin.setValue(30)
        self.server_enabled_box.setChecked(True)
        self.mcp_status.setText("已预填「本地数据助手」示例配置，可直接点「保存」再「测试连接」")

    def _save_server(self) -> None:
        server = self._collect_server()
        if not server.is_configured():
            QMessageBox.information(self, "配置不完整", "stdio 需要填写命令，SSE 需要填写地址。")
            return
        servers = self.context.mcp_servers()
        if 0 <= self._server_index < len(servers):
            servers[self._server_index] = server
        else:
            servers.append(server)
            self._server_index = len(servers) - 1
        self.context.save_mcp_servers(servers)
        self.mcp_status.setText(f"服务器「{server.name}」已保存")
        self.refresh()
        self.server_list.setCurrentRow(self._server_index)

    def _delete_server(self) -> None:
        servers = self.context.mcp_servers()
        if not (0 <= self._server_index < len(servers)):
            return
        removed = servers.pop(self._server_index)
        self.context.save_mcp_servers(servers)
        self._server_index = -1
        self.mcp_status.setText(f"已删除服务器「{removed.name}」")
        self.refresh()

    def _test_server(self) -> None:
        server = self._collect_server()
        if not server.is_configured():
            QMessageBox.information(self, "配置不完整", "stdio 需要填写命令，SSE 需要填写地址。")
            return
        self.mcp_status.setText("正在连接 MCP 服务器…")

        def job() -> tuple[bool, str]:
            from app.mcp import test_connection

            return test_connection(server)

        def done(result: tuple[bool, str]) -> None:
            ok, message = result
            self.mcp_status.setText(("✅ " if ok else "❌ ") + message)
            if ok:
                self._refresh_tools()

        self.context.runner.submit(
            job, done, lambda error: self.mcp_status.setText(f"测试失败：{error}")
        )

    def _refresh_tools(self) -> None:
        self.mcp_status.setText("正在汇总 MCP 工具…")
        self.tool_list.clear()

        def job() -> tuple[list[Any], list[str]]:
            box = self.context.refresh_toolbox()
            return box.tools, box.errors

        def done(result: tuple[list[Any], list[str]]) -> None:
            tools, errors = result
            self.tool_list.clear()
            for tool in tools:
                item = QListWidgetItem(
                    f"● {tool.qualified}\n    {tool.description[:80] or '（无描述）'}"
                )
                self.tool_list.addItem(item)
            if not tools:
                self.tool_list.addItem(QListWidgetItem("暂无可用工具（请先新增并启用 MCP 服务器）"))
            for error in errors:
                self.tool_list.addItem(QListWidgetItem(f"⚠️ {error}"))
            self.mcp_status.setText(
                f"共 {len(tools)} 个工具可用" + (f"，{len(errors)} 个服务器连接失败" if errors else "")
            )

        self.context.runner.submit(
            job, done, lambda error: self.mcp_status.setText(f"刷新工具失败：{error}")
        )
