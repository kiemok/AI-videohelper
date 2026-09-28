"""AI 短剧模块的数据访问层：项目 / 分集 / 分镜。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from app.db.base import session_scope
from app.db.models import DramaEpisode, DramaProject, DramaScene, now


# --------------------------------------------------------------------------- #
# 项目
# --------------------------------------------------------------------------- #
def create_project(
    db_url: str,
    title: str,
    genre: str,
    target_platform: str = "douyin",
    aspect_ratio: str = "9:16",
    logline: str = "",
    style: str = "",
) -> int:
    with session_scope(db_url) as s:
        row = DramaProject(
            title=title[:120] or "未命名短剧",
            genre=genre,
            target_platform=target_platform,
            aspect_ratio=aspect_ratio,
            logline=logline,
            style=style,
        )
        s.add(row)
        s.flush()
        return row.id


def list_projects(db_url: str) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        rows = s.scalars(select(DramaProject).order_by(DramaProject.updated_at.desc())).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "genre": r.genre,
                "target_platform": r.target_platform,
                "aspect_ratio": r.aspect_ratio,
                "logline": r.logline,
                "style": r.style,
                "episode_count": r.episode_count,
                "status": r.status,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]


def get_project(db_url: str, project_id: int) -> dict[str, Any] | None:
    with session_scope(db_url) as s:
        row = s.get(DramaProject, project_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "title": row.title,
            "genre": row.genre,
            "target_platform": row.target_platform,
            "aspect_ratio": row.aspect_ratio,
            "logline": row.logline,
            "style": row.style,
            "episode_count": row.episode_count,
            "status": row.status,
            "updated_at": row.updated_at,
        }


def update_project(
    db_url: str,
    project_id: int,
    *,
    episode_count: int | None = None,
    status: str | None = None,
    logline: str | None = None,
) -> None:
    with session_scope(db_url) as s:
        row = s.get(DramaProject, project_id)
        if row is None:
            return
        if episode_count is not None:
            row.episode_count = episode_count
        if status is not None:
            row.status = status
        if logline is not None:
            row.logline = logline
        row.updated_at = now()


def delete_project(db_url: str, project_id: int) -> None:
    with session_scope(db_url) as s:
        row = s.get(DramaProject, project_id)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# 分集
# --------------------------------------------------------------------------- #
def replace_episodes(db_url: str, project_id: int, episodes: list[dict[str, Any]]) -> None:
    """用新大纲覆盖该项目的分集（保留已有剧本的集数内容）。"""
    with session_scope(db_url) as s:
        existing = {
            e.episode_no: e
            for e in s.scalars(select(DramaEpisode).where(DramaEpisode.project_id == project_id)).all()
        }
        for item in episodes:
            number = int(item.get("episode_no") or 0)
            if number <= 0:
                continue
            row = existing.pop(number, None)
            if row is None:
                row = DramaEpisode(project_id=project_id, episode_no=number)
                s.add(row)
            row.title = str(item.get("title") or "")[:120]
            row.hook = str(item.get("hook") or "")
            row.outline = str(item.get("outline") or "")
            row.cliffhanger = str(item.get("cliffhanger") or "")
            row.updated_at = now()
        for stale in existing.values():
            s.delete(stale)


def list_episodes(db_url: str, project_id: int) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        rows = s.scalars(
            select(DramaEpisode)
            .where(DramaEpisode.project_id == project_id)
            .order_by(DramaEpisode.episode_no)
        ).all()
        return [
            {
                "id": r.id,
                "project_id": r.project_id,
                "episode_no": r.episode_no,
                "title": r.title,
                "hook": r.hook,
                "outline": r.outline,
                "script": r.script,
                "cliffhanger": r.cliffhanger,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]


def get_episode(db_url: str, project_id: int, episode_no: int) -> dict[str, Any] | None:
    for item in list_episodes(db_url, project_id):
        if item["episode_no"] == episode_no:
            return item
    return None


def update_episode_script(
    db_url: str, episode_id: int, script: str, hook: str | None = None, cliffhanger: str | None = None
) -> None:
    with session_scope(db_url) as s:
        row = s.get(DramaEpisode, episode_id)
        if row is None:
            return
        row.script = script
        if hook is not None:
            row.hook = hook
        if cliffhanger is not None:
            row.cliffhanger = cliffhanger
        row.updated_at = now()


# --------------------------------------------------------------------------- #
# 分镜
# --------------------------------------------------------------------------- #
def replace_scenes(db_url: str, episode_id: int, scenes: list[dict[str, Any]]) -> None:
    with session_scope(db_url) as s:
        s.execute(delete(DramaScene).where(DramaScene.episode_id == episode_id))
        for index, item in enumerate(scenes, 1):
            s.add(
                DramaScene(
                    episode_id=episode_id,
                    scene_no=int(item.get("scene_no") or index),
                    shot_type=str(item.get("shot_type") or "中景"),
                    duration_sec=int(item.get("duration_sec") or 3),
                    description=str(item.get("description") or ""),
                    dialogue=str(item.get("dialogue") or ""),
                    image_prompt=str(item.get("image_prompt") or ""),
                    video_prompt=str(item.get("video_prompt") or ""),
                )
            )


def list_scenes(db_url: str, episode_id: int) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        rows = s.scalars(
            select(DramaScene).where(DramaScene.episode_id == episode_id).order_by(DramaScene.scene_no)
        ).all()
        return [
            {
                "id": r.id,
                "scene_no": r.scene_no,
                "shot_type": r.shot_type,
                "duration_sec": r.duration_sec,
                "description": r.description,
                "dialogue": r.dialogue,
                "image_prompt": r.image_prompt,
                "video_prompt": r.video_prompt,
                "asset_path": r.asset_path,
            }
            for r in rows
        ]


def update_scene_asset(db_url: str, scene_id: int, asset_path: str) -> None:
    with session_scope(db_url) as s:
        row = s.get(DramaScene, scene_id)
        if row is not None:
            row.asset_path = asset_path[:255]
