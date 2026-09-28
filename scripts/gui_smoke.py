"""界面冒烟测试：离屏/真实平台渲染主窗口，跑完整业务流程并逐页截图。

覆盖：同步数据 → 分析 → 逐页截图 → AI 简报 → 数据问答 → 创作咨询 → AI 短剧（建项目/大纲/分镜）
→ 再截图。用于快速验证界面与异步任务链路，不依赖人工点击。

用法：
    .venv\\Scripts\\python.exe scripts\\gui_smoke.py
    .venv\\Scripts\\python.exe scripts\\gui_smoke.py --no-import --out D:\\shots
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 必须在导入 Qt 之前设置

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import ensure_dirs  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui import theme as theme_module  # noqa: E402

#: 导航顺序：看板 / 分析与评论 / AI 助手 / 创作咨询 / AI 短剧 / 数据源 / 设置
PAGES = ("dashboard", "analysis", "ai", "consulting", "drama", "data", "settings")
INDEX_AI = 2
INDEX_CONSULTING = 3
INDEX_DRAMA = 4
INDEX_DATA = 5


def log(message: str) -> None:
    """统一输出并强制 flush（管道/后台运行时也能实时看到进度）。"""
    print(message, flush=True)


class Driver:
    """用定时器驱动一个极简状态机，串联整条界面流程。"""

    def __init__(
        self, app: QApplication, window: MainWindow, out_dir: Path, import_data: bool
    ) -> None:
        self.app = app
        self.window = window
        self.context = window.context
        self.out_dir = out_dir
        self.import_data = import_data
        self.phase = "import" if import_data else "analysis"
        self.deadline = time.time() + 300
        self.last_phase = ""
        self.shots: list[Path] = []
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    # ------------------------------------------------------------------ #
    def tick(self) -> None:
        if self.phase != self.last_phase:
            log("[gui] phase -> {}".format(self.phase))
            self.last_phase = self.phase
        if time.time() > self.deadline:
            log("[gui] 超时，中止")
            self.finish()
            return

        phase = self.phase

        if phase == "import":
            log("[gui] 同步离线样例数据…")
            self.context.sync_sample_data(days=30)
            self.phase = "wait_import"

        elif phase == "wait_import":
            if not self.context.busy:
                log("[gui] 数据导入结束：" + str(self.context.overview()))
                self.phase = "analysis"

        elif phase == "analysis":
            log("[gui] 执行分析…")
            self.context.run_analysis()
            self.phase = "wait_analysis"

        elif phase == "wait_analysis":
            if not self.context.busy:
                if not self.context.metrics:
                    log("[gui] 分析没有产生结果")
                else:
                    head = self.context.metrics.get("headline", {})
                    log(
                        "[gui] 分析完成：健康度 {}，新增播放 {}".format(
                            head.get("health_score"), head.get("daily_views")
                        )
                    )
                self.phase = "shots"

        elif phase == "shots":
            self.capture()
            self.phase = "brief"

        elif phase == "brief":
            log("[gui] 触发数据简报生成…")
            self.window.nav.setCurrentRow(INDEX_AI)
            self.window.ai_page._generate("daily_brief")
            self.phase = "wait_brief"

        elif phase == "wait_brief":
            if not self.context.busy:
                log("[gui] 数据简报生成结束")
                self.phase = "chat"

        elif phase == "chat":
            log("[gui] 触发数据问答…")
            self.window.nav.setCurrentRow(INDEX_AI)
            self.window.ai_page.question_edit.setText("抖音和B站哪个平台互动更好？")
            self.window.ai_page._ask()
            self.phase = "wait_chat"

        elif phase == "wait_chat":
            if not self.context.busy:
                log("[gui] 问答结束")
                self.phase = "consulting"

        elif phase == "consulting":
            log("[gui] 触发创作咨询…")
            self.window.nav.setCurrentRow(INDEX_CONSULTING)
            page = self.window.consulting_page
            page.question_edit.setPlainText("结合当前数据，我这一周应该优先做哪几个选题？")
            page.force_local_box.setChecked(True)
            page._generate()
            self.phase = "wait_consulting"

        elif phase == "wait_consulting":
            if not self.context.busy:
                log("[gui] 咨询建议生成结束")
                self.phase = "drama_create"

        elif phase == "drama_create":
            log("[gui] 创建短剧项目…")
            self.window.nav.setCurrentRow(INDEX_DRAMA)
            page = self.window.drama_page
            page.title_edit.setText("面试当天，我拿到了老板的把柄")
            page.logline_edit.setPlainText(
                "新人意外掌握上司的违规证据，被迫在保住工作与说出真相之间做选择。"
            )
            page.style_edit.setText("写实都市夜景，冷色高对比，手持镜头")
            page.force_local_box.setChecked(True)
            page._create_project()
            self.phase = "drama_outline"

        elif phase == "drama_outline":
            log("[gui] 生成分集大纲…")
            self.window.drama_page._generate_outline()
            self.phase = "wait_drama_outline"

        elif phase == "wait_drama_outline":
            if not self.context.busy:
                episodes = self.window.drama_page.episode_list.count()
                log("[gui] 大纲生成结束，共 {} 集".format(episodes))
                self.phase = "drama_script"

        elif phase == "drama_script":
            log("[gui] 生成分集剧本…")
            self.window.drama_page._generate_script()
            self.phase = "wait_drama_script"

        elif phase == "wait_drama_script":
            if not self.context.busy:
                log("[gui] 剧本生成结束")
                self.phase = "drama_storyboard"

        elif phase == "drama_storyboard":
            log("[gui] 生成镜头分镜…")
            self.window.drama_page._generate_storyboard()
            self.phase = "wait_drama_storyboard"

        elif phase == "wait_drama_storyboard":
            if not self.context.busy:
                rows = self.window.drama_page.storyboard_model.rowCount()
                log("[gui] 分镜生成结束，共 {} 个镜头".format(rows))
                self.phase = "repo_page"

        elif phase == "repo_page":
            log("[gui] 数据仓库页：生成数据模板…")
            self.window.nav.setCurrentRow(INDEX_DATA)
            self.window.data_page.template_button.click()
            self.phase = "wait_repo"

        elif phase == "wait_repo":
            if not self.context.busy:
                log("[gui] 数据仓库页操作完成")
                self.phase = "shots2"

        elif phase == "shots2":
            self.capture("final")
            self.phase = "finish"

        elif phase == "finish":
            self.finish()

    def capture(self, suffix: str = "") -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for index, name in enumerate(PAGES):
            try:
                self.window.nav.setCurrentRow(index)
                self.app.processEvents()
                time.sleep(0.15)
                self.app.processEvents()
                path = self.out_dir / "{:02d}_{}{}.png".format(
                    index + 1, name, ("_" + suffix) if suffix else ""
                )
                ok = self.window.grab().save(str(path))
                if ok:
                    self.shots.append(path)
                log("[gui] 截图 {} -> {}".format(name, "成功" if ok else "失败"))
            except BaseException as exc:  # noqa: BLE001 - 诊断用，逐页继续
                log("[gui] 页面 {} 截图异常: {!r}".format(name, exc))

    def finish(self) -> None:
        self.timer.stop()
        log("[gui] 完成，共 {} 张截图 -> {}".format(len(self.shots), self.out_dir))
        self.app.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="界面冒烟测试")
    parser.add_argument("--no-import", action="store_true", help="不导入样例数据")
    parser.add_argument("--out", default="", help="截图输出目录（默认系统临时目录）")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def _excepthook(exc_type, exc, tb) -> None:
        """PySide6 中槽函数抛出的异常会导致进程中止，先把栈打出来便于定位。"""
        import traceback

        log("[gui] 未捕获异常:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _excepthook

    ensure_dirs()
    crash_log = Path(tempfile.gettempdir()) / "ccd_gui_crash.log"
    try:
        import faulthandler

        faulthandler.enable(open(crash_log, "w", encoding="utf-8"))
    except OSError:
        pass

    app = QApplication(sys.argv)
    app.setStyleSheet(theme_module.current_stylesheet())

    context = AppContext()
    window = MainWindow(context)
    window.resize(1480, 940)
    window.show()

    out_dir = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "ccd_gui_shots"
    driver = Driver(app, window, out_dir, import_data=not args.no_import)
    app.exec()
    return 0 if driver.shots else 1


if __name__ == "__main__":
    raise SystemExit(main())
