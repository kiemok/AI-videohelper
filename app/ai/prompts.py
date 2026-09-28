"""提示词构建 + 无 API Key 时的本地规则回退。

两件事：
1. 把结构化分析结果（``app.analysis.service.run_daily_analysis`` 的返回值）
   压缩成一段信息密度高、便于大模型理解的中文上下文 ``metrics_to_context``；
2. 当用户没有配置 API Key 时，用同样的上下文生成**规则化文案**，
   保证「采集 → 分析 → AI 解读 → 看板」链路在离线环境下也可完整演示。
"""

from __future__ import annotations

from typing import Any

from app.config import platform_label

SYSTEM_PROMPT = (
    "你是一名短视频内容创作顾问，服务对象是同时运营 B站 与 抖音 的创作者。"
    "你会收到结构化的数据分析结果，请用简体中文输出：语言通俗、结论先行、"
    "给出可执行的动作建议，避免空话；涉及数字时直接引用数据；"
    "不确定的地方要说明推测依据，不要编造未提供的数据。"
)


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "0%"


# --------------------------------------------------------------------------- #
# 上下文构建
# --------------------------------------------------------------------------- #
def metrics_to_context(metrics: dict[str, Any], max_videos: int = 6, max_anomalies: int = 6) -> str:
    """把分析结果渲染成结构化中文上下文。"""
    if not metrics:
        return "（暂无分析数据：请先在「数据管理」页导入数据，再执行一次分析。）"

    head = metrics.get("headline", {}) or {}
    lines: list[str] = []
    lines.append(f"分析日期：{metrics.get('stat_date')}｜口径：{metrics.get('platform') or '全平台'}")
    span = metrics.get("data_span") or {}
    if span:
        lines.append(
            f"数据范围：{span.get('start')} ~ {span.get('end')}，共 {span.get('video_count')} 个作品、"
            f"{fmt_int(span.get('snapshot_rows'))} 条指标快照"
        )
    lines.append(
        "整体概览："
        f"当日新增播放 {fmt_int(head.get('daily_views'))}（环比 {fmt_pct(head.get('daily_views_growth'))}），"
        f"累计播放 {fmt_int(head.get('total_views'))}，"
        f"当日互动 {fmt_int(head.get('daily_engagement'))}，"
        f"当日互动率 {fmt_pct(head.get('engagement_rate'))}，"
        f"平均传播健康度 {head.get('health_score')}，"
        f"涨粉 {fmt_int(head.get('follower_gain'))}，"
        f"有流量作品 {head.get('active_videos')}/{head.get('video_count')} 个"
    )

    compare = metrics.get("platform_compare") or {}
    if compare:
        lines.append("平台对比（当日）：")
        for platform, data in compare.items():
            lines.append(
                f"  - {platform_label(platform)}：新增播放 {fmt_int(data.get('daily_views'))}，"
                f"互动率 {fmt_pct(data.get('engagement_rate'))}，"
                f"健康度 {data.get('health_score')}，涨粉 {fmt_int(data.get('follower_gain'))}，"
                f"近7日新增播放 {fmt_int(data.get('week_daily_views'))}"
            )

    top_videos = (metrics.get("top_videos") or [])[:max_videos]
    if top_videos:
        lines.append("作品表现 TOP：")
        for i, video in enumerate(top_videos, 1):
            lines.append(
                f"  {i}. 《{video.get('title')}》[{platform_label(video.get('platform', ''))}/"
                f"{video.get('account')}] 当日新增播放 {fmt_int(video.get('daily_views'))}，"
                f"互动率 {fmt_pct(video.get('engagement_rate'))}，"
                f"日增长 {fmt_pct(video.get('growth_rate'))}，健康度 {video.get('health_score')}"
            )

    anomalies = (metrics.get("anomalies") or [])[:max_anomalies]
    if anomalies:
        lines.append("异常拐点：")
        for item in anomalies:
            lines.append(
                f"  - {item.get('stat_date')} 《{item.get('title')}》"
                f"[{platform_label(item.get('platform', ''))}] {item.get('note')}"
                f"（当日新增播放 {fmt_int(item.get('daily_views'))}，环比 {fmt_pct(item.get('growth_rate'))}）"
            )

    sentiment = metrics.get("sentiment") or {}
    if sentiment.get("total"):
        lines.append(
            f"评论情感：共 {fmt_int(sentiment.get('total'))} 条，"
            f"正面 {sentiment.get('positive_ratio')}%、中性 "
            f"{round(100 - float(sentiment.get('positive_ratio', 0)) - float(sentiment.get('negative_ratio', 0)), 2)}%、"
            f"负面 {sentiment.get('negative_ratio')}%，平均情感分 {sentiment.get('avg_score')}"
        )
        for item in (sentiment.get("top_positive") or [])[:2]:
            lines.append(f"  - 代表好评：{item.get('content')}（{item.get('like_count')} 赞）")
        for item in (sentiment.get("top_negative") or [])[:2]:
            lines.append(f"  - 代表差评：{item.get('content')}（{item.get('like_count')} 赞）")

    keywords = metrics.get("keywords") or []
    if keywords:
        lines.append("评论/标题热词：" + "、".join(f"{k['word']}({k['count']})" for k in keywords[:15]))

    hours = metrics.get("publish_hours") or {}
    if hours:
        best = max(hours.items(), key=lambda kv: kv[1])
        lines.append(
            "发布时段："
            + "，".join(f"{h}点 健康度{v}" for h, v in sorted(hours.items()))
            + f"（当前最佳：{best[0]}点）"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 提示词模板
# --------------------------------------------------------------------------- #
def daily_brief_messages(metrics: dict[str, Any]) -> list[dict[str, str]]:
    context = metrics_to_context(metrics)
    user = (
        "以下是今日的双平台数据分析结果：\n"
        f"{context}\n\n"
        "请输出一份**数据简报**，严格按下面结构（用 Markdown 小标题）：\n"
        "## 今日一句话结论\n"
        "## 数据解读（分平台，指出关键变化与原因推测）\n"
        "## 传播健康度诊断（哪个平台/作品健康、哪个出问题）\n"
        "## 明日行动建议（3 条，具体到选题或运营动作）\n"
        "要求：不超过 600 字，数字必须来自上面的数据。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def topic_suggestion_messages(metrics: dict[str, Any]) -> list[dict[str, str]]:
    context = metrics_to_context(metrics)
    user = (
        f"{context}\n\n"
        "请基于以上数据，给出接下来 3 天的**选题建议**：\n"
        "```\n"
        "### 选题 N：标题示例\n"
        "- 适配平台：B站/抖音（可多选）\n"
        "- 推荐理由：结合哪条数据（引用具体数字）\n"
        "- 内容要点：3 条以内\n"
        "- 预期指标：预测可达到的播放/互动率区间及依据\n"
        "```\n"
        "共 3~5 个选题，优先复用已验证的高健康度方向。"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def title_optimize_messages(metrics: dict[str, Any], titles: list[str]) -> list[dict[str, str]]:
    context = metrics_to_context(metrics)
    joined = "\n".join(f"- {t}" for t in titles) or "（未提供标题，请基于热词自行拟定）"
    user = (
        f"{context}\n\n"
        f"以下是待优化的标题：\n{joined}\n\n"
        "请针对每个标题给出 2 个优化版本（分别适配 B站 与 抖音），"
        "并说明优化点（关键词、情绪钩子、数字/悬念的用法），控制在 400 字内。"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def publish_time_messages(metrics: dict[str, Any]) -> list[dict[str, str]]:
    context = metrics_to_context(metrics)
    user = (
        f"{context}\n\n"
        "请给出**发布时间建议**：分别针对 B站 与 抖音，说明推荐的 2 个发布时段、"
        "工作日与周末的差异，以及依据（引用发布时段健康度数据与平台用户习惯），300 字内。"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def chat_messages(metrics: dict[str, Any], question: str, history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    context = metrics_to_context(metrics)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"当前可用的数据上下文如下（回答必须以此为准，不要编造）：\n{context}",
        },
    ]
    for item in (history or [])[-6:]:
        role = item.get("role")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": item.get("content", "")})
    messages.append({"role": "user", "content": question})
    return messages


# --------------------------------------------------------------------------- #
# 本地规则回退（无 API Key）
# --------------------------------------------------------------------------- #
_FALLBACK_NOTE = "> 未检测到可用的大模型 API Key，以下内容由本地规则引擎生成（配置 Key 后自动切换为大模型解读）。\n"


def local_daily_brief(metrics: dict[str, Any]) -> str:
    if not metrics:
        return _FALLBACK_NOTE + "\n暂无分析数据，请先导入数据并执行分析。"
    head = metrics.get("headline", {}) or {}
    compare = metrics.get("platform_compare", {}) or {}
    videos = metrics.get("top_videos", []) or []
    anomalies = metrics.get("anomalies", []) or []
    sentiment = metrics.get("sentiment", {}) or {}
    keywords = metrics.get("keywords", []) or []
    hours = metrics.get("publish_hours", {}) or {}

    growth = float(head.get("daily_views_growth") or 0)
    trend_word = "上行" if growth > 5 else ("回落" if growth < -5 else "平稳")
    best_platform = max(compare.items(), key=lambda kv: kv[1].get("health_score", 0))[0] if compare else ""
    worst_platform = min(compare.items(), key=lambda kv: kv[1].get("health_score", 0))[0] if compare else ""

    lines: list[str] = [_FALLBACK_NOTE]
    lines.append("## 今日一句话结论")
    lines.append(
        f"{metrics.get('stat_date')} 全网新增播放 {fmt_int(head.get('daily_views'))}，"
        f"环比 {fmt_pct(growth)}，整体走势**{trend_word}**；"
        f"平均传播健康度 {head.get('health_score')}，"
        f"最值得加码的平台是 {platform_label(best_platform) if best_platform else '—'}。"
    )

    lines.append("\n## 数据解读")
    if compare:
        for platform, data in sorted(compare.items(), key=lambda kv: kv[1].get("daily_views", 0), reverse=True):
            lines.append(
                f"- **{platform_label(platform)}**：新增播放 {fmt_int(data.get('daily_views'))}，"
                f"互动率 {fmt_pct(data.get('engagement_rate'))}，健康度 {data.get('health_score')}，"
                f"涨粉 {fmt_int(data.get('follower_gain'))}（近 7 日新增播放 {fmt_int(data.get('week_daily_views'))}）"
            )
        if worst_platform and worst_platform != best_platform:
            delta = float(compare[best_platform].get("health_score", 0)) - float(
                compare[worst_platform].get("health_score", 0)
            )
            lines.append(
                f"- 平台差距：{platform_label(best_platform)} 健康度高出 "
                f"{platform_label(worst_platform)} {delta:.1f} 分，"
                "说明两边内容适配度不同，建议对低分平台单独调整开头钩子与选题角度。"
            )
    if videos:
        top = videos[0]
        lines.append(
            f"- 头部作品《{top.get('title')}》（{platform_label(top.get('platform', ''))}）"
            f"贡献当日新增播放 {fmt_int(top.get('daily_views'))}，"
            f"互动率 {fmt_pct(top.get('engagement_rate'))}，健康度 {top.get('health_score')}。"
        )
        weak = [v for v in videos if float(v.get("health_score") or 0) < float(head.get("health_score") or 0)]
        if weak:
            lines.append(
                f"- 低于平均健康度的作品 {len(weak)} 个，例如《{weak[0].get('title')}》"
                f"（健康度 {weak[0].get('health_score')}），值得复盘封面与前 5 秒。"
            )

    lines.append("\n## 传播健康度诊断")
    if anomalies:
        for item in anomalies[:3]:
            lines.append(
                f"- {item.get('stat_date')}《{item.get('title')}》：{item.get('note')}"
            )
    else:
        lines.append("- 近 30 天未检测到显著异常拐点，数据波动处于正常区间。")
    if sentiment.get("total"):
        lines.append(
            f"- 评论情感：正面 {sentiment.get('positive_ratio')}%、负面 {sentiment.get('negative_ratio')}%，"
            f"平均分 {sentiment.get('avg_score')}，"
            + ("口碑健康。" if float(sentiment.get("avg_score") or 0) >= 0 else "建议优先处理负面反馈集中的问题。")
        )

    lines.append("\n## 明日行动建议")
    tips: list[str] = []
    if videos:
        tips.append(
            f"复用已验证选题：延续《{videos[0].get('title')}》的角度做 1 条同系列内容，"
            "保持标题结构与封面风格一致，降低试错成本。"
        )
    if keywords:
        tips.append(
            "把观众高频提到的关键词放进标题/前 3 秒：" + "、".join(k["word"] for k in keywords[:4]) + "。"
        )
    if hours:
        best_hour = max(hours.items(), key=lambda kv: kv[1])[0]
        tips.append(f"发布时间固定在 {best_hour}:00 前后（历史该时段平均健康度最高），错开整点高峰提前 10 分钟发。")
    if sentiment.get("top_negative"):
        tips.append("针对差评集中的点（如「" + str(sentiment["top_negative"][0]["content"])[:20] + "」）在下条视频中正面回应。")
    if not tips:
        tips.append("积累更多数据后（建议至少 7 天）再依赖趋势结论做决策。")
    lines.extend(f"{i}. {tip}" for i, tip in enumerate(tips, 1))
    return "\n".join(lines)


def local_topic_suggestions(metrics: dict[str, Any]) -> str:
    keywords = (metrics.get("keywords") or [])[:6]
    videos = (metrics.get("top_videos") or [])[:3]
    lines = [_FALLBACK_NOTE, "### 本地规则生成的选题方向"]
    if videos:
        lines.append(f"1. **系列化复用**：《{videos[0].get('title')}》表现最好，建议出「续集/进阶版」，沿用同一封面模板。")
        lines.append(f"2. **横向拓展**：把《{videos[0].get('title')}》里的单品测评扩展为同价位横评，接住已有流量人群。")
    if keywords:
        lines.append(
            "3. **评论区选题**：观众高频提到 "
            + "、".join(f"{k['word']}" for k in keywords[:4])
            + "，可做一期集中解答。"
        )
    if not videos and not keywords:
        lines.append("暂无足够数据，请先导入数据并执行分析。")
    return "\n".join(lines)


def local_publish_time(metrics: dict[str, Any]) -> str:
    hours = metrics.get("publish_hours") or {}
    if not hours:
        return _FALLBACK_NOTE + "\n暂无发布时段样本，建议先积累 7 天以上数据。"
    ranked = sorted(hours.items(), key=lambda kv: kv[1], reverse=True)[:3]
    lines = [_FALLBACK_NOTE, "### 本地规则生成的发布时段建议"]
    for i, (hour, score) in enumerate(ranked, 1):
        lines.append(f"{i}. {hour}:00 前后发布（历史平均健康度 {score}）")
    lines.append("- 周末可整体后移 1 小时；避开同一账号两条作品间隔小于 6 小时。")
    return "\n".join(lines)


def local_answer(metrics: dict[str, Any], question: str) -> str:
    """无 Key 时的问答回退：按问题意图匹配已有指标。"""
    if not metrics:
        return _FALLBACK_NOTE + "\n暂无分析数据，请先导入数据并执行分析。"

    head = metrics.get("headline", {}) or {}
    compare = metrics.get("platform_compare", {}) or {}
    videos = metrics.get("top_videos", []) or []
    sentiment = metrics.get("sentiment", {}) or {}
    keywords = metrics.get("keywords", []) or []
    hours = metrics.get("publish_hours", {}) or {}
    question = (question or "").strip()

    matched = [platform for platform in compare if platform_label(platform) in question]
    lines = [_FALLBACK_NOTE]

    def platform_block(key: str) -> str:
        data = compare[key]
        return (
            f"- {platform_label(key)}：新增播放 {fmt_int(data.get('daily_views'))}、"
            f"互动率 {fmt_pct(data.get('engagement_rate'))}、健康度 {data.get('health_score')}、"
            f"涨粉 {fmt_int(data.get('follower_gain'))}"
        )

    if any(word in question for word in ("健康度", "传播", "诊断")):
        lines.append(f"当前平均传播健康度 {head.get('health_score')}（满分 100）。各平台：")
        lines.extend(platform_block(k) for k in compare)
        lines.append("健康度由互动率、收藏率、分享率、增长率加权得到，低于 60 说明内容「有人看但不愿互动」，优先改开头。")
    elif any(word in question for word in ("互动", "点赞", "评论", "收藏")):
        lines.append(
            f"当日互动总量 {fmt_int(head.get('daily_engagement'))}，互动率 {fmt_pct(head.get('engagement_rate'))}。"
        )
        lines.extend(platform_block(k) for k in compare)
        lines.append(f"评论情感平均分 {sentiment.get('avg_score')}，正面占比 {sentiment.get('positive_ratio')}%。")
    elif any(word in question for word in ("选题", "做什么", "拍什么")):
        lines.append(local_topic_suggestions(metrics).replace(_FALLBACK_NOTE, "").strip())
    elif any(word in question for word in ("标题", "封面")):
        lines.append("标题优化建议：")
        lines.append("1. 把数据里表现最好的关键词放进标题前 10 个字。")
        lines.append("2. 标题长度建议 B站 18~24 字、抖音 12~18 字，并保留一个数字或结果承诺。")
        lines.append(f"3. 当前热词：{'、'.join(k['word'] for k in keywords[:5]) or '暂无'}")
    elif any(word in question for word in ("时间", "几点", "发布")):
        lines.append(local_publish_time(metrics).replace(_FALLBACK_NOTE, "").strip())
    elif any(word in question for word in ("播放", "流量", "涨粉", "数据", "表现")):
        lines.append(
            f"当日新增播放 {fmt_int(head.get('daily_views'))}，环比 {fmt_pct(head.get('daily_views_growth'))}；"
            f"累计播放 {fmt_int(head.get('total_views'))}，涨粉 {fmt_int(head.get('follower_gain'))}。"
        )
        lines.extend(platform_block(k) for k in compare)
        if videos:
            lines.append(f"表现最好：《{videos[0].get('title')}》新增播放 {fmt_int(videos[0].get('daily_views'))}。")
    else:
        lines.append(
            "本地规则引擎只能回答数据类问题（播放/互动率/健康度/评论情感/选题/标题/发布时间）。"
            "问题概览如下："
        )
        lines.append(
            f"- {metrics.get('stat_date')} 新增播放 {fmt_int(head.get('daily_views'))}"
            f"（环比 {fmt_pct(head.get('daily_views_growth'))}），健康度 {head.get('health_score')}，"
            f"互动率 {fmt_pct(head.get('engagement_rate'))}"
        )
    if matched:
        lines.insert(1, "（已按你提到的平台聚焦）")
    if hours:
        best_hour = max(hours.items(), key=lambda kv: kv[1])[0]
        lines.append(f"补充：历史最佳发布时段为 {best_hour}:00 前后。")
    return "\n".join(lines)
