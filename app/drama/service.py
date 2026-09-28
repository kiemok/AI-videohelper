"""AI 短剧服务：大纲 → 剧本 → 分镜 三级生成，并预留文生图/文生视频接口。

- 文本生成复用 ``app.ai.client.LLMClient``（OpenAI 兼容），无 Key 时回退结构化模板；
- 分镜会同时产出 ``image_prompt`` / ``video_prompt``，为后续接入文生图、文生视频
  （图生视频/首尾帧等）留好数据位。
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.client import LLMClient, LLMError
from app.config import AppSettings
from app.core.logging_setup import get_logger
from app.drama import prompts as P
from app.drama.repository import (
    create_project,
    delete_project,
    get_episode,
    get_project,
    list_episodes,
    list_projects,
    list_scenes,
    replace_episodes,
    replace_scenes,
    update_episode_script,
    update_project,
)

logger = get_logger(__name__)

#: 多模态能力（预留）：界面据此展示"待接入"状态
MULTIMODAL_ROADMAP: tuple[dict[str, str], ...] = (
    {"name": "文生图（关键帧）", "status": "预留", "hint": "分镜表中已生成 image_prompt，接入图像模型即可批量出图"},
    {"name": "文生视频（镜头片段）", "status": "预留", "hint": "已生成 video_prompt 与镜头时长，可直接对接视频模型"},
    {"name": "配音与字幕", "status": "预留", "hint": "台词已结构化，可接入 TTS 生成配音并自动对齐字幕"},
    {"name": "自动剪辑合成", "status": "预留", "hint": "按分镜时长拼接片段，输出竖屏成片"},
)


class DramaService:
    def __init__(self, settings: AppSettings, db_url: str) -> None:
        self.settings = settings
        self.db_url = db_url

    # ------------------------------------------------------------------ #
    @property
    def client(self) -> LLMClient:
        return LLMClient(self.settings.llm, self.settings.http_proxy)

    def status_text(self) -> str:
        llm = self.settings.llm
        if llm.is_configured:
            return f"编剧模型：{llm.provider} / {llm.resolved_model()}"
        return "编剧模型：未配置 API Key（本地模板生成）"

    # ------------------------------------------------------------------ #
    def projects(self) -> list[dict[str, Any]]:
        return list_projects(self.db_url)

    def create(
        self,
        title: str,
        genre: str,
        target_platform: str = "douyin",
        aspect_ratio: str = "9:16",
        logline: str = "",
        style: str = "",
    ) -> int:
        return create_project(
            self.db_url, title, genre, target_platform, aspect_ratio, logline, style
        )

    def remove(self, project_id: int) -> None:
        delete_project(self.db_url, project_id)

    def project(self, project_id: int) -> dict[str, Any] | None:
        return get_project(self.db_url, project_id)

    def episodes(self, project_id: int) -> list[dict[str, Any]]:
        return list_episodes(self.db_url, project_id)

    def scenes(self, project_id: int, episode_no: int) -> list[dict[str, Any]]:
        episode = get_episode(self.db_url, project_id, episode_no)
        if not episode:
            return []
        return list_scenes(self.db_url, int(episode["id"]))

    # ------------------------------------------------------------------ #
    def _generate(self, messages: list[dict[str, str]], fallback, force_local: bool):
        """统一的大模型/本地回退调用，返回 (内容, provider, model, is_fallback, error)。"""
        if force_local or not self.client.is_available:
            return fallback(), "local", "template-engine", True, ""
        try:
            result = self.client.chat(messages)
            return result.content, result.provider, result.model, False, ""
        except LLMError as exc:
            logger.error("短剧生成失败，回退本地模板: %s", exc)
            return fallback(), "local", "template-engine", True, str(exc)

    # ------------------------------------------------------------------ #
    def generate_outline(
        self, project_id: int, episode_count: int = 6, force_local: bool = False
    ) -> dict[str, Any]:
        project = get_project(self.db_url, project_id)
        if not project:
            return {"error": "项目不存在"}
        content, provider, model, is_fallback, error = self._generate(
            P.build_outline_messages(project, episode_count),
            lambda: P.local_outline(project, episode_count),
            force_local,
        )
        episodes = _parse_outline(content, episode_count)
        replace_episodes(self.db_url, project_id, episodes)
        update_project(
            self.db_url, project_id, episode_count=len(episodes), status="outlined"
        )
        return {
            "content": content,
            "episodes": episodes,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
        }

    def generate_script(
        self, project_id: int, episode_no: int, force_local: bool = False
    ) -> dict[str, Any]:
        project = get_project(self.db_url, project_id)
        episode = get_episode(self.db_url, project_id, episode_no)
        if not project or not episode:
            return {"error": "项目或分集不存在"}
        content, provider, model, is_fallback, error = self._generate(
            P.build_script_messages(project, episode),
            lambda: P.local_script(project, episode),
            force_local,
        )
        update_episode_script(self.db_url, int(episode["id"]), content)
        update_project(self.db_url, project_id, status="scripted")
        return {
            "content": content,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
        }

    def generate_storyboard(
        self, project_id: int, episode_no: int, shot_count: int = 12, force_local: bool = False
    ) -> dict[str, Any]:
        project = get_project(self.db_url, project_id)
        episode = get_episode(self.db_url, project_id, episode_no)
        if not project or not episode:
            return {"error": "项目或分集不存在"}
        content, provider, model, is_fallback, error = self._generate(
            P.build_storyboard_messages(project, episode, shot_count),
            # 本地回退产出的是结构化列表，先转成与模型输出一致的表格文本再统一解析
            lambda: _storyboard_to_markdown(P.local_storyboard(project, episode, shot_count)),
            force_local,
        )
        scenes = _parse_storyboard(content, shot_count)
        if not scenes:
            scenes = P.local_storyboard(project, episode, shot_count)
        replace_scenes(self.db_url, int(episode["id"]), scenes)
        update_project(self.db_url, project_id, status="storyboarded")
        return {
            "content": content,
            "scenes": scenes,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
        }

    # ------------------------------------------------------------------ #
    def multimodal_roadmap(self) -> list[dict[str, str]]:
        return [dict(item) for item in MULTIMODAL_ROADMAP]

    def generate_keyframe(self, scene_id: int) -> None:  # pragma: no cover - 预留
        raise NotImplementedError(
            "文生图能力尚未接入：分镜表中已保存 image_prompt，"
            "后续可对接文生图模型后在此实现批量出图并回填 asset_path。"
        )

    def generate_clip(self, scene_id: int) -> None:  # pragma: no cover - 预留
        raise NotImplementedError(
            "文生视频能力尚未接入：分镜表中已保存 video_prompt 与镜头时长，"
            "后续可对接视频生成模型后输出片段并拼接为成片。"
        )


# --------------------------------------------------------------------------- #
# 解析：把模型输出还原为结构化数据
# --------------------------------------------------------------------------- #
_EPISODE_RE = re.compile(r"^#{2,4}\s*第\s*(\d+)\s*集[\s：:·-]*(.*)$")


def _storyboard_to_markdown(rows: list[dict[str, Any]]) -> str:
    """把结构化分镜列表渲染成 markdown 表格（与模型输出格式一致，便于统一解析）。"""
    header = "| 镜头号 | 景别 | 时长(秒) | 画面描述 | 台词 | 文生图提示词 | 文生视频提示词 |"
    lines = [header, "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append(
            "| {scene_no} | {shot_type} | {duration_sec} | {description} | {dialogue} | "
            "{image_prompt} | {video_prompt} |".format(**row)
        )
    return "\n".join(lines)


def _parse_outline(text: str, expected: int) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        match = _EPISODE_RE.match(line)
        if match:
            if current:
                episodes.append(current)
            current = {
                "episode_no": int(match.group(1)),
                "title": match.group(2).strip() or f"第{match.group(1)}集",
                "hook": "",
                "outline": "",
                "cliffhanger": "",
            }
            continue
        if current is None or not line.startswith(("-", "*", "1.", "2.", "3.")):
            continue
        body = line.lstrip("-*0123456789. ").strip()
        if any(key in body for key in ("钩子", "hook")):
            current["hook"] = body.split("：", 1)[-1].strip()
        elif "悬念" in body or "cliffhanger" in body.lower():
            current["cliffhanger"] = body.split("：", 1)[-1].strip()
        else:
            current["outline"] = (current["outline"] + " " + body).strip()
    if current:
        episodes.append(current)

    if not episodes:
        # 解析失败：退化为单集整体文本，保证界面仍可展示
        return [
            {
                "episode_no": 1,
                "title": "整体大纲",
                "hook": "",
                "outline": (text or "").strip()[:4000],
                "cliffhanger": "",
            }
        ]
    return episodes[: max(expected, len(episodes))]


def _parse_storyboard(text: str, expected: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().strip("|")
        if line.count("|") < 4:
            continue
        cells = [c.strip() for c in line.split("|")]
        if cells[0].startswith("镜头") or set(cells[0]) <= set("-: "):
            continue  # 跳过表头与分隔行
        try:
            scene_no = int(re.sub(r"\D", "", cells[0]) or len(rows) + 1)
        except ValueError:
            scene_no = len(rows) + 1
        duration = 3
        if len(cells) > 2:
            digits = re.sub(r"\D", "", cells[2])
            duration = int(digits) if digits else 3
        rows.append(
            {
                "scene_no": scene_no,
                "shot_type": cells[1] if len(cells) > 1 else "中景",
                "duration_sec": max(1, min(15, duration)),
                "description": cells[3] if len(cells) > 3 else "",
                "dialogue": cells[4] if len(cells) > 4 else "",
                "image_prompt": cells[5] if len(cells) > 5 else "",
                "video_prompt": cells[6] if len(cells) > 6 else "",
            }
        )
        if len(rows) >= expected * 2:
            break
    return rows[:expected]
