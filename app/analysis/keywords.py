"""中文关键词/热词提取（不依赖分词库的词云数据源）。

两级策略：
1. **领域词表匹配**：先按最长匹配扫描领域词（"性价比""剪辑软件"等），
   命中即计数并占用区间，这类词完整、可读，优先级最高；
2. **n-gram 补充**：对未被占用的文本片段做 2~4 字统计，用停用词过滤，
   再做包含关系与字符二元组重叠过滤，抑制"看完直接/完直接下"这类滑动碎片。

输出 ``[{"word": 词, "count": 次数}]``，直接供词云/热词榜使用。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

#: 领域词表（长度 >= 2，避免单字误匹配）；可按业务持续补充
DOMAIN_TERMS: tuple[str, ...] = (
    # 内容质量与观看感受
    "讲得太清楚", "太清楚", "清楚", "好懂", "通俗", "专业", "用心", "细节", "节奏",
    "封面", "标题党", "开头", "剪辑软件", "剪辑", "背景音乐", "灯光", "收音", "字幕",
    "生活方式", "干货满满", "确实香", "太及时",
    # 互动行为
    "已收藏", "收藏", "关注", "点赞", "三连", "催更", "更新", "期待下期", "学到了",
    "涨知识", "学会了", "有帮助", "支持", "推荐", "谢谢", "感谢", "喜欢",
    # 评价与结论
    "干货", "实测", "测评", "避坑", "劝退", "拔草", "避雷", "翻车", "误导", "武断",
    "广告", "恰饭", "结论", "参数", "性价比", "价格", "虚高", "降噪", "续航",
    # 数码物品
    "笔记本", "显示器", "充电宝", "耳机", "键盘", "平板", "显卡", "手机", "相机",
    "主机", "配件", "外设",
    # 特性与问题
    "画质", "音质", "卡顿", "发热", "散热", "手感", "做工", "屏幕", "性能", "效率",
    "技巧", "方法", "原理", "教程", "流程", "清单",
)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "这个", "那个", "什么", "怎么", "可以", "就是", "没有", "不是", "还是", "真的",
        "感觉", "觉得", "已经", "自己", "我们", "你们", "他们", "东西", "时候", "现在",
        "因为", "所以", "但是", "如果", "而且", "还有", "一下", "一个", "这种", "那样",
        "开始", "到底", "直接", "然后", "其实", "这么", "那些", "这些", "哈哈", "哈哈哈",
        "up主", "视频", "内容", "问题", "地方", "情况", "方式", "我我", "了我",
    }
)

_SORTED_TERMS: tuple[str, ...] = tuple(sorted(DOMAIN_TERMS, key=len, reverse=True))


def _bigrams(word: str) -> set[str]:
    return {word[i : i + 2] for i in range(len(word) - 1)}


def _score_terms(text: str, counts: Counter[str], used: list[bool]) -> None:
    for term in _SORTED_TERMS:
        start = 0
        while True:
            idx = text.find(term, start)
            if idx < 0:
                break
            end = idx + len(term)
            if any(used[idx:end]):
                start = idx + 1
                continue
            counts[term] += 1
            for pos in range(idx, end):
                used[pos] = True
            start = end


def _remaining_segments(text: str, used: list[bool]) -> list[str]:
    """返回未被词表占用的连续中文片段。"""
    segments: list[str] = []
    current: list[str] = []
    for idx, char in enumerate(text):
        if not used[idx] and _CJK_RE.match(char):
            current.append(char)
        elif current:
            segments.append("".join(current))
            current = []
    if current:
        segments.append("".join(current))
    return segments


def _ngrams(segment: str, min_len: int, max_len: int) -> Iterable[str]:
    length = len(segment)
    for n in range(min_len, max_len + 1):
        if length < n:
            continue
        for i in range(length - n + 1):
            yield segment[i : i + n]


def extract_keywords(
    texts: Iterable[str],
    top_n: int = 40,
    min_count: int = 2,
    max_len: int = 4,
    overlap_ratio: float = 0.6,
) -> list[dict[str, object]]:
    """统计热词，返回按优先级排序的 ``[{"word", "count"}]``。"""
    term_counts: Counter[str] = Counter()
    gram_counts: Counter[str] = Counter()

    for text in texts:
        text = str(text or "")
        if not text:
            continue
        used = [False] * len(text)
        _score_terms(text, term_counts, used)
        for segment in _remaining_segments(text, used):
            gram_counts.update(_ngrams(segment, 2, max_len))

    kept: list[tuple[str, int]] = [(w, c) for w, c in term_counts.most_common() if c > 0]
    kept_bigrams: list[set[str]] = [_bigrams(w) for w, _ in kept]

    for word, count in sorted(gram_counts.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        if count < min_count or word in _STOPWORDS:
            continue
        if any(word in term or term in word for term, _ in kept):
            continue
        grams = _bigrams(word)
        if grams and kept_bigrams:
            overlap = max(len(grams & existing) / len(grams) for existing in kept_bigrams)
            if overlap > overlap_ratio:
                continue  # 只是某个已选词的滑动版本
        kept.append((word, count))
        kept_bigrams.append(grams)
        if len(kept) >= top_n * 2:  # 多留一些候选，最后统一截断
            break

    kept.sort(key=lambda kv: (-kv[1], -len(kv[0])))
    return [{"word": w, "count": int(c)} for w, c in kept[:top_n]]


def keywords_from_comments(comments: list[dict], top_n: int = 40) -> list[dict[str, object]]:
    return extract_keywords((c.get("content", "") for c in comments), top_n=top_n)


def keywords_from_titles(videos: list[dict], top_n: int = 40) -> list[dict[str, object]]:
    return extract_keywords((v.get("title", "") for v in videos), top_n=top_n)
