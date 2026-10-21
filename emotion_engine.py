# -*- coding: utf-8 -*-
"""对话文本 -> 结构化上下文（R3 + v2.2 契约兼容）。

核心区分：
- `user_emotion` / `emotion`：**用户自己**在表达的情绪（英文标签 / 中文情绪组）
- `requested_sticker_emotion`：用户**点名要图片表达**的情绪（英文标签）
- `requested_visual_features`：用户点名要画面里出现的元素（冒火 / 挥拳 / 揪衣领 / 抱爱心…）
- `intensity`：1-10。用户自述时取用户语气；明确索图时取**索图语气**，不受用户情绪影响。

强度规则（cue-based，不按命中词数量堆叠）：
    强（9）  ：气死/气炸/崩溃/痛哭/狂喜 + “特别/非常/超级/太 + 情绪词”
    中（6）  ：真的/很/好/挺/比较 + 情绪词
    轻（2）  ：有点/稍微/一点点/不太 + 情绪词
    常规（5）：只出现情绪词
    重复情绪词 +2、双重程度词 +1、连续感叹号 +1（仅在中档以上累加）
"""
import hashlib
import re

from taxonomy import (
    ACTION_PATTERNS,
    CONFLICT_WORDS,
    CRISIS_WORDS,
    EMOTION_CUES,
    FEAR_WORDS,
    INTENT_CUES,
    PLAYFUL_WORDS,
    REQUEST_CUES,
    SERIOUS_NEGATIVE_WORDS,
    TECH_MARKERS,
)

# ---------------------------------------------------------------- 情绪标签
# 图库情绪组 -> 客户端沿用的英文标签（v2.2 契约）
EMOTION_LABELS = {
    "开心": "happy",
    "喜欢": "love",
    "伤心": "sad",
    "生气": "angry",
    "期待": "expect",
    "疲惫": "tired",
    "思考": "thinking",
    "感谢": "thanks",
    "害羞": "shy",
    "慌张": "panic",
    "自信": "confident",
    "平静": "calm",
    "忍耐": "endure",
    "尴尬": "awkward",
    "惊讶": "surprise",
    "馋": "hungry",
}

# ---------------------------------------------------------------- 动作 / 画面
# 动作：用户在故事里提到的动作（可能只是叙述）
ACTION_PATTERNS.update({
    "安慰": ["安慰", "哄哄", "陪陪我", "陪我"],
})

# 画面：用户点名要求的**图片内容**，必须能在图片元数据里找到证据
VISUAL_PATTERNS = {
    "冒火": (r"(?:头(?:顶|上)|脑袋|额头).{0,3}(?:冒火|着火|起火|火焰)",
             r"(?:气得|气到).{0,2}冒烟", r"冒火", r"火焰"),
    "挥拳": (r"(?:挥|举|抬|攥).{0,2}拳(?:头)?", r"拳头"),
    "揪衣领": (r"(?:揪|抓|拽|扯).{0,3}(?:衣领|领子|衣服)",),
    "抱爱心": (r"(?:抱|捧|搂).{0,3}(?:爱心|红心|心形)",),
    "亲吻": (r"亲亲", r"亲吻", r"接吻", r"么么"),
    "摸头": (r"摸.{0,2}头", r"摸摸头", r"揉.{0,2}头"),
    "摇尾巴": (r"摇.{0,2}尾巴", r"摆.{0,2}尾巴"),
}

# ---------------------------------------------------------------- 语气与语境
_EMOTION_CUE = r"(?:生气|气死|气炸|冒火|恼火|烦|难过|伤心|难受|委屈|失落|崩溃|开心|高兴|快乐|害羞|脸红)"
MILD_RE = re.compile(rf"(?:有点|一点点|稍微|轻微|小小|不太|微微).{{0,4}}{_EMOTION_CUE}")
STRONG_RE = re.compile(
    r"气死|气炸|暴怒|怒火中烧|崩溃|痛哭|狂喜|激动坏|开心坏|"
    rf"(?:特别|非常|极其|超级|太).{{0,4}}{_EMOTION_CUE}"
)
MEDIUM_RE = re.compile(rf"(?:真的|很|好|挺|比较).{{0,4}}{_EMOTION_CUE}")
REPEAT_RE = re.compile(rf"({_EMOTION_CUE})(?:[，,\s]{{0,2}}\1)+")
NEGATION_RE = re.compile(r"(?:不是(?:在)?|并非|没有|没在|不想|(?<!特)别|不要|无需|不需要|不)$")

SUCCESS_RE = re.compile(
    r"成功|做成|搞定|完成|实现|终于|"
    r"(?:考试|测试|审核|验收|答辩|面试).{0,4}通过|"
    r"通过(?:了)?(?:考试|测试|审核|验收|答辩|面试)"
)
DISTRESS_RE = re.compile(r"失败|难受|伤心|难过|委屈|崩溃|失落|哭")
COMFORT_REQUEST_RE = re.compile(r"求抱抱|抱抱我|安慰我|哄哄我|陪陪我|陪我")

# ---------------------------------------------------------------- 明确索图
STICKER_OBJECT = r"(?:表情包|表情|贴纸|猫猫|小猫|猫|cat-\d{3})"
DIRECT_STICKER_RE = re.compile(
    r"(?:^|[，,。！!；;？?\s])"
    r"(?:(?:再|顺便|另外)\s*)?"
    r"(?:(?:请|麻烦|你(?:可以|能不能)|能不能|可不可以|可以)\s*)?"
    r"(?:(?:帮我|给我)\s*)?"
    r"(?:我想要|我要|想要|发|发送|来|用|选|挑|换成|贴|展示|放|求|指定)"
    rf"[^。！？!?]{{0,18}}?{STICKER_OBJECT}",
    re.IGNORECASE,
)
WANT_STICKER_RE = re.compile(
    r"(?:^|[，,。！!；;？?\s])(?:给我|我要|我想要|想要|要)"
    rf"(?![^。！？!?]{{0,18}}?(?:分析|解释|介绍|说明))[^。！？!?]{{0,18}}?{STICKER_OBJECT}",
    re.IGNORECASE,
)
OBJECT_FIRST_RE = re.compile(
    rf"(?:^|[，,。！!；;？?\s])把[^。！？!?]{{0,18}}?{STICKER_OBJECT}"
    r"[^。！？!?]{0,8}?(?:发|发送|给我|用|选|换|贴|展示|放)",
    re.IGNORECASE,
)
NEGATED_STICKER_REQUEST_RE = re.compile(
    r"不要|不用|无需|不需要|不想|不是要|没要|请勿|禁止|别(?:发|送|用|给|来|选|挑|贴|放)"
)


def _negated(text, start):
    prefix = text[max(0, start - 8):start]
    return bool(NEGATION_RE.search(prefix))


def text_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _matched(text, words):
    return [w for w in words if w in text]


def _detect_groups(text):
    """中文情绪组 + 命中的线索词；否定语境不计。"""
    groups = []
    hits = []
    for group, cues in EMOTION_CUES.items():
        for cue in cues:
            matches = list(re.finditer(re.escape(cue), text))
            if not matches:
                continue
            if any(not _negated(text, m.start()) for m in matches):
                groups.append(group)
                hits.append(cue)
                break
    return groups, hits


def _detect_actions(text):
    actions = []
    for action, aliases in ACTION_PATTERNS.items():
        if any(alias in text for alias in aliases):
            actions.append(action)
    return actions


def _detect_visual_features(text):
    found = []
    for feature, patterns in VISUAL_PATTERNS.items():
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
            if any(not _negated(text, m.start()) for m in matches):
                found.append(feature)
                break
    return found


def _explicit_sticker_match(text):
    for pattern in (DIRECT_STICKER_RE, WANT_STICKER_RE, OBJECT_FIRST_RE):
        for match in pattern.finditer(text):
            if not NEGATED_STICKER_REQUEST_RE.search(match.group()):
                return match
    return None


def _sticker_query(text):
    """去掉“给我/请发/通过插件发送”这类投递指令，留下描述目标图片的词。"""
    text = text.lstrip("，,。；; ")
    prefixes = (
        r"^(?:用户|对方)",
        r"^(?:明确)?(?:要求|请求|希望)",
        r"^(?:通过|使用|用).{0,12}?(?:插件|工具|接口|mcp)\s*",
        r"^(?:请|麻烦|帮我|给我|我想要|我要|想要)",
    )
    while True:
        previous = text
        for pattern in prefixes:
            text = re.sub(pattern, "", text, count=1).lstrip()
        if text == previous:
            return re.sub(r"^(?:发送|发(?=一?[张个只])|来|找|提供)(?:一[张个])?(?:表达)?",
                          "", text, count=1).lstrip()


def estimate_intensity(text, has_emotion):
    """cue-based 1-10。无情绪线索时为 1（保持 1-10 取值域）。"""
    if not has_emotion:
        return 1
    if STRONG_RE.search(text):
        level = 9
    elif MILD_RE.search(text):
        level = 2
    elif MEDIUM_RE.search(text):
        level = 6
    else:
        level = 5
    if level >= 5 and REPEAT_RE.search(text):
        level = min(10, level + 2)
    if level >= 5 and re.search(r"(?:真的|非常|特别|超级).{0,12}(?:真的|非常|特别|超级)", text):
        level = min(10, level + 1)
    if level >= 5 and re.search(r"[!！]{2,}", text):
        level = min(10, level + 1)
    return max(1, min(10, level))


def _labels(groups):
    return [EMOTION_LABELS.get(g, g) for g in groups]


def analyze_context(text, explicit_request=False):
    raw = text or ""
    normalized = raw.strip().lower()

    request_match = _explicit_sticker_match(normalized)
    explicit_sticker_request = bool(explicit_request or request_match is not None)

    if request_match is not None:
        # 请求之前的部分才描述用户自己（“我气死了，请发一张开心猫”）
        user_text = normalized[: request_match.start()]
        requested_text = re.split(r"(?:但|不过|其实)我(?:本人|自己|现在|今天)?",
                                  normalized[request_match.start():], maxsplit=1)[0]
    elif explicit_sticker_request:
        # 客户端给的是第三人称摘要
        user_text = ""
        requested_text = normalized
    else:
        user_text = normalized
        requested_text = ""

    query = _sticker_query(requested_text)

    user_groups, user_hits = _detect_groups(user_text)
    requested_groups, requested_hits = _detect_groups(query)

    actions = _detect_actions(normalized)
    visual_features = _detect_visual_features(query if explicit_sticker_request else normalized)

    crises = _matched(raw, CRISIS_WORDS)
    conflicts = _matched(raw, CONFLICT_WORDS)
    fears = _matched(raw, FEAR_WORDS)
    negatives = _matched(raw, SERIOUS_NEGATIVE_WORDS)
    playful = _matched(normalized, PLAYFUL_WORDS)
    tech = _matched(normalized, TECH_MARKERS)
    request_cues = _matched(normalized, REQUEST_CUES)

    distress = bool(DISTRESS_RE.search(normalized))
    success = bool(SUCCESS_RE.search(normalized))
    emotional_request = bool(COMFORT_REQUEST_RE.search(normalized))

    # 场景：意图在元数据里的落点（安慰/庆祝/亲密互动/求婚）
    scenes = []
    close_actions = {"拥抱", "亲吻"}
    if "求婚" in actions:
        scenes.append("求婚")
    if emotional_request or distress or "安慰" in actions:
        scenes.append("安慰")
    if (success and not distress) or "庆祝" in actions:
        scenes.append("庆祝")
    if (("抱抱" in actions or "亲亲" in actions or "比心" in actions)
            and "安慰" not in scenes):
        scenes.append("亲密互动")
    scenes = list(dict.fromkeys(scenes))

    intents = [i for i, cues in INTENT_CUES.items() if _matched(normalized, cues)]
    if "安慰" in scenes:
        intents.append("comfort")
    if "庆祝" in scenes:
        intents.append("celebrate")
    if "亲密互动" in scenes or "求婚" in scenes:
        intents.append("affection")
    intents = list(dict.fromkeys(intents))

    crisis = bool(crises)
    serious = bool(tech) or bool(request_cues and not user_groups)
    if crisis or explicit_sticker_request:
        serious = False  # 明确索图是工具指令，不是技术任务

    # 强度：索图时看索图语气，自述时看用户语气
    if explicit_sticker_request and (requested_groups or visual_features):
        intensity = estimate_intensity(query, bool(requested_groups))
    else:
        intensity = estimate_intensity(user_text or normalized, bool(user_groups))

    # 打分用的目标情绪：索图时用被请求的情绪，否则用用户情绪
    target_groups = list(requested_groups) if explicit_sticker_request else list(user_groups)
    if not target_groups and explicit_sticker_request and "求婚" in scenes:
        target_groups = ["喜欢"]
    if not target_groups and not explicit_sticker_request:
        if "安慰" in scenes:
            target_groups = ["伤心"]
        elif "庆祝" in scenes:
            target_groups = ["开心"]
    target_groups = list(dict.fromkeys(target_groups))

    keywords = sorted(set(user_hits + requested_hits))
    if explicit_sticker_request and "点赞" in actions:
        keywords = sorted(set(keywords + ["点赞"]))

    return {
        # —— R3 打分用 ——
        "emotion": target_groups,
        "intent": intents,
        "keywords": keywords,
        "actions": actions,
        "intensity": intensity,
        "crisis": crisis,
        "serious": serious,
        "playful": bool(playful),
        "conflict": bool(conflicts),
        "fear": bool(fears),
        "strong_negative": bool(negatives),
        "scenes": scenes,
        # —— v2.2 契约 ——
        "user_emotion": _labels(user_groups),
        "requested_sticker_emotion": _labels(requested_groups),
        "requested_actions": visual_features if explicit_sticker_request else [],
        "requested_visual_features": visual_features if explicit_sticker_request else [],
        "explicit_sticker_request": explicit_sticker_request,
        "sticker_query": query if explicit_sticker_request else raw,
        "request_type": "factual" if serious else "social",
        "original_text": raw,
        "context_hash": text_hash(raw),
        # —— 排查用原始命中（不参与打分，也不进日志）——
        "_signals": {
            "crisis": crises,
            "conflict": conflicts,
            "fear": fears,
            "strong_negative": negatives,
            "playful": playful,
            "tech": tech,
            "request": request_cues,
            "user_hits": user_hits,
            "requested_hits": requested_hits,
            "visual": visual_features,
        },
    }
