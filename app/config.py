"""全局配置管理。

设计要点：
- 配置以 JSON 文件形式保存在**用户目录**（Windows 为 ``%APPDATA%\\DataPulseAI\\settings.json``，
  其它系统为 ``~/.config/DataPulseAI/settings.json``）。放在项目目录**之外**，
  是为了让「拷贝 / 打包 / 分发源码」时不会带走大模型 API Key。
- 旧版本位于 ``<项目根>/config/settings.json`` 的配置会在首次运行时自动迁移过去（见
  :func:`migrate_legacy_config`），旧文件会被**移出项目目录**，避免它仍含 Key 被一起打包。
- 可用环境变量 ``CCD_CONFIG_PATH`` 覆盖配置文件位置。
- 读取时对缺失/多余字段做容错，便于后续版本平滑新增配置项。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DIR = DATA_DIR / "samples"
ARCHIVE_DIR = DATA_DIR / "archive"
LOG_DIR = PROJECT_ROOT / "logs"

#: 旧版本的配置位置（项目目录内）；首次运行时会自动迁移到用户目录
LEGACY_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"


def user_config_dir() -> Path:
    """用户级配置目录：Windows 取 ``%APPDATA%\\DataPulseAI``，其它系统取 ``~/.config/DataPulseAI``。"""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "DataPulseAI"
    return Path.home() / ".config" / "DataPulseAI"


DEFAULT_CONFIG_PATH = user_config_dir() / "settings.json"

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
class McpServerSettings:
    """MCP（Model Context Protocol）服务器配置。

    支持两种传输方式：

    - ``stdio``：本地命令启动的服务器（例如 ``npx -y @modelcontextprotocol/server-filesystem``）
    - ``sse``  ：远程 HTTP/SSE 服务器（填写 url 即可）

    只有标记为启用（``enabled=True``）的服务器，其工具才会出现在 AI 咨询的可用工具里。
    """

    name: str = ""  # 显示名，同时作为工具名前缀
    enabled: bool = False
    transport: str = "stdio"  # stdio / sse
    command: str = ""  # stdio：可执行命令（python / npx / uvx …）
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""  # sse：服务器地址
    timeout: int = 30  # 单次调用超时（秒）

    def is_configured(self) -> bool:
        if self.transport == "sse":
            return bool(self.url.strip())
        return bool(self.command.strip())

    def describe(self) -> str:
        if self.transport == "sse":
            return f"SSE · {self.url}"
        command = " ".join([self.command, *self.args[:3]]).strip()
        return f"stdio · {command}"


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
    skills_dir: str = ""  # 自定义技能目录，留空 = <项目根>/skills
    skills_enabled: list[str] = field(default_factory=list)  # 已启用的技能 slug
    mcp_servers: list[McpServerSettings] = field(default_factory=list)  # MCP 服务器列表
    #: 数据看板「作品表现 TOP」区域高度占比（0.2~0.8）；上下拖动分隔条调整后自动保存
    dashboard_top_ratio: float = 0.45
    #: 评论情感分析引擎：lexicon（离线词典法，默认）/ llm（大模型批量打标）
    sentiment_engine: str = "lexicon"
    #: 视频创作咨询是否启用 RAG 检索（从本地库检索相关作品/评论素材注入提示词）
    consulting_rag_enabled: bool = True

    def resolved_db_url(self) -> str:
        if self.db_url.strip():
            return self.db_url.strip()
        return default_sqlite_url()


_NESTED_TYPES.update({"llm": LLMSettings, "data_repo": DataRepoSettings})
#: 嵌套的 dataclass 列表（JSON 中为对象数组）
_NESTED_LIST_TYPES: dict[str, type] = {"mcp_servers": McpServerSettings}


def default_sqlite_url() -> str:
    """默认本地 SQLite 存储；在设置页改为 ``mysql+pymysql://user:pwd@host:3306/db`` 即可切 MySQL。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (DATA_DIR / "content_decision.db").as_posix()


def config_path() -> Path:
    override = os.environ.get("CCD_CONFIG_PATH", "").strip()
    return Path(override) if override else DEFAULT_CONFIG_PATH


def migrate_legacy_config() -> Path | None:
    """把旧版「项目内 config/settings.json」迁移到用户目录（幂等）。

    仅当**新位置尚无配置**且旧文件存在时执行一次：复制到用户目录，并把旧文件**移到用户目录**
    改名 ``settings.legacy-backup.json`` —— 项目目录里不再保留任何含 Key 的文件（否则拷贝源码时
    仍会把它带走），同时内容得以备份。显式设置 ``CCD_CONFIG_PATH`` 时不做任何迁移
    （测试 / 多环境隔离依赖这一点）。

    返回迁移后的新配置路径；未发生迁移时返回 ``None``。
    """
    if os.environ.get("CCD_CONFIG_PATH", "").strip():
        return None
    if DEFAULT_CONFIG_PATH.exists() or not LEGACY_CONFIG_PATH.is_file():
        return None
    try:
        DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_CONFIG_PATH, DEFAULT_CONFIG_PATH)
        backup = DEFAULT_CONFIG_PATH.with_name("settings.legacy-backup.json")
        LEGACY_CONFIG_PATH.replace(backup)
    except OSError:
        return None
    return DEFAULT_CONFIG_PATH


def _build_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """按字段名过滤后构造 dataclass，忽略未知键、补全缺失键（支持嵌套配置）。"""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        nested = _NESTED_TYPES.get(f.name)
        nested_list = _NESTED_LIST_TYPES.get(f.name)
        if nested is not None:
            kwargs[f.name] = _build_dataclass(nested, value or {})
        elif nested_list is not None:
            kwargs[f.name] = [
                _build_dataclass(nested_list, item)
                for item in (value or [])
                if isinstance(item, dict)
            ]
        else:
            kwargs[f.name] = value
    # dataclass 自身负责补齐缺少字段的默认值
    return cls(**kwargs)  # type: ignore[arg-type]


def load_settings(path: Path | None = None) -> AppSettings:
    """读取配置；文件不存在或损坏时回退到默认配置。

    未显式指定 ``path`` 时，会先尝试把旧版「项目内 config/settings.json」迁移到用户目录
    （幂等，见 :func:`migrate_legacy_config`）。
    """
    if path is None:
        migrate_legacy_config()
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
