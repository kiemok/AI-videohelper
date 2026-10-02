"""提示词模板库：把大模型的「角色设定」抽成可编辑文件，不改代码也能调优。

设计要点：

- **默认内置于代码**（``DEFAULTS``），开箱即用，无需任何文件；
- 用户可在 ``<项目根>/prompts/`` 放同名 ``.md`` 文件覆盖对应模板；
- 文件缺失或内容为空时**自动回退**内置默认 —— 误删模板不会让功能失效；
- 每次构造请求时读取（文件很小，读盘开销可忽略），因此改完文件即可生效，无需重启。

对应关系：``chat.system`` 供 AI 咨询，``brief.system`` 供洞察/选题/标题等生成任务，
``consulting.system`` 供视频创作咨询，``drama.system`` 供 AI 短剧三级生成。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: 内置默认模板内容（单一来源：各处提示词模块都从这里取）
CHAT_SYSTEM_DEFAULT = (
    "你是一名短视频内容创作顾问，服务对象是同时运营 B站 与 抖音 的创作者。"
    "你会收到结构化的数据分析结果，请用简体中文输出：语言通俗、结论先行、"
    "给出可执行的动作建议，避免空话；涉及数字时直接引用数据；"
    "不确定的地方要说明推测依据，不要编造未提供的数据。"
)

CONSULTING_SYSTEM_DEFAULT = (
    "你是一名深耕 B站与抖音的短视频创作顾问，擅长把数据结论翻译成创作者可直接执行的行动方案。"
    "回答要求：简体中文、结论先行、分点、每条建议都说明依据（引用提供的数据），"
    "必要时给出示例标题或脚本片段；不要编造未提供的数据。"
)

DRAMA_SYSTEM_DEFAULT = (
    "你是一名擅长抖音/B站竖屏短剧的编剧与分镜师，熟悉 3 秒钩子、强冲突、快节奏反转与结尾悬念的写法。"
    "输出使用简体中文，结构化、可直接拍摄执行；台词口语化，避免书面语。"
)


def default_prompt_dir() -> Path:
    """默认模板目录：``<项目根>/prompts``。"""
    return Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class PromptInfo:
    """一个可覆盖的提示词模板（元信息 + 内置默认）。"""

    key: str
    filename: str
    name: str
    description: str
    default: str


DEFAULTS: tuple[PromptInfo, ...] = (
    PromptInfo(
        key="chat.system",
        filename="chat.system.md",
        name="AI 咨询角色设定",
        description="右侧 AI 咨询面板与「AI 决策助手」自由问答使用的系统提示词",
        default=CHAT_SYSTEM_DEFAULT,
    ),
    PromptInfo(
        key="brief.system",
        filename="brief.system.md",
        name="数据洞察生成角色设定",
        description="数据简报 / 爆款选题 / 标题优化 / 发布时机等生成任务的系统提示词",
        default=CHAT_SYSTEM_DEFAULT,
    ),
    PromptInfo(
        key="consulting.system",
        filename="consulting.system.md",
        name="视频创作咨询角色设定",
        description="「视频创作咨询」页生成行动方案时使用的系统提示词",
        default=CONSULTING_SYSTEM_DEFAULT,
    ),
    PromptInfo(
        key="drama.system",
        filename="drama.system.md",
        name="AI 短剧创作角色设定",
        description="「AI 短剧工坊」生成大纲 / 剧本 / 分镜时使用的系统提示词",
        default=DRAMA_SYSTEM_DEFAULT,
    ),
)

_BY_KEY: dict[str, PromptInfo] = {item.key: item for item in DEFAULTS}


@dataclass
class PromptTemplate:
    """列表展示用：模板元信息 + 当前生效内容。"""

    key: str
    name: str
    description: str
    default: str
    content: str
    path: Path

    @property
    def overridden(self) -> bool:
        """当前内容是否来自用户文件（与内置默认不同）。"""
        return self.content.strip() != self.default.strip()


def _require(key: str) -> PromptInfo:
    info = _BY_KEY.get(key)
    if info is None:
        raise KeyError(f"未知的提示词模板：{key}")
    return info


def prompt_text(key: str, directory: Path | None = None) -> str:
    """取生效的提示词：用户文件优先，否则内置默认（未知 key 返回空串）。"""
    info = _BY_KEY.get(key)
    if info is None:
        return ""
    path = (directory or default_prompt_dir()) / info.filename
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    return info.default


def load_templates(directory: Path | None = None) -> list[PromptTemplate]:
    """列出全部模板及其当前生效内容。"""
    base = directory or default_prompt_dir()
    return [
        PromptTemplate(
            key=item.key,
            name=item.name,
            description=item.description,
            default=item.default,
            content=prompt_text(item.key, base),
            path=base / item.filename,
        )
        for item in DEFAULTS
    ]


def save_template(key: str, content: str, directory: Path | None = None) -> Path:
    """保存（或覆盖）用户模板文件。"""
    info = _require(key)
    base = directory or default_prompt_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / info.filename
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def reset_template(key: str, directory: Path | None = None) -> bool:
    """删除用户覆盖文件以恢复内置默认；返回是否真的删除了文件。"""
    info = _require(key)
    path = (directory or default_prompt_dir()) / info.filename
    try:
        path.unlink()
        return True
    except (FileNotFoundError, OSError):
        return False


def ensure_default_files(directory: Path | None = None, overwrite: bool = False) -> list[Path]:
    """把内置默认写成文件，方便用户直接编辑；返回本次写出的文件列表。"""
    base = directory or default_prompt_dir()
    base.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in DEFAULTS:
        path = base / item.filename
        if path.exists() and not overwrite:
            continue
        path.write_text(item.default.strip() + "\n", encoding="utf-8")
        written.append(path)
    return written
