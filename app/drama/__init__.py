"""AI 短剧模块（扩展方向二）。

定位：从「一句话梗概」出发，自动产出**分集大纲 → 分集剧本 → 镜头级分镜**，
分镜同时携带中英文提示词，为后续接入文生图（关键帧）与文生视频（镜头片段）
以及配音、自动剪辑预留了完整的数据链路。
"""

from app.drama.prompts import (
    DEFAULT_SHOT_SECONDS,
    GENRES,
    SHOT_TYPES,
    local_outline,
    local_script,
    local_storyboard,
)
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
from app.drama.service import MULTIMODAL_ROADMAP, DramaService

__all__ = [
    "DEFAULT_SHOT_SECONDS",
    "GENRES",
    "SHOT_TYPES",
    "MULTIMODAL_ROADMAP",
    "DramaService",
    "local_outline",
    "local_script",
    "local_storyboard",
    "create_project",
    "delete_project",
    "get_episode",
    "get_project",
    "list_episodes",
    "list_projects",
    "list_scenes",
    "replace_episodes",
    "replace_scenes",
    "update_episode_script",
    "update_project",
]
