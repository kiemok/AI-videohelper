"""评论情感倾向分析（本地词典法，无需联网）。

方法：构建中文情感词表（正向/负向 + 强度），配合否定词与程度副词做修饰，
采用**最长匹配 + 已匹配区间占用**避免重复计数；原始得分经压缩映射到 [-1, 1]。
阈值 ±0.15 划分正面 / 中性 / 负面。

选择词典法的原因：完全离线、可解释、零额外依赖，适合桌面端每日批处理；
后续可平滑替换为模型（如 SnowNLP / 大模型打标），只需保持本模块的函数契约。
"""

from __future__ import annotations

import json
import math
from typing import Any, Iterable

import pandas as pd

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

#: 正向词 → 强度（1.0 为普通，>1 为强情感）
POSITIVE_TERMS: dict[str, float] = {
    "好": 1.0, "很好": 1.3, "不错": 1.1, "厉害": 1.2, "清晰": 1.1, "有用": 1.2,
    "实用": 1.1, "干货": 1.3, "收藏": 1.1, "感谢": 1.2, "谢谢": 1.1, "学到了": 1.3,
    "太棒": 1.4, "喜欢": 1.2, "支持": 1.1, "推荐": 1.2, "性价比": 1.1, "惊艳": 1.4,
    "舒服": 1.1, "满意": 1.2, "涨知识": 1.3, "及时": 1.1, "专业": 1.2, "详细": 1.1,
    "用心": 1.2, "到位": 1.2, "靠谱": 1.2, "值": 0.9, "香": 1.1, "简洁": 1.1,
    "直观": 1.1, "客观": 1.1, "救命": 1.2, "牛": 1.2, "绝了": 1.3, "真香": 1.3,
    "学会了": 1.3, "有帮助": 1.3, "好懂": 1.2, "讲得好": 1.3, "实用性强": 1.3,
}

NEGATIVE_TERMS: dict[str, float] = {
    "差": 1.1, "烂": 1.3, "失望": 1.4, "广告": 1.2, "太水": 1.3, "难看": 1.2,
    "不行": 1.2, "骗": 1.4, "太贵": 1.2, "假": 1.3, "吵": 1.1, "卡顿": 1.2,
    "垃圾": 1.4, "无语": 1.3, "浪费时间": 1.4, "误导": 1.4, "糊": 1.1, "无聊": 1.2,
    "翻车": 1.3, "退钱": 1.4, "抄": 1.2, "恰饭": 1.1, "劝退": 1.3, "虚标": 1.3,
    "掉帧": 1.2, "发热": 1.0, "拔草": 1.2, "避雷": 1.3, "一般": 0.9, "没重点": 1.2,
    "听不懂": 1.1, "听不下去": 1.2, "不如": 1.0, "武断": 1.1, "标题党": 1.3,
}

_DEGREE: dict[str, float] = {
    "非常": 1.5, "特别": 1.4, "超级": 1.5, "太": 1.4, "很": 1.3, "挺": 1.2,
    "真的": 1.3, "巨": 1.4, "极其": 1.6, "有点": 0.7, "稍微": 0.6, "略": 0.6, "还算": 0.8,
}
_NEGATION: tuple[str, ...] = ("不", "没", "无", "别", "非", "未", "毫无", "并不")

POSITIVE_THRESHOLD = 0.15
NEGATIVE_THRESHOLD = -0.15

# 最长匹配优先
_TERMS: tuple[tuple[str, float], ...] = tuple(
    sorted(
        [(w, s) for w, s in POSITIVE_TERMS.items()] + [(w, -s) for w, s in NEGATIVE_TERMS.items()],
        key=lambda item: len(item[0]),
        reverse=True,
    )
)
_MAX_TERM_LEN = max(len(w) for w, _ in _TERMS)


def label_of(score: float) -> str:
    if score >= POSITIVE_THRESHOLD:
        return "positive"
    if score <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def analyze_text(text: str) -> tuple[float, str]:
    """返回 (情感得分[-1,1], 标签)。"""
    text = (text or "").strip()
    if not text:
        return 0.0, "neutral"

    used = [False] * len(text)
    total = 0.0
    for term, polarity in _TERMS:
        start = 0
        while True:
            idx = text.find(term, start)
            if idx < 0:
                break
            end = idx + len(term)
            if any(used[idx:end]):
                start = idx + 1
                continue
            prefix = text[max(0, idx - 3) : idx]
            factor = 1.0
            for degree, multiplier in _DEGREE.items():
                if prefix.endswith(degree):
                    factor = multiplier
                    break
            if any(prefix.endswith(neg) for neg in _NEGATION):
                factor *= -1.0
            total += polarity * factor
            for pos in range(idx, end):
                used[pos] = True
            start = end

    score = math.tanh(total / 2.2)  # 压缩到 (-1, 1)，避免长评语分数溢出
    score = round(max(-1.0, min(1.0, score)), 3)
    return score, label_of(score)


def score_comments(comments: Iterable[dict[str, Any]]) -> list[tuple[int, float, str]]:
    """批量打分，返回 [(comment_id, score, label), ...]。"""
    out: list[tuple[int, float, str]] = []
    for item in comments:
        score, label = analyze_text(item.get("content", ""))
        out.append((int(item["id"]), score, label))
    return out


# ---------------------------------------------------------------------- #
# 大模型打标（可选）：与词典法保持完全相同的返回契约，便于随时切换 / 回退
# ---------------------------------------------------------------------- #
#: 每次请求交给模型的评论条数
LLM_BATCH_SIZE = 25
#: 单次分析最多交给模型打标的评论条数（超出部分自动用词典法补齐，控制耗时与成本）
LLM_MAX_COMMENTS = 600

_LLM_SYSTEM = "你是中文评论情感分析器，只输出 JSON 数组，不要输出任何解释或多余文字。"

_LLM_TEMPLATE = """请判断下面每条评论的情感极性，逐条输出结果。

评分口径：
- score：-1~1 的小数（-1 极负面 / 0 中性 / 1 极正面）
- label：positive（score ≥ 0.15）/ neutral（-0.15 < score < 0.15）/ negative（score ≤ -0.15）
- 反讽、玩梗、网络用语（"恰饭""标题党""真香"）按真实态度判断，不要只看字面

输入评论（JSON 数组，字段 id 与 text）：
{payload}

只输出与输入等长、同顺序的 JSON 数组，例如：
[{{"id": 1, "score": 0.6, "label": "positive"}}, {{"id": 2, "score": -0.4, "label": "negative"}}]"""


def build_llm_messages(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    """构造一批评论的打标请求消息。"""
    payload = json.dumps(
        [{"id": int(item["id"]), "text": str(item.get("content") or "")[:160]} for item in batch],
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": _LLM_SYSTEM},
        {"role": "user", "content": _LLM_TEMPLATE.format(payload=payload)},
    ]


def parse_llm_scores(raw: str) -> dict[int, tuple[float, str]]:
    """解析模型返回的 JSON（容忍 ```json 包裹与前后说明文字），非法条目直接丢弃。"""
    text = (raw or "").strip()
    if "[" in text and "]" in text:
        text = text[text.find("[") : text.rfind("]") + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}

    out: dict[int, tuple[float, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            comment_id = int(item.get("id"))
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        score = round(max(-1.0, min(1.0, score)), 3)
        label = str(item.get("label") or "").strip().lower()
        if label not in ("positive", "neutral", "negative"):
            label = label_of(score)
        out[comment_id] = (score, label)
    return out


def score_comments_with_llm(
    comments: list[dict[str, Any]],
    client: Any,
    batch_size: int = LLM_BATCH_SIZE,
    max_comments: int = LLM_MAX_COMMENTS,
) -> tuple[list[tuple[int, float, str]], int, list[str]]:
    """用大模型批量打标。

    返回 ``(结果, 模型实际命中条数, 错误信息列表)``；模型漏答、答错或整批失败的条目
    会自动用词典法补齐，因此返回结果**一定覆盖全部输入**，调用方无需再处理缺失。
    """
    target = comments[:max_comments] if max_comments > 0 else list(comments)
    hits: dict[int, tuple[float, str]] = {}
    errors: list[str] = []

    for start in range(0, len(target), batch_size):
        batch = target[start : start + batch_size]
        try:
            reply = client.chat(build_llm_messages(batch))
            hits.update(parse_llm_scores(reply.content))
        except Exception as exc:  # noqa: BLE001 - 任何异常都不应中断整次分析，退化为词典法
            logger.warning("大模型情感打标失败（第 %d 批）：%s", start // batch_size + 1, exc)
            errors.append(str(exc))

    out: list[tuple[int, float, str]] = []
    llm_hits = 0
    for item in comments:
        comment_id = int(item["id"])
        hit = hits.get(comment_id)
        if hit is None:
            score, label = analyze_text(item.get("content", ""))
            out.append((comment_id, score, label))
        else:
            llm_hits += 1
            out.append((comment_id, hit[0], hit[1]))
    return out, llm_hits, errors


def aggregate(comments: list[dict[str, Any]], top_n: int = 5) -> dict[str, Any]:
    """汇总情感分布 + 代表性正/负评论。"""
    if not comments:
        return {
            "total": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "avg_score": 0.0,
            "by_platform": {},
            "top_positive": [],
            "top_negative": [],
        }

    frame = pd.DataFrame(
        [
            {
                "id": c["id"],
                "platform": c.get("platform", ""),
                "content": c.get("content", ""),
                "like_count": int(c.get("like_count") or 0),
                "score": float(c.get("sentiment_score") or 0.0),
                "label": c.get("sentiment_label") or label_of(float(c.get("sentiment_score") or 0.0)),
            }
            for c in comments
        ]
    )
    counts = frame["label"].value_counts().to_dict()
    total = int(len(frame))

    def brief(row: Any) -> dict[str, Any]:
        return {
            "content": str(row["content"])[:80],
            "score": round(float(row["score"]), 3),
            "like_count": int(row["like_count"]),
            "platform": row["platform"],
        }

    top_positive = [
        brief(row)
        for _, row in frame.sort_values(["score", "like_count"], ascending=False)
        .head(top_n)
        .iterrows()
        if row["score"] > 0
    ]
    top_negative = [
        brief(row)
        for _, row in frame.sort_values(["score", "like_count"], ascending=True)
        .head(top_n)
        .iterrows()
        if row["score"] < 0
    ]

    by_platform: dict[str, dict[str, Any]] = {}
    for platform, part in frame.groupby("platform"):
        part_total = int(len(part))
        platform_counts = part["label"].value_counts().to_dict()
        by_platform[str(platform)] = {
            "total": part_total,
            "positive": int(platform_counts.get("positive", 0)),
            "neutral": int(platform_counts.get("neutral", 0)),
            "negative": int(platform_counts.get("negative", 0)),
            "avg_score": round(float(part["score"].mean()), 3),
        }

    return {
        "total": total,
        "positive": int(counts.get("positive", 0)),
        "neutral": int(counts.get("neutral", 0)),
        "negative": int(counts.get("negative", 0)),
        "positive_ratio": round(counts.get("positive", 0) / total * 100, 2),
        "negative_ratio": round(counts.get("negative", 0) / total * 100, 2),
        "avg_score": round(float(frame["score"].mean()), 3),
        "by_platform": by_platform,
        "top_positive": top_positive,
        "top_negative": top_negative,
    }
