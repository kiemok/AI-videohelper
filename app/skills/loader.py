"""自定义技能（Skill）：用户可维护的专家提示词包。

设计目标：让用户像写笔记一样扩展 AI 咨询的能力，不需要改代码。

- **存储形式**：每个技能一个 Markdown 文件（YAML 头部 + 正文提示词），
  可放在项目的 ``skills/`` 目录，也可指向任意文件夹；
- **零依赖解析**：头部只支持 ``key: value``、``key: [a, b]`` 与 ``- item`` 列表，
  不引入 YAML 库；
- **生效方式**：在咨询面板勾选启用的技能，其提示词会注入到大模型的 system prompt。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_SKILLS_DIR = PROJECT_ROOT / "skills"
_SLUG_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")


def default_skills_dir() -> Path:
    """默认技能目录：<项目根>/skills。"""
    return _DEFAULT_SKILLS_DIR


def slugify(text: str) -> str:
    """把技能名转成可用的文件名（保留中英文与数字）。"""
    slug = _SLUG_RE.sub("-", (text or "").strip()).strip("-")
    return slug[:60] or "skill"


@dataclass
class Skill:
    """一个自定义技能。"""

    slug: str
    name: str
    description: str = ""
    scenario: str = ""
    tags: list[str] = field(default_factory=list)
    prompt: str = ""
    path: Path | None = None
    builtin: bool = False

    def to_markdown(self) -> str:
        """序列化为 Markdown 文件内容。"""
        lines = ["---", f"name: {self.name}"]
        if self.description:
            lines.append(f"description: {self.description}")
        if self.scenario:
            lines.append(f"scenario: {self.scenario}")
        if self.tags:
            lines.append("tags: [" + ", ".join(self.tags) + "]")
        lines.append(f"builtin: {str(self.builtin).lower()}")
        lines.append("---")
        lines.append("")
        lines.append(self.prompt.strip())
        lines.append("")
        return "\n".join(lines)

    def brief(self) -> str:
        parts = [self.name]
        if self.tags:
            parts.append("·".join(self.tags))
        return "  ".join(parts)


# --------------------------------------------------------------------------- #
# front-matter 解析（零依赖）
# --------------------------------------------------------------------------- #
def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """解析 YAML 头部，返回 (元数据, 正文)。无头部时返回 ({}, 原文)。"""
    normalized = text.replace("\r\n", "\n")
    if not normalized.lstrip().startswith("---"):
        return {}, normalized.strip()

    lines = normalized.split("\n")
    start = next(i for i, line in enumerate(lines) if line.strip() == "---")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"),
        None,
    )
    if end is None:
        return {}, normalized.strip()

    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in lines[start + 1 : end]:
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.lstrip().startswith("-") and current_list_key:
            value = line.lstrip()[1:].strip().strip("\"'")
            meta.setdefault(current_list_key, []).append(value)
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("\"'") for v in value[1:-1].split(",")]
            meta[key] = [v for v in items if v]
            current_list_key = key
        elif value == "":
            meta[key] = []
            current_list_key = key
        else:
            meta[key] = value.strip("\"'")
            current_list_key = None

    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def parse_skill_text(slug: str, text: str, path: Path | None = None) -> Skill:
    """把技能文件文本解析成 Skill；头部缺失时用文件名作为技能名。"""
    meta, body = parse_front_matter(text)
    name = str(meta.get("name") or slug).strip()
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[|,，]", tags) if t.strip()]
    return Skill(
        slug=slug,
        name=name or slug,
        description=str(meta.get("description") or "").strip(),
        scenario=str(meta.get("scenario") or "").strip(),
        tags=[str(t) for t in tags],
        prompt=body,
        path=path,
        builtin=str(meta.get("builtin", "false")).lower() in {"true", "1", "yes"},
    )


# --------------------------------------------------------------------------- #
# 加载 / 保存 / 删除
# --------------------------------------------------------------------------- #
def load_skills(directory: Path | str | None = None) -> list[Skill]:
    """扫描目录下的所有技能文件（``*.md`` / ``*.markdown``）。"""
    root = Path(directory) if directory else default_skills_dir()
    if not root.exists():
        return []
    skills: list[Skill] = []
    for path in sorted(root.glob("*.md")) + sorted(root.glob("*.markdown")):
        if path.name.lower().startswith(("readme", "data_format")):
            continue
        try:
            skill = parse_skill_text(path.stem, path.read_text(encoding="utf-8"), path)
        except OSError as exc:
            logger.warning("读取技能文件失败 %s: %s", path.name, exc)
            continue
        if skill.prompt:
            skills.append(skill)
    return skills


def save_skill(skill: Skill, directory: Path | str | None = None) -> Path:
    """写入 / 覆盖一个技能文件（界面新建或编辑时调用）。"""
    root = Path(directory) if directory else default_skills_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = skill.path if skill.path and skill.path.parent == root else root / f"{skill.slug}.md"
    path.write_text(skill.to_markdown(), encoding="utf-8")
    logger.info("技能已保存：%s", path)
    return path


def delete_skill(skill: Skill) -> bool:
    """删除技能文件（内置示例同样允许删除）。"""
    if not skill.path or not skill.path.exists():
        return False
    try:
        skill.path.unlink()
        logger.info("技能已删除：%s", skill.path.name)
        return True
    except OSError as exc:
        logger.warning("删除技能失败 %s: %s", skill.path, exc)
        return False


def build_skill_prompt(skills: list[Skill], limit_chars: int = 6000) -> str:
    """把启用的技能拼接为注入 system prompt 的片段。"""
    selected = [s for s in skills if s.prompt.strip()]
    if not selected:
        return ""
    lines = [
        "【已启用的创作技能】以下是用户为本轮咨询启用的专家技能，请在回答中严格遵循其要求："
    ]
    for index, skill in enumerate(selected, 1):
        lines.append(f"\n### 技能 {index}：{skill.name}")
        if skill.scenario:
            lines.append(f"适用场景：{skill.scenario}")
        lines.append(skill.prompt.strip())
    text = "\n".join(lines)
    return text if len(text) <= limit_chars else text[:limit_chars] + "\n（技能内容过长已截断）"


# --------------------------------------------------------------------------- #
# 内置示例技能（首次运行时写入技能目录，用户可自由修改或删除）
# --------------------------------------------------------------------------- #
_BUILTIN_SKILLS: tuple[tuple[str, str], ...] = (
    (
        "抖音三秒钩子专家",
        """---
name: 抖音三秒钩子专家
description: 为抖音短视频设计前 3 秒钩子与开场节奏
scenario: 需要提升抖音完播率、观看留存、开头吸引力时启用
tags: [抖音, 钩子, 完播率]
builtin: true
---

你是抖音短视频「前 3 秒钩子」专家。请遵守：

1. 每条建议都要给出**可直接念出口的钩子文案**（≤20 字），并注明它触发的心理机制（好奇缺口 / 利益承诺 / 冲突反转 / 身份认同）。
2. 结合当前数据指出问题：若数据里出现完播率、互动率、涨粉、健康度等指标，必须直接引用具体数字，不要空谈。
3. 为每个钩子指定**一个可直接拍摄的镜头**（画面 + 机位 + 字幕），便于照着拍。
4. 禁止"要有吸引力""更抓人"这类没有信息量的说法。
""",
    ),
    (
        "B站长视频脚本顾问",
        """---
name: B站长视频脚本顾问
description: 面向 B站 中长视频的结构化脚本与信息密度建议
scenario: 制作 8 分钟以上的深度内容、需要脚本结构与节奏建议时启用
tags: [B站, 脚本, 长视频]
builtin: true
---

你是 B站 中长视频的脚本顾问。请遵守：

1. 按「钩子 → 冲突/铺垫 → 证据 → 结论 → 互动引导」五段式给出可执行脚本框架，并标注每段建议时长。
2. 明确说明**信息密度**安排（每分钟出现几个关键信息点），并解释与 B站 用户观看习惯的关系。
3. 若数据中有收藏率、评论率、弹幕数等指标，请引用它们判断内容是否"值得收藏"，并给出提升沉淀价值的写法。
4. 结尾必须给出一句可念出的互动引导语（引导评论或三连，且不生硬）。
""",
    ),
    (
        "数据分析师（严格引用数据）",
        """---
name: 数据分析师（严格引用数据）
description: 只用给定数据下结论，明确区分事实与推测
scenario: 需要严谨的数据解读、担心大模型编数据时启用
tags: [数据, 严谨, 解读]
builtin: true
---

你是严谨的数据分析师。请遵守：

1. **所有结论必须能追溯到提供的数据**，引用时给出具体数值与日期；没有数据支撑的判断必须显式标注为「推测」并说明依据。
2. 严格区分三种表述：**事实**（数据直读）、**推断**（有数据基础的判断）、**假设**（无数据、需要验证）。
3. 对样本量不足的情况主动提示（例如"仅 3 天数据，趋势结论参考价值有限"）。
4. 不使用"大幅提升""显著增长"等模糊词，改为给出具体数值与百分比。
""",
    ),
    (
        "标题实验室",
        """---
name: 标题实验室
description: 批量产出标题并给出 A/B 测试与投放建议
scenario: 需要起标题、做标题 A/B 测试时启用
tags: [标题, A/B测试, 封面]
builtin: true
---

你是短视频标题实验室。请遵守：

1. 一次给出 **6 个标题版本**，并按「结果承诺型 / 悬念型 / 冲突型 / 数字清单型 / 身份代入型 / 反差型」分类标注。
2. 每个标题后附：适用平台（B站/抖音）、字数、判断的点击动机、与封面的配合方式（封面不重复标题信息）。
3. 给出 **A/B 测试方案**：先测哪两个、观察哪个指标（点击率 / 前 3 秒留存 / 完播率）、测多久、如何判定胜负。
4. 若数据里提供了历史高表现的标题或热词，优先复用其中的关键词。
""",
    ),
)


def ensure_builtin_skills(directory: Path | str | None = None) -> list[Path]:
    """首次运行时写入内置示例技能；已存在同名文件则不覆盖。"""
    root = Path(directory) if directory else default_skills_dir()
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in _BUILTIN_SKILLS:
        path = root / f"{slugify(name)}.md"
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)
    if written:
        logger.info("已写入 %d 个内置示例技能 -> %s", len(written), root)
    return written
