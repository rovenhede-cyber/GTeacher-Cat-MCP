"""情绪分析：intensity 计算、技术问题不误触发、危机场景识别。"""
from emotion_engine import analyze_context


def test_intensity_in_valid_range():
    for text in [
        "今天好开心",
        "有点烦",
        "我彻底崩溃了，受不了了",
        "",
        "哈哈哈哈",
    ]:
        ctx = analyze_context(text)
        assert 1 <= ctx["intensity"] <= 10, (text, ctx["intensity"])


def test_mild_is_weaker_than_strong():
    mild = analyze_context("有点委屈")
    strong = analyze_context("我真的崩溃了，一直在哭，受不了了")
    assert mild["intensity"] < strong["intensity"]


def test_emotion_vocabulary_is_chinese_groups():
    """库里的 emotion 字段是中文标签，分析结果必须是同一套词，否则永远匹配不上。"""
    ctx = analyze_context("实验失败了，好难受，抱抱我")
    assert "伤心" in ctx["emotion"], ctx


def test_technical_question_is_flagged_serious():
    ctx = analyze_context("这个代码怎么优化，接口一直报错")
    assert ctx["serious"] is True
    assert ctx["emotion"] == [], ctx


def test_technical_word_in_emotional_sentence_is_not_serious():
    """含技术名词但主体是情绪表达时，不能判成技术任务。"""
    ctx = analyze_context("实验又失败了，好难受")
    assert ctx["serious"] is False, ctx
    assert "伤心" in ctx["emotion"], ctx


def test_crisis_detected():
    ctx = analyze_context("我真的不想活了，想结束这一切")
    assert ctx["crisis"] is True


def test_crisis_word_not_triggered_by_normal_sadness():
    ctx = analyze_context("今天有点难过")
    assert ctx["crisis"] is False


def test_actions_extracted():
    assert "抱抱" in analyze_context("抱抱我好吗")["actions"]
    assert "亲亲" in analyze_context("想亲亲你")["actions"]
    assert "求婚" in analyze_context("你愿意嫁给我吗，我要单膝跪地求婚")["actions"]


def test_plain_keywords_do_not_create_intensity():
    """不含情绪线索的普通句子强度要低。"""
    assert analyze_context("今天下午三点开会")["intensity"] <= 4
