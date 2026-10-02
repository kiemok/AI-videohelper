"""数据仓库与导入页。

数据来源改为**用户自建的 Git 数据仓库**（外部定期爬取后推送），
软件内不再包含任何爬取逻辑。本页负责：

- 仓库配置：地址 / 分支 / 本地目录 / 数据子目录 / 获取方式（自动、仅 git、仅 ZIP、仅本地）/ 自动拉取
- 同步操作：拉取并导入、仅导入本地目录、生成数据模板、载入演示数据
- 状态遥测：仓库状态（commit / 数据文件数 / 最近更新）、本地存储体积、统一实体映射表
- 数据清单：作品 / 账号 / 指标快照 / 同步记录
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import PLATFORM_LABELS, DataRepoSettings
from app.db.base import init_db, reset_engines
from app.db.repository import (
    list_accounts,
    list_repo_sync_logs,
    list_snapshots,
    list_videos,
)
from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import (
    Badge,
    ModuleCard,
    SegmentBar,
    StatRow,
    hint_label,
    muted_label,
)
from app.ui.widgets.tables import (
    ACCOUNT_COLUMNS,
    VIDEO_COLUMNS,
    Column,
    DictTableModel,
    configure_table,
)

#: 统一数据模型 ←→ 双平台原始字段的映射说明（与 app/collect/fusion.py 保持一致）
MAPPING_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("work_id (PK)", "bvid", "aweme_id", "字符串去空格，平台内唯一"),
    ("platform (Enum)", "'bilibili'", "'douyin'", "读取时自动写入平台标识"),
    ("play_count (int)", "stat.view", "statistics.play_count", "累计口径，缺失置 0"),
    ("like_count (int)", "stat.like", "statistics.digg_count", "缺失置 0"),
    ("comment_count (int)", "stat.reply", "statistics.comment_count", "评论数含二级评论"),
    ("share_count (int)", "stat.share", "statistics.share_count", "分享/转发统一映射"),
    ("favorite_count (int)", "stat.favorite", "statistics.collect_count", "收藏/收藏夹归一"),
    ("danmaku_count (int)", "stat.danmaku", "—", "仅 B站有弹幕，抖音置 0"),
    ("engagement_rate", "(点赞+评论+分享)/播放", "(点赞+评论+分享)/播放", "双平台同一口径计算"),
    ("comments_ref", "replies[].message", "comments[].text", "写入 comment 表并外键关联"),
)

MAPPING_COLUMNS = [
    Column("entity", "标准统一实体", 160),
    Column("bilibili", "Bilibili 映射字段（RAW JSON）", 230),
    Column("douyin", "Douyin 映射字段（RAW JSON）", 230),
    Column("rule", "计算 / 转换规则", 280),
]

SNAPSHOT_COLUMNS = [
    Column("platform", "平台", 60),
    Column("title", "作品", 260),
    Column("stat_date", "日期", 100),
    Column("view_count", "累计播放", 100, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("like_count", "点赞", 84, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("comment_count", "评论", 76, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("follower_gain", "涨粉", 76, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
]

SYNC_LOG_COLUMNS = [
    Column("finished_at", "时间", 150, lambda v: str(v)[:19] if v else "—"),
    Column("action", "动作", 100),
    Column("item_count", "数据文件", 84, lambda v: f"{int(v or 0)}", Qt.AlignRight | Qt.AlignVCenter),
    Column("status", "状态", 72),
    Column("message", "结果", 520),
]

_REPO_MODES: tuple[tuple[str, str], ...] = (
    ("自动（git → ZIP）", "auto"),
    ("仅 git 命令", "git"),
    ("仅 ZIP 下载", "zip"),
    ("仅本地目录", "local"),
)


class DataPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build()
        self.load_repo_form(context.settings.data_repo)
        context.data_changed.connect(self.refresh)
        context.settings_changed.connect(self.refresh)
        context.settings_changed.connect(
            lambda: self.load_repo_form(self.context.settings.data_repo)
        )

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        # 内容较多：外层套滚动区，窗口不够高时出现滚动条，而不是把卡片压扁/截断
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        root.addWidget(self._build_toolbar())
        root.addWidget(
            hint_label(
                "数据由你自建的 Git 仓库提供（外部定期爬取后推送）；本软件只负责拉取与导入，"
                "不在软件内执行任何爬取行为。仓库支持标准 CSV 与平台原始 JSON/JSONL 两种格式。"
            )
        )

        top = QHBoxLayout()
        top.setSpacing(12)
        repo_card = self._build_repo_card()
        repo_card.setMinimumHeight(340)  # 保证仓库配置表单完整可见
        format_card = self._build_format_card()
        format_card.setMinimumHeight(340)
        top.addWidget(repo_card, 3)
        top.addWidget(format_card, 2)
        root.addLayout(top)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        storage_card = self._build_storage_card()
        storage_card.setMinimumHeight(300)
        mapping_card = self._build_mapping_card()
        mapping_card.setMinimumHeight(300)
        middle.addWidget(storage_card, 2)
        middle.addWidget(mapping_card, 3)
        root.addLayout(middle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_video_tab(), "作品清单")
        self.tabs.addTab(self._build_account_tab(), "账号清单")
        self.tabs.addTab(self._build_snapshot_tab(), "指标快照")
        self.tabs.addTab(self._build_log_tab(), "同步记录")
        self.tabs.setMinimumHeight(360)
        root.addWidget(self.tabs)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_toolbar(self) -> QWidget:
        bar = ToolbarRow(spacing=8)
        title = bar.add(QLabel("数据仓库与导入"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")
        desc = muted_label("仓库拉取 → 融合导入")
        desc.setWordWrap(False)
        bar.add(desc, ToolbarRow.LOW)
        bar.add_stretch()

        self.sync_button = QPushButton("拉取 / 更新数据")
        self.sync_button.setObjectName("PrimaryButton")
        self.sync_button.clicked.connect(self.context.sync_data_repo)
        bar.add(self.sync_button, ToolbarRow.REQUIRED)

        self.local_button = QPushButton("仅导入本地目录")
        self.local_button.clicked.connect(self.context.import_repo_local)
        bar.add(self.local_button, ToolbarRow.HIGH)

        self.template_button = QPushButton("生成数据模板")
        self.template_button.clicked.connect(self.context.write_repo_templates)
        bar.add(self.template_button, ToolbarRow.NORMAL)
        return bar

    # ------------------------------------------------------------------ #
    def _build_repo_card(self) -> QWidget:
        card = ModuleCard("数据仓库（Git）", "DATA REPOSITORY")
        self.repo_badge = Badge("未配置", "muted")
        card.add_header_widget(self.repo_badge)

        grid = QWidget()
        form = QGridLayout(grid)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://github.com/用户名/数据仓库.git 或 https://gitee.com/…")
        self.url_edit.setMinimumWidth(320)
        form.addWidget(QLabel("仓库地址"), 0, 0)
        form.addWidget(self.url_edit, 0, 1, 1, 3)

        self.branch_edit = QLineEdit()
        self.branch_edit.setPlaceholderText("main")
        form.addWidget(QLabel("分支"), 1, 0)
        form.addWidget(self.branch_edit, 1, 1, 1, 3)

        self.subdir_edit = QLineEdit()
        self.subdir_edit.setPlaceholderText("留空 = 仓库根目录；例如 data")
        form.addWidget(QLabel("数据子目录"), 2, 0)
        form.addWidget(self.subdir_edit, 2, 1, 1, 3)

        self.local_edit = QLineEdit()
        self.local_edit.setPlaceholderText("留空 = <项目根>/data/repo")
        form.addWidget(QLabel("本地缓存目录"), 3, 0)
        form.addWidget(self.local_edit, 3, 1, 1, 3)

        form.addWidget(QLabel("获取方式"), 4, 0)
        self.mode_bar = SegmentBar([(label, key) for label, key in _REPO_MODES], current="auto")
        form.addWidget(self.mode_bar, 4, 1, 1, 3)

        self.auto_pull_box = QCheckBox("每日定时任务触发时先自动拉取仓库")
        form.addWidget(self.auto_pull_box, 5, 1, 1, 3)
        card.add_widget(grid)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.repo_status_label = muted_label("")
        status_layout.addWidget(self.repo_status_label, 1)
        self.save_repo_button = QPushButton("保存仓库配置")
        self.save_repo_button.setObjectName("PrimaryButton")
        self.save_repo_button.clicked.connect(self._save_repo)
        status_layout.addWidget(self.save_repo_button)
        card.add_widget(status_row)

        validation_row = QWidget()
        validation_layout = QHBoxLayout(validation_row)
        validation_layout.setContentsMargins(0, 0, 0, 0)
        validation_layout.setSpacing(8)
        self.validation_label = muted_label("数据校验：尚未导入")
        self.validation_label.setWordWrap(False)
        validation_layout.addWidget(self.validation_label, 1)
        self.report_button = QPushButton("查看导入报告")
        self.report_button.setToolTip("打开最近一次导入生成的数据校验报告（Markdown）")
        self.report_button.clicked.connect(self._open_import_report)
        validation_layout.addWidget(self.report_button)
        card.add_widget(validation_row)

        demo_row = QWidget()
        demo_layout = QHBoxLayout(demo_row)
        demo_layout.setContentsMargins(0, 0, 0, 0)
        demo_layout.setSpacing(8)
        demo_layout.addWidget(QLabel("样例天数"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(7, 180)
        self.days_spin.setValue(30)
        demo_layout.addWidget(self.days_spin)
        self.demo_button = QPushButton("载入演示数据（离线生成）")
        self.demo_button.clicked.connect(
            lambda: self.context.sync_sample_data(days=self.days_spin.value())
        )
        demo_layout.addWidget(self.demo_button)
        demo_layout.addStretch(1)
        card.add_widget(demo_row)
        card.add_widget(
            muted_label("提示：演示数据仅用于无仓库时体验界面与自检，建议接入真实仓库后清空重导。")
        )
        card.body_layout.addStretch(1)
        return card

    def _build_format_card(self) -> QWidget:
        card = ModuleCard("仓库数据格式约定", "支持两种格式，可混用")
        card.add_widget(
            hint_label(
                "A. 标准 CSV：accounts.csv / videos.csv / snapshots/YYYY-MM-DD.csv / comments/YYYY-MM-DD.csv"
                "（字段为统一模型字段）"
            )
        )
        card.add_widget(
            hint_label(
                "B. 平台原始 JSON/JSONL：bilibili/*.json、douyin/*.json"
                "（爬虫导出原样即可，软件自动做字段融合映射）"
            )
        )
        card.add_widget(
            muted_label(
                "作品对象内若带 snapshots / stats 数组，会被自动解析为该作品的每日快照；"
                "文件按 accounts / videos / snapshots / comments 关键字自动归类。"
            )
        )
        button = QPushButton("在本地目录生成模板与说明")
        button.clicked.connect(self.context.write_repo_templates)
        card.add_widget(button)
        card.body_layout.addStretch(1)
        return card

    def _build_storage_card(self) -> QWidget:
        card = ModuleCard("本地存储遥测", "LOCAL STORAGE")
        card.add_header_widget(Badge("SQLite 单文件", "cyan"))
        self.storage_path = muted_label("")
        card.add_widget(self.storage_path)

        self.size_bar = QProgressBar()
        self.size_bar.setRange(0, 100)
        self.size_bar.setTextVisible(False)
        self.size_bar.setFixedHeight(8)
        card.add_widget(self.size_bar)
        self.size_label = muted_label("")
        card.add_widget(self.size_label)

        self.storage_rows = {
            "videos": StatRow("收录作品", "0"),
            "comments": StatRow("抓取评论", "0"),
            "snapshots": StatRow("每日指标快照", "0"),
            "accounts": StatRow("创作者账号", "0"),
            "reports": StatRow("AI 报告", "0"),
        }
        grid = QWidget()
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(4)
        for index, row in enumerate(self.storage_rows.values()):
            grid_layout.addWidget(row, index // 2, index % 2)
        card.add_widget(grid)

        clear_button = QPushButton("清空本地业务数据")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self.confirm_clear)
        card.add_widget(clear_button)
        card.body_layout.addStretch(1)
        return card

    def _build_mapping_card(self) -> QWidget:
        card = ModuleCard("统一多源数据实体映射", "Data Model Mapper")
        card.add_header_widget(Badge("异构字段 → 标准实体", "cyan"))
        self.mapping_model = DictTableModel(MAPPING_COLUMNS)
        self.mapping_model.set_rows(
            [{"entity": e, "bilibili": b, "douyin": d, "rule": r} for e, b, d, r in MAPPING_ROWS]
        )
        self.mapping_table = QTableView()
        self.mapping_table.setModel(self.mapping_model)
        configure_table(self.mapping_table, row_height=28, stretch_column=3)
        card.add_widget(self.mapping_table, 1)
        card.add_widget(
            muted_label("映射规则集中在 app/collect/fusion.py，新增数据源只需补充一组 normalize_* 分支。")
        )
        return card

    def _build_video_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        filters = QWidget()
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self.platform_filter = SegmentBar(
            [("全部", "")] + [(label, key) for key, label in PLATFORM_LABELS.items()], current=""
        )
        self.platform_filter.selected.connect(lambda _key: self.refresh())
        filter_layout.addWidget(self.platform_filter)
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("按标题筛选…")
        self.keyword_edit.setFixedWidth(200)
        self.keyword_edit.returnPressed.connect(self.refresh)
        filter_layout.addWidget(self.keyword_edit)
        filter_layout.addStretch(1)
        self.video_hint = muted_label("")
        filter_layout.addWidget(self.video_hint)
        layout.addWidget(filters)

        self.video_model = DictTableModel(VIDEO_COLUMNS)
        self.video_table = QTableView()
        self.video_table.setModel(self.video_model)
        configure_table(self.video_table, row_height=30, stretch_column=1, platform_column=0)
        layout.addWidget(self.video_table, 1)
        return page

    def _build_account_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.account_model = DictTableModel(ACCOUNT_COLUMNS)
        self.account_table = QTableView()
        self.account_table.setModel(self.account_model)
        configure_table(self.account_table, row_height=30, stretch_column=1, platform_column=0)
        layout.addWidget(self.account_table, 1)
        return page

    def _build_snapshot_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.snapshot_model = DictTableModel(SNAPSHOT_COLUMNS)
        self.snapshot_table = QTableView()
        self.snapshot_table.setModel(self.snapshot_model)
        configure_table(self.snapshot_table, row_height=28, stretch_column=1, platform_column=0)
        layout.addWidget(self.snapshot_table, 1)
        self.snapshot_hint = muted_label("")
        layout.addWidget(self.snapshot_hint)
        return page

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.log_model = DictTableModel(SYNC_LOG_COLUMNS)
        self.log_table = QTableView()
        self.log_table.setModel(self.log_model)
        configure_table(self.log_table, row_height=28, stretch_column=4)
        layout.addWidget(self.log_table, 1)
        layout.addWidget(
            muted_label("记录每次「拉取 / 更新数据」「仅导入本地目录」的结果，便于排查仓库格式问题。")
        )
        return page

    # ------------------------------------------------------------------ #
    def load_repo_form(self, repo: DataRepoSettings) -> None:
        self.url_edit.setText(repo.url)
        self.branch_edit.setText(repo.branch or "main")
        self.subdir_edit.setText(repo.subdir)
        self.local_edit.setText(repo.local_dir)
        self.mode_bar.set_current(repo.mode or "auto")
        self.auto_pull_box.setChecked(bool(repo.auto_pull))

    def _collect_repo(self) -> DataRepoSettings:
        return DataRepoSettings(
            url=self.url_edit.text().strip(),
            branch=self.branch_edit.text().strip() or "main",
            subdir=self.subdir_edit.text().strip(),
            local_dir=self.local_edit.text().strip(),
            mode=str(self.mode_bar.current_key() or "auto"),
            auto_pull=self.auto_pull_box.isChecked(),
        )

    def _save_repo(self) -> None:
        settings = self.context.settings
        settings.data_repo = self._collect_repo()
        self.context.apply_settings(settings)
        self.refresh_repo_status()

    # ------------------------------------------------------------------ #
    def confirm_clear(self) -> None:
        answer = QMessageBox.question(
            self,
            "确认清空",
            "将删除本地数据库中的全部账号、作品、指标快照、评论、分析结果与 AI 报告，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.context.clear_data()

    def _restart_engine(self) -> None:
        def job() -> str:
            reset_engines()
            init_db(self.context.db_url)
            return "本地引擎已重启（连接池已重建）"

        self.context.runner.submit(
            job,
            lambda message: self.context.status_message.emit(message),
            lambda error: self.context.status_message.emit(f"重启失败：{error}"),
        )

    # ------------------------------------------------------------------ #
    def refresh_repo_status(self) -> None:
        """刷新仓库状态胶囊与说明（不联网）。"""
        status = self.context.repo_status()
        if not status["configured"]:
            self.repo_badge.setText("未配置")
            self.repo_badge.set_tone("muted")
            self.repo_status_label.setText(
                f"本地目录：{status['local_dir']}（尚未配置仓库地址；也可只用「仅本地目录」模式）"
            )
            return

        if status["exists"]:
            tone = "green" if status["files"] else "coral"
            text = "已同步" if status["files"] else "目录为空"
            commit = f"commit {status['commit']}" if status["commit"] else "非 git 目录"
            self.repo_status_label.setText(
                f"{status['local_dir']}｜{commit}｜数据文件 {status['files']} 个"
                f"｜最近更新 {status['updated_at'] or '未知'}"
            )
        else:
            tone = "amber"
            text = "待拉取"
            self.repo_status_label.setText(
                f"尚未拉取：点击右上角「拉取 / 更新数据」将克隆到 {status['local_dir']}"
            )
        self.repo_badge.setText(text)
        self.repo_badge.set_tone(tone)

    def refresh_status(self) -> None:
        self.refresh()

    # ------------------------------------------------------------------ #
    # 导入校验报告（最近一次导入的数据质量问题）
    # ------------------------------------------------------------------ #
    def _render_validation(self) -> None:
        report = self.context.last_import_report or {}
        if not report:
            self.validation_label.setText("数据校验：尚未导入｜导入后这里会显示校验结论")
            self.report_button.setEnabled(False)
            return
        errors = int(report.get("error_count") or 0)
        warnings = int(report.get("warning_count") or 0)
        if errors or warnings:
            self.validation_label.setText(
                f"数据校验：错误 {errors} 处、警告 {warnings} 处｜{self._first_issue(report)}"
            )
        else:
            self.validation_label.setText("数据校验：未发现问题 ✅")
        self.report_button.setEnabled(bool(report.get("report_path")))

    @staticmethod
    def _first_issue(report: dict[str, Any]) -> str:
        issues = report.get("errors") or report.get("warnings") or []
        return str(issues[0]) if issues else "详见导入报告"

    def _open_import_report(self) -> None:
        path = str((self.context.last_import_report or {}).get("report_path") or "")
        if not path:
            self.context.status_message.emit("暂无导入报告：请先执行一次数据导入")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.context.status_message.emit(f"无法打开报告（请手动查看）：{path}")
        else:
            self.context.status_message.emit(f"已打开导入报告：{path}")

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self.refresh_repo_status()
        self._render_validation()
        overview = self.context.overview()
        platform = self.platform_filter.current_key() or None
        keyword = self.keyword_edit.text().strip() or None
        videos = list_videos(self.context.db_url, platform=platform, keyword=keyword)
        self.video_model.set_rows(videos)
        self.video_hint.setText(f"共 {len(videos)} 条记录")
        self.account_model.set_rows(list_accounts(self.context.db_url))
        snapshots = list_snapshots(self.context.db_url)
        self.snapshot_model.set_rows(snapshots[-500:])
        self.snapshot_hint.setText(f"共 {len(snapshots):,} 条快照（展示最近 500 条）")
        self.log_model.set_rows(list_repo_sync_logs(self.context.db_url, limit=30))

        for key, row in self.storage_rows.items():
            row.set_value(f"{int(overview.get(key, 0)):,}")

        if self.context.db_url.startswith("sqlite"):
            path = self.context.db_url.split("///")[-1]
            self.storage_path.setText(f"本地库路径：{path}")
            size_mb = 0.0
            try:
                size_mb = Path(path).stat().st_size / 1024 / 1024
            except OSError:
                pass
            self.size_label.setText(f"总体量占用：{size_mb:.2f} MB / 建议上限 5120 MB")
            self.size_bar.setValue(min(100, int(size_mb / 5120 * 100)))
        else:
            self.storage_path.setText("远程数据库：MySQL（连接池已启用 pre_ping）")
            self.size_label.setText("体积统计仅对本地 SQLite 生效")
            self.size_bar.setValue(0)
