"""自定义技能单测：YAML 头部解析、slug 生成、保存/加载/删除与提示词拼接。"""

from __future__ import annotations

from app.skills import (
    Skill,
    build_skill_prompt,
    delete_skill,
    ensure_builtin_skills,
    load_skills,
    parse_front_matter,
    parse_skill_text,
    save_skill,
    slugify,
)

SAMPLE = """---
name: 抖音三秒钩子专家
description: 为抖音短视频设计前 3 秒钩子
scenario: 需要提升完播率时启用
tags: [抖音, 钩子, 完播率]
---

你是钩子专家。请遵守：
1. 前 3 秒给出冲突或结果
"""


# ---------------------------------------------------------------------- #
# 解析
# ---------------------------------------------------------------------- #
def test_parse_front_matter_splits_meta_and_body():
    meta, body = parse_front_matter(SAMPLE)
    assert meta["name"] == "抖音三秒钩子专家"
    assert meta["tags"] == ["抖音", "钩子", "完播率"]
    assert body.strip().startswith("你是钩子专家")


def test_parse_front_matter_without_header_returns_body_only():
    meta, body = parse_front_matter("只有正文，没有 YAML 头部")
    assert meta == {}
    assert body.strip() == "只有正文，没有 YAML 头部"


def test_parse_skill_text_builds_skill():
    skill = parse_skill_text("douyin-hook", SAMPLE)
    assert isinstance(skill, Skill)
    assert skill.slug == "douyin-hook"
    assert skill.name == "抖音三秒钩子专家"
    assert skill.tags == ["抖音", "钩子", "完播率"]
    assert "钩子专家" in skill.prompt


def test_parse_skill_text_falls_back_to_slug_as_name():
    skill = parse_skill_text("only-body", "正文内容")
    assert skill.name == "only-body"
    assert skill.prompt.strip() == "正文内容"


def test_slugify_produces_safe_slug():
    for text in ("抖音三秒钩子专家", "Hello World!", "数据分析师（严格引用数据）"):
        slug = slugify(text)
        assert slug, f"不应为空：{text}"
        assert not set(slug) & set('\\/:*?"<>| '), f"slug 含非法字符：{slug}"


# ---------------------------------------------------------------------- #
# 保存 / 加载 / 删除
# ---------------------------------------------------------------------- #
def test_save_load_delete_roundtrip(tmp_path):
    skill = Skill(slug="demo-skill", name="演示技能", description="用于测试", prompt="你是演示助手。")
    path = save_skill(skill, tmp_path)
    assert path.is_file()

    loaded = {item.slug: item for item in load_skills(tmp_path)}
    assert "demo-skill" in loaded
    assert loaded["demo-skill"].name == "演示技能"
    assert loaded["demo-skill"].prompt.strip() == "你是演示助手。"

    assert delete_skill(loaded["demo-skill"]) is True
    assert "demo-skill" not in {item.slug for item in load_skills(tmp_path)}


def test_ensure_builtin_skills_writes_once(tmp_path):
    written = ensure_builtin_skills(tmp_path)
    assert written, "首次应写入内置示例技能"
    assert len(load_skills(tmp_path)) == len(written)
    assert ensure_builtin_skills(tmp_path) == [], "重复调用不应覆盖已有文件"


def test_load_skills_ignores_broken_files(tmp_path):
    (tmp_path / "broken.md").write_text("没有头部也没有正文", encoding="utf-8")
    (tmp_path / "ok.md").write_text(SAMPLE, encoding="utf-8")
    slugs = {item.slug for item in load_skills(tmp_path)}
    assert "ok" in slugs


# ---------------------------------------------------------------------- #
# 提示词拼接
# ---------------------------------------------------------------------- #
def test_build_skill_prompt_empty_returns_blank():
    assert build_skill_prompt([]) == ""


def test_build_skill_prompt_joins_enabled_skills():
    skills = [
        Skill(slug="a", name="技能A", prompt="A 的提示词"),
        Skill(slug="b", name="技能B", prompt="B 的提示词"),
    ]
    text = build_skill_prompt(skills)
    assert "技能A" in text and "A 的提示词" in text
    assert "技能B" in text and "B 的提示词" in text


def test_build_skill_prompt_truncates_long_content():
    big = Skill(slug="big", name="长技能", prompt="x" * 9000)
    text = build_skill_prompt([big], limit_chars=500)
    assert len(text) <= 1000, "超长技能内容应被截断，避免挤占上下文"
