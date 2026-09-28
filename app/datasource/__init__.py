"""数据仓库模块：从用户自建的 Git 仓库拉取数据并导入统一模型。

设计原则：**软件内不做任何爬取**。数据由用户在外部定期采集后推送到仓库，
软件只负责按配置拉取（git / zip / 本地目录）并把仓库内容解析入本地库。
"""

from app.datasource.loader import RepoScan, import_repository, read_rows, scan_repository
from app.datasource.sync import SyncResult, archive_url, repository_status, sync_repository
from app.datasource.templates import write_data_templates

__all__ = [
    "RepoScan",
    "SyncResult",
    "import_repository",
    "read_rows",
    "scan_repository",
    "sync_repository",
    "repository_status",
    "archive_url",
    "write_data_templates",
]
