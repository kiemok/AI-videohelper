"""创作咨询的轻量检索增强（RAG）：从本地数据仓库里找出与问题最相关的素材。

**实现选择（重要）**：使用本地 **BM25 关键词检索**，而不是向量检索 ——

- 桌面端零额外依赖（不需要 embedding 服务 / torch / 向量库），离线可用；
- 完全可解释：每条素材都带 BM25 得分，"为什么选中它"能在论文与界面上说清；
- 接口固定：若要升级为向量检索，只需替换 ``BM25Index.search`` 的打分实现
  （例如接入通义 ``text-embedding-v3`` 做余弦相似度），上层调用与提示词拼装无需改动。

语料来源（全部来自本地库，不联网）：作品（标题 + 账号 + 最新指标）与评论（原文 + 情感标签）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import platform_label
from app.core.logging_setup import get_logger
from app.db.repository import list_comments, list_videos

logger = get_logger(__name__)

#: 中文按单字切分、英文与数字按词切分
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")

#: 中文高频虚词（避免"的/了/是"这类字主导打分）
_STOPWORDS = frozenset(
    "的了是在我你他她它们和与及或就不都很也还要有个这那之其以为对上中下得地着吗呢吧啊呀哦嗯"
)

#: 索引规模上限（评论只取最近 N 条，控制内存与构建耗时）
MAX_COMMENT_DOCS = 400


def tokenize(text: str) -> list[str]:
    """极简分词：中文单字 + 中文二元组 + 英文/数字词，并过滤停用词。"""
    raw = _TOKEN_RE.findall(text or "")
    cjk = [t for t in raw if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    tokens = [t for t in raw if t not in _STOPWORDS]
    tokens.extend(b for b in bigrams if not any(ch in _STOPWORDS for ch in b))
    return tokens


@dataclass
class Doc:
    """一条可检索素材。"""

    kind: str  # 作品 / 评论
    doc_id: str
    title: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "doc_id": self.doc_id,
            "title": self.title,
            "text": self.text,
            "score": self.score,
            "meta": self.meta,
        }


class BM25Index:
    """BM25（Okapi）检索索引：无需第三方依赖的小语料实现。"""

    K1 = 1.5
    B = 0.75

    def __init__(self) -> None:
        self._docs: list[Doc] = []
        self._lengths: list[int] = []
        self._freqs: list[dict[str, int]] = []
        self._postings: dict[str, set[int]] = {}
        self._avg_len = 1.0

    # ------------------------------------------------------------------ #
    def add(self, doc: Doc) -> None:
        index = len(self._docs)
        tokens = tokenize(doc.text)
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        self._docs.append(doc)
        self._lengths.append(len(tokens))
        self._freqs.append(counts)
        for token in counts:
            self._postings.setdefault(token, set()).add(index)

    def finalize(self) -> None:
        if self._lengths:
            self._avg_len = max(1.0, sum(self._lengths) / len(self._lengths))

    @property
    def size(self) -> int:
        return len(self._docs)

    def search(self, query: str, top_k: int = 6) -> list[Doc]:
        """返回得分最高的前 ``top_k`` 条素材（得分为 0 的不返回）。"""
        total = len(self._docs)
        if not total:
            return []
        scores = [0.0] * total
        for token in set(tokenize(query)):
            posting = self._postings.get(token)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
            for index in posting:
                tf = self._freqs[index].get(token, 0)
                length = self._lengths[index] or 1
                norm = self.K1 * (1 - self.B + self.B * length / self._avg_len)
                scores[index] += idf * (tf * (self.K1 + 1)) / (tf + norm)

        ranked = sorted(range(total), key=lambda i: scores[i], reverse=True)
        results: list[Doc] = []
        for index in ranked[:top_k]:
            if scores[index] <= 0:
                break
            doc = self._docs[index]
            doc.score = round(scores[index], 3)
            results.append(doc)
        return results


# ---------------------------------------------------------------------- #
# 语料构建
# ---------------------------------------------------------------------- #
def _video_doc(video: dict[str, Any]) -> Doc:
    title = str(video.get("title") or "（无标题）")
    account = str(video.get("account") or "未知账号")
    parts = [f"作品《{title}》｜账号 {account}｜平台 {platform_label(video.get('platform'))}"]
    metrics: list[str] = []
    for key, label, fmt in (
        ("view_count", "累计播放", "{:,.0f}"),
        ("like_count", "点赞", "{:,.0f}"),
        ("comment_count", "评论", "{:,.0f}"),
    ):
        value = video.get(key)
        if value:
            metrics.append(f"{label} " + fmt.format(float(value)))
    if metrics:
        parts.append("、".join(metrics))
    publish = str(video.get("publish_time") or "")[:10]
    if publish:
        parts.append(f"发布于 {publish}")
    return Doc(
        kind="作品",
        doc_id=f"video:{video.get('id')}",
        title=title,
        text="，".join(parts) + "。",
        meta={
            "platform": video.get("platform"),
            "views": video.get("view_count"),
            "likes": video.get("like_count"),
        },
    )


def _comment_doc(comment: dict[str, Any]) -> Doc:
    content = str(comment.get("content") or "").strip()
    label = {"positive": "正面", "negative": "负面", "neutral": "中性"}.get(
        str(comment.get("sentiment_label") or ""), "未标注"
    )
    return Doc(
        kind="评论",
        doc_id=f"comment:{comment.get('id')}",
        title=content[:24] or "（空评论）",
        text=f"观众评论（情感 {label}）：{content}",
        meta={"sentiment": label},
    )


def build_index(
    db_url: str, comments: list[dict[str, Any]] | None = None, max_comments: int = MAX_COMMENT_DOCS
) -> BM25Index:
    """从本地库构建索引（作品 + 最近评论）。"""
    index = BM25Index()
    for video in list_videos(db_url):
        index.add(_video_doc(video))
    rows = comments if comments is not None else list_comments(db_url)
    for comment in rows[:max_comments]:
        if str(comment.get("content") or "").strip():
            index.add(_comment_doc(comment))
    index.finalize()
    return index


#: 进程内索引缓存：key = db_url，value = (评论条数指纹, 索引)
_INDEX_CACHE: dict[str, tuple[int, BM25Index]] = {}


def get_index(db_url: str, force: bool = False) -> BM25Index:
    """取（带缓存的）检索索引；数据量变化时自动重建。"""
    comments = list_comments(db_url)
    fingerprint = len(comments)
    cached = _INDEX_CACHE.get(db_url)
    if cached is not None and cached[0] == fingerprint and not force:
        return cached[1]
    index = build_index(db_url, comments=comments)
    _INDEX_CACHE[db_url] = (fingerprint, index)
    logger.info("RAG 索引构建完成：%d 条素材（当前评论总数 %d）", index.size, fingerprint)
    return index


def retrieve_material(
    db_url: str, question: str, profile: str = "", top_k: int = 6
) -> list[Doc]:
    """按问题检索最相关的素材；任何异常都退化为「无素材」，不影响咨询主流程。

    相同文本的素材（样例数据里常有重复评论）只保留得分最高的一条，避免占满素材位。
    """
    query = f"{question} {profile}".strip()
    if not query:
        return []
    try:
        candidates = get_index(db_url).search(query, top_k=max(top_k * 3, top_k + 6))
    except Exception as exc:  # noqa: BLE001 - 检索失败不应阻断咨询
        logger.warning("RAG 检索失败（已忽略素材）：%s", exc)
        return []

    unique: list[Doc] = []
    seen: set[str] = set()
    for doc in candidates:
        key = doc.text.strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
        if len(unique) >= top_k:
            break
    return unique


def format_material(docs: list[Doc]) -> str:
    """把检索结果拼成注入提示词的文本块。"""
    if not docs:
        return ""
    lines = [
        "【相关历史素材】（从本地数据仓库检索得到，引用时请点明是作品还是评论，不要编造未列出的内容）"
    ]
    lines.extend(f"{i}. {doc.text}" for i, doc in enumerate(docs, 1))
    return "\n".join(lines)
