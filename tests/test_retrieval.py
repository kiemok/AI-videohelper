"""创作咨询 RAG（BM25 检索）单测：分词、排序、去重与降级。

纯内存构造语料，不依赖数据库、模型或网络。
"""

from __future__ import annotations

from app.consulting.retrieval import BM25Index, Doc, format_material, tokenize


def build_index() -> BM25Index:
    index = BM25Index()
    index.add(
        Doc(
            kind="作品",
            doc_id="video:1",
            title="充电宝测评",
            text="作品《为什么你的充电宝越充越慢 #数码测评》｜账号 老张说科技｜平台 抖音，累计播放 274,218。",
        )
    )
    index.add(
        Doc(
            kind="作品",
            doc_id="video:2",
            title="城市漫步",
            text="作品《第一次尝试citywalk路线分享 #生活方式》｜账号 美美Vlog｜平台 抖音，累计播放 41,997。",
        )
    )
    index.add(Doc(kind="评论", doc_id="comment:1", title="音质一般", text="观众评论（情感 负面）：音质一般"))
    index.add(Doc(kind="评论", doc_id="comment:2", title="价格虚高", text="观众评论（情感 负面）：价格虚高"))
    index.finalize()
    return index


# ---------------------------------------------------------------------- #
# 分词
# ---------------------------------------------------------------------- #
def test_tokenize_keeps_cjk_and_bigrams_and_drops_stopwords():
    tokens = tokenize("抖音的充电宝测评")
    assert "抖" in tokens and "音" in tokens
    assert "充电" in tokens, "应包含中文二元组，提高区分度"
    assert "的" not in tokens, "停用词应被过滤"


def test_tokenize_keeps_ascii_words():
    tokens = tokenize("B站 vs douyin 2026")
    assert "douyin" in tokens
    assert "2026" in tokens


# ---------------------------------------------------------------------- #
# 检索
# ---------------------------------------------------------------------- #
def test_search_ranks_relevant_video_first():
    results = build_index().search("充电宝 数码测评 播放", top_k=3)
    assert results, "应命中素材"
    assert results[0].doc_id == "video:1"
    assert results[0].score > 0
    scores = [doc.score for doc in results]
    assert scores == sorted(scores, reverse=True), "结果应按 BM25 得分降序"


def test_search_matches_comment_by_keyword():
    results = build_index().search("价格 评价", top_k=2)
    assert any(doc.kind == "评论" and "价格" in doc.text for doc in results)


def test_search_returns_empty_for_unrelated_query():
    assert build_index().search("量子力学 黑洞", top_k=3) == []


def test_search_on_empty_index_is_safe():
    assert BM25Index().search("任意查询") == []


# ---------------------------------------------------------------------- #
# 注入格式
# ---------------------------------------------------------------------- #
def test_format_material_includes_all_docs_and_instructions():
    docs = build_index().search("充电宝", top_k=2)
    assert docs, "「充电宝」至少应命中一条素材"
    text = format_material(docs)
    assert "【相关历史素材】" in text
    for index, doc in enumerate(docs, 1):
        assert f"{index}." in text
        assert doc.text[:18] in text


def test_format_material_empty_returns_blank():
    assert format_material([]) == ""
