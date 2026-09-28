"""数据接入层：契约、双平台字段融合、导入流水线与演示数据。

软件内**不再包含爬取逻辑**——数据由用户自建的仓库提供（见 ``app/datasource``），
本包负责把这些数据融合归一化后写入统一数据模型。
"""

from app.collect.contracts import ImportResult, RawBatch
from app.collect.pipeline import (
    archive_snapshots_csv,
    import_batch,
    import_csv_dir,
    sync_sample_data,
)

__all__ = [
    "ImportResult",
    "RawBatch",
    "archive_snapshots_csv",
    "import_batch",
    "import_csv_dir",
    "sync_sample_data",
]
