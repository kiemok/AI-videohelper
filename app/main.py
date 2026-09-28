"""桌面端程序入口。

运行：
    .venv\\Scripts\\python.exe -m app.main
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app import __app_name__, __version__
from app.config import ensure_dirs, load_settings
from app.ui import theme as theme_module
from app.ui.context import AppContext
from app.ui.main_window import MainWindow


def main() -> int:
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)

    # 外观主题（浅黑 / 浅白 / 浅蓝）：读取用户配置，默认浅黑
    settings = load_settings()
    theme_module.apply_theme(settings.theme)
    app.setStyleSheet(theme_module.current_stylesheet())

    context = AppContext()
    window = MainWindow(context)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
