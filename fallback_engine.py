# -*- coding: utf-8 -*-
"""R7.1 弱信号显式索图兜底：用户明确要图，但这句话里没有任何可用于选图的信号。

典型："发张猫猫" / "给我个表情包" / "给我看看猫猫"。
R5 的行为是 `no_request_signal` -> None（见 `_select_explicit`），体验上等于
"你说要图，但我不知道你想表达什么，所以不发"。

这里只解决"确实要图但没说要什么"这一种情况，边界刻意收得很紧：

启动条件（全部成立才启动，任一不成立都给出可诊断原因）
1. 客户端显式声明 `explicit_request=True`（只有原文像索图、客户端没声明的不兜底）
2. 原文里**真的**有明确索图表达（`request_evidence`，防止误传 flag 的技术求助被兜底）
3. `signal_count == 0`（有任何情绪/动作/场景/画面信号时，交给正常选图逻辑）
4. 无危机（安全闸门本来就会先拦，这里再守一次）
5. 过滤后的候选池里仍有"通用安全"图片（`select_generic`）

候选判定只用图库**已有**元数据（本图库没有 accompany/cute 之类的英文字段）：
- 情绪组必须全部落在 `GENERIC_SAFE_GROUPS`（开心 / 平静），负向与过强的情绪一律不发
- 没有任何 relationship 声明（不把亲昵/朋友专属图当通用图发给 formal）
- 文本字段（name/description/tags/scene/action/use_when）不含
  `GENERIC_UNSAFE_MARKERS`（亲密、暧昧、攻击、危险、悲伤、不宜场合）
- 复用 `sticker_engine.apply_filters` 的结果，危险图/avoid_when/关系过滤一律先生效

选择顺序固定（`GENERIC_CANDIDATE_ORDER`，人工确认过），因此同一图库版本下结果可复现：
不做打分、不随机、不看意图，避免"为了发图而发图"。
图库升级后如果这些 id 消失或元数据变脏，`select_generic` 会自动跳过；
`tests/test_r7_generic_fallback.py` 里有断言，保证候选表不会悄悄失效。
"""
import re

from taxonomy import DANGER_MARKERS, group_of

# ---------------------------------------------------------------- 判定原因码
REASON_NOT_EXPLICIT = "not_explicit_request"     # 客户端没声明 explicit_request
REASON_TEXT_MISSING = "explicit_text_missing"    # 原文没有真实的索图表达
REASON_SIGNALS_PRESENT = "signals_present"       # 有可用的选图信号，不该由兜底接管
REASON_SAFETY = "blocked_by_safety"              # 危机等安全条件
REASON_NO_CANDIDATE = "no_generic_candidate"     # 没有合格的通用安全图片
REASON_WEAK_EXPLICIT = "weak_explicit_request"   # 触发兜底

# ---------------------------------------------------------------- 索图表达
# 交付动词 + 最多 10 个字符 + 图片对象。刻意不含"用/做"，
# 避免 "我要用猫猫做头像" 这类**使用意图**被当成发表情包的请求。
# 否定前缀被并进匹配（而不是事后看前缀），否则 "别发猫猫" 里的 "别" 会被切在匹配之外。
REQUEST_EVIDENCE_RE = re.compile(
    r"(?P<neg>不要|不用|无需|不需要|不想|不是要|没要|请勿|禁止|(?<![特分级告])别)?"
    r"(?:发|发送|来|给我|给个|求|整|甩|贴|换成|换一?[张个])"
    r"[^。！？!?；;]{0,10}?"
    r"(?:猫猫|小猫|猫|表情包|表情|贴纸)"
)


def request_evidence(text):
    """原文里是否有**真实的**明确索图表达（否定语境不算）。"""
    text = (text or "").strip().lower()
    if not text:
        return False
    for match in REQUEST_EVIDENCE_RE.finditer(text):
        if match.group("neg"):
            continue
        return True
    return False


# ---------------------------------------------------------------- 通用安全候选
# 只允许"友好 / 中性"的情绪组。负向（伤心/生气/疲惫）、亲昵（喜欢/害羞/期待）
# 一律不进通用池——通用图不该替用户表达情绪，也不该带亲密暗示。
GENERIC_SAFE_GROUPS = frozenset({"开心", "平静"})

# 命中任一即排除。覆盖：亲密暧昧、攻击威慑、悲伤崩溃、不宜场合。
GENERIC_UNSAFE_MARKERS = (
    # 亲密 / 暧昧
    "亲亲", "亲吻", "贴贴", "抱抱", "抱心", "抱爱心", "比心", "依偎", "爱心", "心动",
    "浪漫", "示爱", "求婚", "戒指", "玫瑰", "情书", "撒娇", "爱你", "想念", "甜蜜",
    "暧昧", "媳妇", "老公", "老婆", "宝宝", "心动", "脸红",
    # 攻击 / 危险
    "菜刀", "持刀", "刀", "威胁", "威慑", "挥拳", "揪衣领", "冒火", "愤怒", "生气",
    "不爽", "警告", "嘲讽", "嫌弃", "鄙视", "拒绝", "禁止", "中指", "炸弹",
    # 悲伤 / 崩溃 / 负面
    "伤心", "难过", "委屈", "哭泣", "流泪", "擦泪", "眼泪", "崩溃", "无助", "失落",
    "遗憾", "心碎", "痛苦", "绝望", "摆烂", "躺平", "辞职", "忍耐", "呐喊", "发火",
    # 不宜场合
    "抽烟", "喝醉", "血", "呕吐", "垃圾桶", "内裤", "裸",
)

# 人工确认过的通用陪伴候选，按优先级排列（同样是固定顺序 = 结果可复现）。
# 依据：打招呼 / 举爪 / 傻乐 / 举对勾 / 点赞 这类"友好、中性、无亲密暗示"的表达。
# 元数据仍要过 `generic_reject_reason()`，所以图库升级后变脏的条目会被自动跳过。
GENERIC_CANDIDATE_ORDER = (
    "cat-030",   # 打招呼小猫：问候，最通用的"给你一张猫猫"
    "cat-074",   # 吐舌傻乐狗：开心放松
    "cat-044",   # 眯眼举爪狗：眯眼笑
    "cat-004",   # 收到消息猫：平静，确认收到
    "cat-019",   # 对勾认可猫：开心，认同
    "cat-020",   # 举手点赞猫：开心，赞赏
    "cat-067",   # 吐舌摇尾狗：开心
    "cat-056",   # 卷毛呆立狗：平静，呆萌
)

_CORE_FIELDS = ("name", "description", "tags", "scene", "action", "use_when")


def _evidence_text(item):
    parts = []
    for field in _CORE_FIELDS:
        value = item.get(field)
        if isinstance(value, (list, tuple)):
            parts.extend(str(x) for x in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def generic_reject_reason(item):
    """不合格时返回原因（可诊断），合格返回 None。"""
    declared = item.get("relationship") or []
    if declared:
        # 声明了适用关系 = 专属图，不能当通用图（formal 场景尤其危险）
        return "relationship_declared:%s" % ",".join(str(x) for x in declared)

    groups = {group_of(tag) for tag in (item.get("emotion") or [])}
    groups.discard(None)
    if not groups:
        return "no_emotion_group"
    if not groups <= GENERIC_SAFE_GROUPS:
        return "emotion_group_not_generic:%s" % ",".join(sorted(groups))

    text = _evidence_text(item)
    for marker in DANGER_MARKERS:
        if marker and marker in text:
            return "dangerous_marker:%s" % marker
    for marker in GENERIC_UNSAFE_MARKERS:
        if marker in text:
            return "unsafe_marker:%s" % marker
    return None


def select_generic(candidates, order=None):
    """按固定顺序挑第一张合格的通用图。

    candidates 必须是**已过 apply_filters** 的候选池（安全过滤先于兜底）。
    返回 (item|None, detail)，detail 里带跳过原因，便于日志排查。
    """
    order = GENERIC_CANDIDATE_ORDER if order is None else order
    index = {item.get("id"): item for item in candidates or []}
    skipped = []
    for rank, sticker_id in enumerate(order, start=1):
        item = index.get(sticker_id)
        if item is None:
            skipped.append("%s:not_in_pool" % sticker_id)
            continue
        reason = generic_reject_reason(item)
        if reason:
            skipped.append("%s:%s" % (sticker_id, reason))
            continue
        return item, {"rank": rank, "skipped": skipped}
    return None, {"rank": None, "skipped": skipped}


def evaluate(ctx):
    """返回 (eligible, reason)。只做策略判断，不碰图库。"""
    if ctx.get("crisis"):
        return False, REASON_SAFETY
    if not ctx.get("explicit_request_flag"):
        # 只有原文像索图、客户端没声明 explicit_request 的，不兜底（保持 R5 行为）
        return False, REASON_NOT_EXPLICIT
    if not request_evidence(ctx.get("original_text")):
        # 误传 explicit_request=True 的普通对话（技术求助等）走这里
        return False, REASON_TEXT_MISSING
    if int(ctx.get("signal_count") or 0) > 0:
        return False, REASON_SIGNALS_PRESENT
    return True, REASON_WEAK_EXPLICIT
