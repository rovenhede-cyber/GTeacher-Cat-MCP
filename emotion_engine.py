import re


EMOTION_MAP = {

    "sad": [
        "伤心",
        "难过",
        "痛苦",
        "失败",
        "崩溃",
        "哭",
        "委屈",
        "失落"
    ],

    "happy": [
        "开心",
        "快乐",
        "成功",
        "完成",
        "太好了",
        "开心死了"
    ],

    "love": [
        "喜欢",
        "想你",
        "爱你",
        "亲亲",
        "抱抱",
        "宝宝"
    ],

    "angry": [
        "生气",
        "气死",
        "讨厌",
        "烦"
    ],

    "thinking": [
        "思考",
        "怎么办",
        "分析",
        "问题",
        "研究"
    ]

}


INTENT_MAP = {

    "comfort": [
        "安慰",
        "抱抱",
        "陪我",
        "难受"
    ],

    "celebrate": [
        "成功",
        "完成",
        "终于",
        "开心"
    ],

    "affection": [
        "喜欢",
        "想你",
        "亲亲",
        "宝宝"
    ],

    "help": [
        "怎么办",
        "怎么做",
        "分析"
    ]

}


KEYWORD_MAP = {

    "sad": [
        "哭哭",
        "抱抱",
        "加油",
        "安慰"
    ],

    "happy": [
        "庆祝",
        "开心",
        "撒花"
    ],

    "love": [
        "贴贴",
        "爱心",
        "亲亲"
    ]

}


def analyze_context(text):

    text = text.lower()


    emotions = []
    intents = []
    keywords = []


    # 情绪识别

    for emotion, words in EMOTION_MAP.items():

        for word in words:

            if word in text:
                emotions.append(emotion)
                break



    # 意图识别

    for intent, words in INTENT_MAP.items():

        for word in words:

            if word in text:
                intents.append(intent)
                break



    # 关键词扩展

    for emotion in emotions:

        keywords.extend(
            KEYWORD_MAP.get(
                emotion,
                []
            )
        )


    # 去重

    emotions = list(set(emotions))
    intents = list(set(intents))
    keywords = list(set(keywords))


    # 情绪强度

    intensity = min(
        len(emotions) * 3 +
        len(intents) * 2,
        10
    )


    return {

        "emotion": emotions,

        "intent": intents,

        "keywords": keywords,

        "intensity": intensity

    }