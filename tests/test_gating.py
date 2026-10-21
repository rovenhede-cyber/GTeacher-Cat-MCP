"""触发闸门：技术问题、严肃任务、危机场景不发表情包。"""
from emotion_engine import analyze_context
from trigger_engine import should_send_sticker
import sticker_engine


def _gate(text):
    return should_send_sticker(analyze_context(text))


def test_tech_question_blocked():
    assert _gate("这段代码怎么优化，接口一直报错") is False
    assert _gate("帮我排查一下这个 Python 异常") is False
    assert _gate("数据库索引的原理是什么") is False


def test_tech_question_with_emotion_word_blocked():
    """技术问题里带了情绪词，也不能仅凭关键词就发猫猫。"""
    assert _gate("这段代码报错，烦死了，怎么解决") is False


def test_crisis_blocked():
    assert _gate("我不想活了") is False


def test_emotional_scenes_still_trigger():
    assert _gate("实验又失败了，好难受") is True
    assert _gate("终于通过啦，好开心") is True
    assert _gate("谢谢你一直帮我") is True
    assert _gate("抱抱我好不好") is True


def test_plain_statement_blocked():
    assert _gate("今天下午三点开会") is False
    assert _gate("嗯") is False


def test_thesis_frustration_is_emotional_not_technical():
    """写论文吐槽属于情绪场景，不应被当成技术任务拦掉。"""
    assert _gate("论文写不出来，好崩溃") is True


def test_crisis_returns_no_sticker(library):
    assert sticker_engine.select_sticker("我真的撑不下去了，不想活") is None


def test_tech_returns_no_sticker(library):
    assert sticker_engine.select_sticker("这个 API 报 500，怎么排查") is None
