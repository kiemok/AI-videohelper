"""设置页：数据存储、大模型 API（Key 保存在用户本地）、任务调度与日志。"""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import create_engine, text

from app.config import PROVIDER_PRESETS, AppSettings, LLMSettings, default_sqlite_url
from app.ui.context import AppContext
from app.ui.theme import THEME_LABELS
from app.ui.widgets.cards import SegmentBar, hint_label

MYSQL_EXAMPLE = "mysql+pymysql://root:密码@127.0.0.1:3306/content_decision?charset=utf8mb4"


class SettingsPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build()
        self.load_from_settings(context.settings)
        context.settings_changed.connect(lambda: self.load_from_settings(self.context.settings))
        context.theme_changed.connect(lambda name: self.theme_bar.set_current(name))

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title = QLabel("调度与设置")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(
            hint_label(
                "大模型 API Key 只保存在本机配置文件（默认 config/settings.json，已加入 .gitignore），"
                "不会上传到任何服务器，也不会写入数据库。"
            )
        )

        root.addWidget(self._build_appearance_group())
        root.addWidget(self._build_storage_group())
        root.addWidget(self._build_llm_group())
        root.addWidget(self._build_task_group())
        root.addWidget(self._build_repo_group())

        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.save_button = QPushButton("保存配置")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._save)
        action_layout.addWidget(self.save_button)
        self.reset_button = QPushButton("恢复默认值")
        self.reset_button.clicked.connect(self._reset)
        action_layout.addWidget(self.reset_button)
        action_layout.addStretch(1)
        self.feedback = hint_label("")
        action_layout.addWidget(self.feedback)
        root.addWidget(actions)
        root.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ #
    def _build_appearance_group(self) -> QGroupBox:
        group = QGroupBox("外观主题")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        self.theme_bar = SegmentBar(
            [(label, key) for key, label in THEME_LABELS], current="dark"
        )
        self.theme_bar.selected.connect(self._on_theme_selected)
        form.addRow("主题", self.theme_bar)
        form.addRow(
            hint_label(
                "三套内置主题：浅黑（默认，适合长时间盯屏）／浅白（亮色办公）／浅蓝（清爽蓝调）。"
                "切换后立即生效（含图表与自绘组件配色），并记入本地配置，下次启动自动沿用。"
            )
        )
        return group

    def _on_theme_selected(self, key: object) -> None:
        self.context.apply_theme(str(key))

    def _build_storage_group(self) -> QGroupBox:
        group = QGroupBox("数据存储")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

        self.db_edit = QLineEdit()
        self.db_edit.setPlaceholderText(default_sqlite_url())
        form.addRow("数据库连接串", self.db_edit)
        form.addRow("", hint_label(f"默认 SQLite（本地单文件，零配置）。切换 MySQL 示例：{MYSQL_EXAMPLE}"))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.db_test_button = QPushButton("测试数据库连接")
        self.db_test_button.clicked.connect(self._test_db)
        row_layout.addWidget(self.db_test_button)
        self.db_default_button = QPushButton("使用默认 SQLite")
        self.db_default_button.clicked.connect(lambda: self.db_edit.setText(default_sqlite_url()))
        row_layout.addWidget(self.db_default_button)
        row_layout.addStretch(1)
        form.addRow("", row)
        return group

    def _build_llm_group(self) -> QGroupBox:
        group = QGroupBox("大模型 API（DeepSeek / 通义千问 / 任意 OpenAI 兼容服务）")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

        self.provider_box = QComboBox()
        for key, preset in PROVIDER_PRESETS.items():
            self.provider_box.addItem(preset["label"], key)
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("服务商", self.provider_box)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-…（仅保存在本机）")
        key_layout.addWidget(self.api_key_edit, 1)
        self.show_key_box = QCheckBox("显示")
        self.show_key_box.toggled.connect(
            lambda checked: self.api_key_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        key_layout.addWidget(self.show_key_box)
        form.addRow("API Key", key_row)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("留空使用服务商默认地址")
        form.addRow("Base URL", self.base_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("留空使用默认模型，如 deepseek-chat / qwen-plus")
        form.addRow("模型名", self.model_edit)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.6)
        form.addRow("温度 temperature", self.temperature_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(128, 8192)
        self.max_tokens_spin.setSingleStep(128)
        self.max_tokens_spin.setValue(1200)
        form.addRow("最大输出 tokens", self.max_tokens_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(60)
        form.addRow("请求超时（秒）", self.timeout_spin)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("可选，如 http://127.0.0.1:7890（爬虫与大模型请求共用）")
        form.addRow("HTTP 代理", self.proxy_edit)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.llm_test_button = QPushButton("测试大模型连接")
        self.llm_test_button.clicked.connect(self._test_llm)
        row_layout.addWidget(self.llm_test_button)
        row_layout.addStretch(1)
        form.addRow("", row)
        return group

    def _build_task_group(self) -> QGroupBox:
        group = QGroupBox("任务调度与日志")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

        self.schedule_box = QCheckBox("启用每日自动分析")
        form.addRow("定时任务", self.schedule_box)

        self.schedule_time_edit = QLineEdit()
        self.schedule_time_edit.setPlaceholderText("HH:MM，如 08:30")
        form.addRow("执行时间", self.schedule_time_edit)

        self.schedule_status = hint_label("")
        form.addRow("", self.schedule_status)

        self.log_level_box = QComboBox()
        self.log_level_box.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        form.addRow("日志级别", self.log_level_box)
        form.addRow("", hint_label("日志写入 logs/app.log，ERROR 级别同时写入 logs/alerts.log（告警通道）。"))
        return group

    def _build_repo_group(self) -> QGroupBox:
        group = QGroupBox("数据仓库（数据来源）")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow(
            hint_label(
                "本软件不包含爬取功能：数据由你在外部定期采集后推送到自建 Git 仓库，"
                "软件只负责拉取与导入。仓库地址 / 分支 / 获取方式 / 每日自动拉取 等配置"
                "请到「数据仓库与导入」页维护。"
            )
        )
        return group

    # ------------------------------------------------------------------ #
    def _on_provider_changed(self) -> None:
        provider = self.provider_box.currentData()
        preset = PROVIDER_PRESETS.get(provider, {})
        # 仅当用户未自定义时填充默认值，避免覆盖手工填写的内容
        if provider != "custom":
            if not self.base_url_edit.text().strip():
                self.base_url_edit.setPlaceholderText(preset.get("base_url", ""))
            if not self.model_edit.text().strip():
                self.model_edit.setPlaceholderText(preset.get("model", ""))

    def load_from_settings(self, settings: AppSettings) -> None:
        self.db_edit.setText(settings.db_url or "")
        llm = settings.llm
        index = self.provider_box.findData(llm.provider)
        self.provider_box.setCurrentIndex(index if index >= 0 else 0)
        self.api_key_edit.setText(llm.api_key)
        self.base_url_edit.setText(llm.base_url)
        self.model_edit.setText(llm.model)
        self.temperature_spin.setValue(float(llm.temperature))
        self.max_tokens_spin.setValue(int(llm.max_tokens))
        self.timeout_spin.setValue(int(llm.timeout))
        self.proxy_edit.setText(settings.http_proxy)
        self.schedule_box.setChecked(bool(settings.schedule_enabled))
        self.schedule_time_edit.setText(settings.schedule_time)
        level_index = self.log_level_box.findText(settings.log_level.upper())
        self.log_level_box.setCurrentIndex(level_index if level_index >= 0 else 1)
        self.theme_bar.set_current(settings.theme or "dark")
        self._on_provider_changed()
        self.refresh_schedule_status()

    def refresh_schedule_status(self) -> None:
        """显示定时任务当前运行状态与下次执行时间。"""
        scheduler = self.context.scheduler
        if scheduler.is_running:
            self.schedule_status.setText(f"状态：运行中，下次执行 {scheduler.next_run_text()}")
        else:
            self.schedule_status.setText("状态：未启用（勾选并保存后生效）")

    def collect_settings(self) -> AppSettings:
        """从界面收集配置。

        以**当前配置为基础**做字段覆盖（``dataclasses.replace``），
        避免遗漏字段——例如 ``theme``（外观主题）与 ``data_repo``（数据仓库）
        都由其它入口维护，重建对象时若丢失会被重置为默认值。
        """
        llm = LLMSettings(
            provider=self.provider_box.currentData() or "deepseek",
            api_key=self.api_key_edit.text().strip(),
            base_url=self.base_url_edit.text().strip(),
            model=self.model_edit.text().strip(),
            temperature=float(self.temperature_spin.value()),
            max_tokens=int(self.max_tokens_spin.value()),
            timeout=int(self.timeout_spin.value()),
        )
        return dataclasses.replace(
            self.context.settings,
            db_url=self.db_edit.text().strip(),
            log_level=self.log_level_box.currentText(),
            http_proxy=self.proxy_edit.text().strip(),
            schedule_enabled=self.schedule_box.isChecked(),
            schedule_time=self.schedule_time_edit.text().strip() or "08:30",
            # 外观主题以 AppContext 为准（顶栏与设置页切换都会同步它），UI 值仅作兜底
            theme=str(self.context.settings.theme or self.theme_bar.current_key() or "dark"),
            llm=llm,
        )

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        settings = self.collect_settings()
        if settings.db_url and not settings.db_url.split("://")[0].startswith(("sqlite", "mysql")):
            QMessageBox.warning(self, "连接串格式", "数据库连接串需以 sqlite:/// 或 mysql+pymysql:// 开头。")
            return
        self.context.apply_settings(settings)
        self.feedback.setText("配置已保存并生效")

    def _reset(self) -> None:
        self.load_from_settings(AppSettings())
        self.feedback.setText("已恢复默认值（需点击「保存配置」生效）")

    # ------------------------------------------------------------------ #
    def _test_db(self) -> None:
        url = self.db_edit.text().strip() or default_sqlite_url()
        self.feedback.setText("正在测试数据库连接…")

        def probe() -> str:
            engine = create_engine(url, pool_pre_ping=True)
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return f"数据库连接成功：{url.split('@')[-1]}"
            finally:
                engine.dispose()

        self.context.runner.submit(
            probe,
            lambda message: self.feedback.setText(message),
            lambda error: self.feedback.setText(f"数据库连接失败：{error}"),
        )

    def _test_llm(self) -> None:
        settings = self.collect_settings()
        self.feedback.setText("正在测试大模型连接…")

        def probe() -> str:
            from app.ai.client import LLMClient

            ok, message = LLMClient(settings.llm, settings.http_proxy).test_connection()
            return ("✅ " if ok else "❌ ") + message

        self.context.runner.submit(
            probe,
            lambda message: self.feedback.setText(message),
            lambda error: self.feedback.setText(f"测试失败：{error}"),
        )
