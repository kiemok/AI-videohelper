"""评论情感分析单测：词典法口径、大模型返回解析与「漏答回退」兜底。

大模型部分使用假客户端（FakeClient），不联网、不消耗额度。
"""

from __future__ import annotations

from app.analysis import sentiment as S


class FakeReply:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeClient:
    """最小可用的假 LLM 客户端：按传入函数生成回复，可模拟异常。"""

    is_available = True

    def __init__(self, responder) -> None:
        self._responder = responder

    def chat(self, messages, **_kwargs):
        return FakeReply(self._responder(messages))


COMMENTS = [
    {"id": 1, "content": "这个教程太有用了，学到了干货"},
    {"id": 2, "content": "垃圾视频，浪费时间"},
    {"id": 3, "content": "一般般吧"},
    {"id": 4, "content": "真香，已收藏"},
]


# ---------------------------------------------------------------------- #
# 词典法
# ---------------------------------------------------------------------- #
def test_label_thresholds():
    assert S.label_of(0.5) == "positive"
    assert S.label_of(0.0) == "neutral"
    assert S.label_of(-0.5) == "negative"


def test_analyze_text_directions():
    positive_score, positive_label = S.analyze_text("干货满满，讲得特别好，学到了")
    negative_score, negative_label = S.analyze_text("太水了，浪费时间，劝退")

    assert positive_score > 0 and positive_label == "positive"
    assert negative_score < 0 and negative_label == "negative"
    assert 0 <= abs(positive_score) <= 1


def test_analyze_text_handles_empty_and_negation():
    assert S.analyze_text("") == (0.0, "neutral")
    # 否定词应翻转极性
    score, _label = S.analyze_text("不推荐")
    assert score < 0


def test_score_comments_covers_all_inputs():
    scored = S.score_comments(COMMENTS)
    assert [row[0] for row in scored] == [1, 2, 3, 4]


# ---------------------------------------------------------------------- #
# 大模型返回解析
# ---------------------------------------------------------------------- #
def test_parse_llm_scores_plain_array():
    parsed = S.parse_llm_scores('[{"id": 1, "score": 0.6, "label": "positive"}]')
    assert parsed[1] == (0.6, "positive")


def test_parse_llm_scores_tolerates_code_fence_and_prose():
    fenced = '```json\n[{"id": 2, "score": -0.5, "label": "negative"}]\n```'
    prose = '好的，结果如下：[{"id": 3, "score": 0.0, "label": "neutral"}] 完成'
    assert S.parse_llm_scores(fenced)[2] == (-0.5, "negative")
    assert S.parse_llm_scores(prose)[3] == (0.0, "neutral")


def test_parse_llm_scores_drops_invalid_and_clamps_score():
    raw = (
        '[{"id": "x", "score": 1}, {"id": 4, "score": "abc"},'
        ' {"id": 5, "score": 0.4, "label": "weird"}, {"id": 6, "score": 9}]'
    )
    parsed = S.parse_llm_scores(raw)
    assert set(parsed) == {5, 6}, "非法 id / 非法分数应被丢弃"
    assert parsed[5][1] == "positive", "未知 label 应按分数反推"
    assert parsed[6][0] == 1.0, "越界分数应被截断"


def test_parse_llm_scores_handles_garbage():
    assert S.parse_llm_scores("") == {}
    assert S.parse_llm_scores("not json") == {}
    assert S.parse_llm_scores('{"id": 1}') == {}


# ---------------------------------------------------------------------- #
# 打标主流程与兜底
# ---------------------------------------------------------------------- #
def test_partial_answer_is_backfilled_by_lexicon():
    client = FakeClient(
        lambda _m: '[{"id": 1, "score": 0.9, "label": "positive"}, {"id": 2, "score": -0.9, "label": "negative"}]'
    )
    scored, hits, errors = S.score_comments_with_llm(COMMENTS, client)

    assert hits == 2 and not errors
    assert len(scored) == len(COMMENTS), "必须覆盖全部输入"
    mapping = {row[0]: (row[1], row[2]) for row in scored}
    assert mapping[1] == (0.9, "positive"), "模型命中项直接采用"
    # 未命中项与词典法一致
    lexicon = {row[0]: (row[1], row[2]) for row in S.score_comments(COMMENTS)}
    assert mapping[3] == lexicon[3] and mapping[4] == lexicon[4]


def test_batch_failure_falls_back_to_lexicon_entirely():
    def boom(_messages):
        raise RuntimeError("模拟网络超时")

    scored, hits, errors = S.score_comments_with_llm(COMMENTS, FakeClient(boom))

    assert hits == 0
    assert errors and "网络超时" in errors[0]
    assert scored == S.score_comments(COMMENTS), "整批失败时结果应与词典法完全一致"


def test_build_llm_messages_contains_ids_and_text():
    messages = S.build_llm_messages(COMMENTS[:2])
    user_text = messages[-1]["content"]
    assert '"id": 1' in user_text and "这个教程太有用了" in user_text
    assert messages[0]["role"] == "system"
