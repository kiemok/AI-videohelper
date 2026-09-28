"""日志与告警模块：控制台 + 滚动文件双通道。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


class Alerter(logging.Handler):
    """简易告警通道：ERROR 及以上级别写入 logs/alerts.log，供后续接入邮件/消息推送。"""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.ERROR)
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(self.format(record) + "\n")
        except OSError:  # 告警通道本身不允许影响主流程
            pass


def setup_logging(level: str = "INFO") -> logging.Logger:
    """初始化根日志器，重复调用只生效一次。"""
    global _configured
    root = logging.getLogger()
    if _configured:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return root

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    alerter = Alerter(LOG_DIR / "alerts.log")
    alerter.setFormatter(formatter)
    root.addHandler(alerter)

    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
