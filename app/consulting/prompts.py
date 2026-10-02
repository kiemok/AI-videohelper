"""视频创作咨询提示词与本地回退。

咨询与「数据解读」的区别：数据解读回答"数据怎么样"，咨询回答"我接下来怎么做"。
因此提示词里除数据上下文外，还会加入咨询分类方法论与创作者画像占位。
"""

from __future__ import annotations

from typing import Any

from app.ai.prompts import fmt_int, fmt_pct, metrics_to_context
from app.prompts_store import prompt_text

#: 咨询分类（界面下拉/分段控件使用）
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("综合咨询", "general"),
    ("账号定位", "positioning"),
    ("脚本结构", "script"),
    ("标题封面", "title_cover"),
    ("增长策略", "growth"),
    ("商业化", "monetization"),
)

CATEGORY_LABELS: dict[str, str] = {key: label for label, key in CATEGORIES}

#: 每类咨询的方法论要点（写给模型的"专家框架"，也是本地回退的骨架）
METHODOLOGY: dict[str, tuple[str, ...]] = {
    "general": (
        "先给结论，再给依据（引用数据）",
        "建议必须可执行：说明做什么、何时做、预期指标",
        "识别当前最大瓶颈（流量 / 互动 / 转化）",
    ),
    "positioning": (
        "人群 × 场景 × 差异点 三要素定位",
        "对照双平台数据判断哪一端更认同当前定位",
        "给出可迁移到另一平台的表述方式",
    ),
    "script": (
        "前 3 秒钩子 → 冲突 → 证据 → 结论 → 行动号召",
        "控节奏：口播信息密度与时长匹配",
        "埋互动点：提问、选择、投票式结尾",
    ),
    "title_cover": (
        "标题 = 关键词 + 结果承诺 + 悬念/数字",
        "封面与标题互补，不重复信息",
        "分平台适配长度与语气",
    ),
    "growth": (
        "稳定更新节奏 + 系列化复用已被验证的选题",
        "给长尾内容二次分发窗口",
        "关注收藏率与完播率，而非单看播放",
    ),
    "monetization": (
        "先建立信任品类，再承接商单",
        "内容与带货品类一致性检查",
        "用互动率与评论意图判断转化潜力",
    ),
}

def _system_prompt() -> str:
    """系统提示词：优先取用户模板 ``prompts/consulting.system.md``。"""
    return prompt_text("consulting.system")


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)


def build_advice_messages(
    question: str,
    category: str,
    metrics: dict[str, Any],
    profile: str = "",
    material: str = "",
) -> list[dict[str, str]]:
    """咨询提示词：数据上下文 + 检索素材（RAG）+ 方法论 + 创作者补充信息。"""
    context = metrics_to_context(metrics)
    methods = METHODOLOGY.get(category, METHODOLOGY["general"])
    method_text = "\n".join(f"- {m}" for m in methods)
    profile_text = f"\n创作者补充信息：{profile}" if profile.strip() else ""
    material_text = f"\n{material}\n" if material.strip() else ""
    user = (
        f"【当前数据上下文】\n{context}{profile_text}\n"
        f"{material_text}\n"
        f"【本次咨询类型】{category_label(category)}\n"
        f"【专家方法论】\n{method_text}\n\n"
        f"【创作者的问题】{question}\n\n"
        "请输出：\n"
        "## 直接结论（1~2 句）\n"
        "## 依据（引用数据或上方素材，2~3 条）\n"
        "## 执行方案（3 条，含做什么/怎么做/预期指标）\n"
        "## 风险提示（1 条）"
    )
    return [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": user}]


def local_advice(
    question: str, category: str, metrics: dict[str, Any], profile: str = ""
) -> tuple[str, list[str]]:
    """无 API Key 时的本地规则建议，返回 (正文, 要点列表)。"""
    head = (metrics or {}).get("headline", {}) or {}
    compare = (metrics or {}).get("platform_compare", {}) or {}
    videos = (metrics or {}).get("top_videos", []) or []
    keywords = (metrics or {}).get("keywords", []) or []
    sentiment = (metrics or {}).get("sentiment", {}) or {}
    hours = (metrics or {}).get("publish_hours", {}) or {}

    best_platform = max(compare.items(), key=lambda kv: kv[1].get("health_score", 0))[0] if compare else ""
    weak_platform = min(compare.items(), key=lambda kv: kv[1].get("health_score", 0))[0] if compare else ""

    lines: list[str] = [
        "> 未配置大模型 API Key，以下为本地规则引擎基于当前数据生成的咨询建议"
        "（配置 Key 后自动切换为大模型咨询）。",
        "",
        "## 直接结论",
    ]
    if best_platform:
        lines.append(
            f"当前 {category_label(category)} 的核心动作：把资源集中在 "
            f"**{best_platform}**（健康度 {compare[best_platform].get('health_score')}），"
            f"同时用已跑通的选题结构去补 **{weak_platform}** 的短板。"
        )
    else:
        lines.append("当前数据不足，建议先积累 7 天以上双平台数据再做定位判断。")

    lines.append("")
    lines.append("## 依据")
    if head:
        lines.append(
            f"- 全平台当日新增播放 {fmt_int(head.get('daily_views'))}，"
            f"互动率 {fmt_pct(head.get('engagement_rate'))}，"
            f"传播健康度 {head.get('health_score')}，涨粉 {fmt_int(head.get('follower_gain'))}。"
        )
    for platform, data in compare.items():
        lines.append(
            f"- {platform}：互动率 {fmt_pct(data.get('engagement_rate'))}、"
            f"健康度 {data.get('health_score')}、近 7 日新增播放 {fmt_int(data.get('week_daily_views'))}。"
        )
    if videos:
        lines.append(
            f"- 表现最好：《{videos[0].get('title')}》，当日新增播放 "
            f"{fmt_int(videos[0].get('daily_views'))}，健康度 {videos[0].get('health_score')}。"
        )

    highlights: list[str] = []
    lines.append("")
    lines.append("## 执行方案")

    if category == "positioning":
        highlights = [
            "明确「人群 × 场景 × 差异点」，在主页简介与封面统一表达",
            "对照双平台互动率差异，保留高分平台的主定位，低分平台换表述",
            "连续 4 条内容验证定位一致性，观察收藏率是否上升",
        ]
    elif category == "script":
        highlights = [
            "前 3 秒直接抛结果或冲突，去掉铺垫",
            "中段每 8~10 秒一个信息点，配字幕与画面切换",
            "结尾设置提问式互动点，提升评论率",
        ]
    elif category == "title_cover":
        hot = "、".join(k["word"] for k in keywords[:3]) or "核心关键词"
        highlights = [
            f"标题前置关键词：{hot}",
            "标题与封面互补：标题给结论，封面给冲突画面",
            "B站点明信息量，抖音压缩到 12~18 字并加情绪词",
        ]
    elif category == "growth":
        highlights = [
            "复用已验证选题做系列化，降低单条试错成本",
            "固定发布节奏，错开整点提前 10 分钟发布",
            "对长尾表现好的旧作做二次剪辑再分发",
        ]
    elif category == "monetization":
        highlights = [
            "优先在互动率高的品类建立信任，再接商单",
            "检查内容题材与带货品类一致性",
            "用评论区高频问题判断真实需求点",
        ]
    else:
        highlights = [
            "聚焦已被验证的选题方向做系列化复用",
            "针对低健康度平台单独调整开头钩子",
            "保持更新节奏，避免连续两条同质内容",
        ]

    for index, item in enumerate(highlights, 1):
        lines.append(f"{index}. {item}")

    lines.append("")
    lines.append("## 风险提示")
    if sentiment and float(sentiment.get("negative_ratio") or 0) > 10:
        lines.append(
            f"- 负面评论占比 {sentiment.get('negative_ratio')}%，先解决口碑问题再加量，"
            "否则放量会放大争议。"
        )
    elif hours:
        best_hour = max(hours.items(), key=lambda kv: kv[1])[0]
        lines.append(f"- 不要在非高峰时段（如 {best_hour}:00 之外）大量投放，避免消耗内容新鲜度。")
    else:
        lines.append("- 样本量偏小，结论存在偶然性，建议连续观察一周再调整策略。")

    if profile.strip():
        lines.append("")
        lines.append(f"（已参考你补充的信息：{profile.strip()[:60]}）")
    return "\n".join(lines), highlights
