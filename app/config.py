"""全局配置管理。

设计要点：
- 配置以 JSON 文件形式保存在**用户本地**（默认 ``<项目根>/config/settings.json``），
  大模型 API Key 只写入该文件，不进入版本库（见 .gitignore）。
- 可用环境变量 ``CCD_CONFIG_PATH`` 覆盖配置文件位置。
- 读取时对缺失/多余字段做容错，便于后续版本平滑新增配置项。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DIR = DATA_DIR / "samples"
ARCHIVE_DIR = DATA_DIR / "archive"
LOG_DIR = PROJECT_ROOT / "logs"

# 大模型服务商预设（均为 OpenAI 兼容协议）
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "label": "通义千问(DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "custom": {
        "label": "自定义(OpenAI 兼容)",
        "base_url": "",
        "model": "",
    },
}

# 支持的平台标识
PLATFORMS: tuple[str, ...] = ("bilibili", "douyin")
PLATFORM_LABELS: dict[str, str] = {"bilibili": "B站", "douyin": "抖音"}


def platform_label(key: str) -> str:
    """平台中文名。"""
    return PLATFORM_LABELS.get(key, key)


@dataclass
class LLMSettings:
    """大模型调用配置。API Key 由用户在设置页填写，保存在本地配置文件。"""

    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""  # 留空则使用 provider 预设
    model: str = ""  # 留空则使用 provider 预设
    temperature: float = 0.6
    max_tokens: int = 1200
    timeout: int = 60

    def resolved_base_url(self) -> str:
        if self.base_url.strip():
            return self.base_url.strip().rstrip("/")
        return PROVIDER_PRESETS.get(self.provider, {}).get("base_url", "")

    def resolved_model(self) -> str:
        if self.model.strip():
            return self.model.strip()
        return PROVIDER_PRESETS.get(self.provider, {}).get("model", "")

    @property
    def is_configured(self) -> bool:
        """是否已具备真实调用条件（有 Key + 有 base_url + 有模型名）。"""
        return bool(self.api_key.strip() and self.resolved_base_url() and self.resolved_model())


#: 嵌套配置类型注册（用于 JSON → dataclass 的递归构造）
_NESTED_TYPES: dict[str, type] = {}


@dataclass
class DataRepoSettings:
    """数据仓库（Git）配置。

    数据由用户自建仓库提供（定期爬取后推送），软件只负责**拉取与导入**，
    不在软件内部执行任何爬取行为。
    """

    url: str = ""  # 仓库地址（https / ssh / 本地路径 / 归档 ZIP 链接）
    branch: str = "main"
    local_dir: str = ""  # 本地缓存目录，留空 = <项目根>/data/repo
    subdir: str = ""  # 仓库内数据子目录，留空 = 仓库根目录
    mode: str = "auto"  # auto / git / zip / local
    auto_pull: bool = True  # 定时任务触发时是否先拉取最新数据

    def resolved_local_dir(self) -> Path:
        if self.local_dir.strip():
            return Path(self.local_dir.strip())
        return DATA_DIR / "repo"

    @property
    def is_configured(self) -> bool:
        return bool(self.url.strip() or self.local_dir.strip())

    def describe(self) -> str:
        if not self.is_configured:
            return "未配置数据仓库"
        target = self.url.strip() or str(self.resolved_local_dir())
        return f"{target}（{self.branch}）"


@dataclass
class AppSettings:
    """应用级配置。"""

    db_url: str = ""
    log_level: str = "INFO"
    http_proxy: str = ""  # 形如 http://127.0.0.1:7890，留空表示直连
    schedule_enabled: bool = False
    schedule_time: str = "08:30"  # 每日自动执行分析的时间
    theme: str = "dark"  # 外观主题：dark（浅黑）/ light（浅白）/ blue（浅蓝）
    llm: LLMSettings = field(default_factory=LLMSettings)
    data_repo: DataRepoSettings = field(default_factory=DataRepoSettings)

    def resolved_db_url(self) -> str:
        if self.db_url.strip():
            return self.db_url.strip()
        return default_sqlite_url()


_NESTED_TYPES.update({"llm": LLMSettings, "data_repo": DataRepoSettings})


def default_sqlite_url() -> str:
    """默认本地 SQLite 存储；在设置页改为 ``mysql+pymysql://user:pwd@host:3306/db`` 即可切 MySQL。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (DATA_DIR / "content_decision.db").as_posix()


def config_path() -> Path:
    override = os.environ.get("CCD_CONFIG_PATH", "").strip()
    return Path(override) if override else DEFAULT_CONFIG_PATH


def _build_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """按字段名过滤后构造 dataclass，忽略未知键、补全缺失键（支持嵌套配置）。"""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        nested = _NESTED_TYPES.get(f.name)
        if nested is not None:
            kwargs[f.name] = _build_dataclass(nested, value or {})
        else:
            kwargs[f.name] = value
    # dataclass 自身负责补齐缺少字段的默认值
    return cls(**kwargs)  # type: ignore[arg-type]


def load_settings(path: Path | None = None) -> AppSettings:
    """读取配置；文件不存在或损坏时回退到默认配置。"""
    path = path or config_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppSettings()
        return _build_dataclass(AppSettings, raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    """写入配置到用户本地（原子替换，避免写坏文件）。"""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def ensure_dirs() -> None:
    """确保运行期目录存在。"""
    for d in (DEFAULT_CONFIG_PATH.parent, DATA_DIR, SAMPLE_DIR, ARCHIVE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
