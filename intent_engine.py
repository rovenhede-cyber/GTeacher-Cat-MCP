# -*- coding: utf-8 -*-
"""R5 意图引擎：助手回应意图 + 表情包表达行为。

三件事分开：
1. **助手回应意图**（10 类）：调用方最清楚"我这条回复想做什么"，所以优先用显式传入的
   `assistant_response_intent`；没传时才用文本线索推导（`derive_intent`）。
2. **表情包表达行为**：这张图被发出去时"在做一个什么表达"。来源优先级不可逆：
       manual overlay（人工标注，带证据）  >  规则推导（scene -> behavior）  >  neutral
   推导**永不到道歉**（apology）：服务端无法从用户文本判断助手该不该道歉，
   也不能因为"鞠躬"像道歉就把"谢谢鞠躬猫"当成道歉图。
3. **回退链**：意图 -> 行为精确命中 8 分 / 同家族 4 分 / 明显矛盾 -10 分，
   全部只在安全闸门与过滤器**之后**发生。
"""
import json
import os

from logger_config import logger
from taxonomy import (
    ASSISTANT_BEHAVIORS,
    ASSISTANT_INTENTS,
    BEHAVIOR_RULES,
    INTENT_CONFLICT,
    INTENT_FAMILY,
    group_of,
)

OVERLAY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_overlay.json")

# 明确写死：apology 没有任何"隐式回落"行为。
# 没有人工标注的道歉图时，道歉意图就是 None，绝不拿 comfort/感谢图顶替。
APOLOGY_FALLBACK_BEHAVIORS = frozenset()

# 助手视角的行为：发出去是"我在表达"，而不是"你在表达"
_ASSISTANT_SIDE = frozenset(
    {"comfort", "accompany", "encourage", "celebrate", "gratitude", "apology", "agree", "acknowledge"}
)
# 用户视角的情绪标签：这类图是"替用户表达"，不该拿助手 persona 分
_USER_SIDE_EMOTIONS = frozenset({"生气", "嘲讽", "嫌弃", "警告", "怀疑"})

CORE_TEXT_FIELDS = ("name", "description", "action", "tags", "scene", "use_when")

_overlay = None


class OverlayError(ValueError):
    """intent_overlay.json 写错了（证据引用不存在 / schema 不合法）。"""


# ---------------------------------------------------------------- overlay 读写
def reset_overlay():
    global _overlay
    _overlay = None


def disable_overlay(reason=""):
    """把人工标注置空，降级为规则推导。

    只在标注校验失败时调用：一个写坏的标注文件不该让整个选图链路不可用，
    也不该让 `R5_INTENT_MODE=off` 这个回滚开关失效（load_library 不看模式都会校验）。
    """
    global _overlay
    _overlay = {"schema": 1, "stickers": {}, "disabled_reason": reason}
    logger.error("intent_overlay 已禁用，降级为规则推导：%s", reason or "-")
    return _overlay


def load_overlay(path=None, force=False):
    """加载人工标注。写错就抛 OverlayError——这是数据错误，应该早暴露。"""
    global _overlay
    if _overlay is not None and not force and path is None:
        return _overlay

    path = path or OVERLAY_PATH
    if not os.path.exists(path):
        data = {"schema": 1, "stickers": {}}
    else:
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except ValueError as exc:
                raise OverlayError("intent_overlay.json 不是合法 JSON：%s" % exc) from exc

    if not isinstance(data, dict) or not isinstance(data.get("stickers", {}), dict):
        raise OverlayError("intent_overlay.json 结构异常：需要 {schema, stickers:{id:{...}}}")

    data.setdefault("schema", 1)
    data.setdefault("stickers", {})
    if path == OVERLAY_PATH:
        _overlay = data
    return data


def _item_text(item):
    parts = []
    for field in CORE_TEXT_FIELDS:
        value = item.get(field)
        if isinstance(value, (list, tuple)):
            parts.extend(str(x) for x in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def validate_overlay(overlay, library=None, warn_orphans=True):
    """校验标注：证据必须真实存在（抛错），孤儿 id 只告警（返回孤儿列表）。"""
    entries = overlay.get("stickers") or {}
    index = None
    if library is not None:
        index = {item.get("id"): item for item in library}

    orphans = []
    for sticker_id, entry in entries.items():
        if not isinstance(entry, dict):
            raise OverlayError("overlay 条目必须是对象：%s" % sticker_id)
        behaviors = entry.get("behaviors") or []
        if isinstance(behaviors, str):
            behaviors = [behaviors]
        unknown = [b for b in behaviors if b not in ASSISTANT_BEHAVIORS]
        if unknown:
            raise OverlayError("overlay 出现未知行为 %s：%s" % (unknown, sticker_id))
        if entry.get("source") != "manual":
            raise OverlayError("overlay 只接受人工标注（source=manual）：%s" % sticker_id)
        evidence = str(entry.get("evidence") or "").strip()
        if not evidence:
            raise OverlayError("overlay 缺少证据：%s" % sticker_id)

        if index is None:
            continue
        item = index.get(sticker_id)
        if item is None:
            orphans.append(sticker_id)
            continue
        if evidence not in _item_text(item):
            raise OverlayError(
                "证据不在图片元数据里：%s 引用 %r" % (sticker_id, evidence)
            )

    if orphans and warn_orphans:
        logger.warning(
            "intent_overlay 含图库中不存在的 id（已忽略）：%s", ", ".join(sorted(orphans))
        )
    return sorted(orphans)


def _overlay_entry(sticker_id):
    entry = (load_overlay().get("stickers") or {}).get(sticker_id)
    if not isinstance(entry, dict):
        return None
    behaviors = entry.get("behaviors") or []
    if isinstance(behaviors, str):
        behaviors = [behaviors]
    behaviors = [b for b in behaviors if b in ASSISTANT_BEHAVIORS]
    if not behaviors:
        return None
    return {
        "behaviors": behaviors,
        "persona_fit": entry.get("persona_fit") or derive_persona(behaviors),
        "source": "overlay",
    }


# ---------------------------------------------------------------- 行为
def derive_behaviors(item):
    """按 scene 推导（只在没有人工标注时使用）。"""
    scenes = item.get("scene") or []
    if isinstance(scenes, str):
        scenes = [scenes]
    found = []
    for scene in scenes:
        for behavior in BEHAVIOR_RULES.get(str(scene), ()):
            if behavior not in found:
                found.append(behavior)
    return found


def derive_persona(behaviors, item=None):
    """这张图更像"助手在表达"还是"用户在表达"（决定是否给 persona 加分）。"""
    if item is not None:
        groups = {group_of(tag) for tag in (item.get("emotion") or [])}
        tags = {str(tag) for tag in (item.get("emotion") or [])}
        if (groups & {"生气"}) or (tags & _USER_SIDE_EMOTIONS):
            return "user"
    if "teasing" in behaviors:
        return "user"
    if behaviors and set(behaviors) <= _ASSISTANT_SIDE:
        return "assistant"
    return "shared"


def behaviors_for(item):
    """返回 {behaviors, persona, source}；source ∈ overlay / derived / neutral。"""
    sticker_id = item.get("id")
    entry = _overlay_entry(sticker_id) if sticker_id else None
    if entry is not None:
        return entry

    derived = derive_behaviors(item)
    if derived:
        return {
            "behaviors": derived,
            "persona_fit": derive_persona(derived, item),
            "source": "derived",
        }
    return {"behaviors": ["neutral"], "persona_fit": "shared", "source": "neutral"}


# ---------------------------------------------------------------- 意图
def normalize_intent(value):
    """非法/空值返回 None（调用方负责告警），不抛异常。"""
    if value is None:
        return None
    text = str(value).strip().lower()
    return text if text in ASSISTANT_INTENTS else None


def intent_family(intent):
    return INTENT_FAMILY.get(intent)


def family_behaviors(intent):
    """同一家族的其它行为（用于"意图没精确命中但语义相近"的给分）。"""
    family = INTENT_FAMILY.get(intent)
    if not family:
        return frozenset()
    return frozenset(b for b, f in INTENT_FAMILY.items() if f == family and b != intent)


def conflicting(intent):
    return frozenset(INTENT_CONFLICT.get(intent, ()))


# 情绪组 -> 兜底意图（顺序即优先级：越靠前越具体）
_GROUP_FALLBACK = (
    ("伤心", "comfort"),
    ("生气", "comfort"),
    ("疲惫", "accompany"),
    ("慌张", "encourage"),
    ("期待", "encourage"),
    ("感谢", "gratitude"),
    ("喜欢", "affection"),
    ("害羞", "affection"),
    ("开心", "celebrate"),
)


def _teasing_target(text):
    return any(word in text for word in ("你", "您", "他", "她", "这"))


def derive_intent(ctx):
    """从已有分析结果推导"助手这条回复想做什么"。推不出来就返回 None。"""
    if not ctx:
        return None
    if ctx.get("crisis") or ctx.get("serious"):
        return None
    if ctx.get("explicit_sticker_request"):
        # 用户点名要图，选图由请求本身决定；此时再叠一层"助手意图"只会互相打架
        return None

    text = str(ctx.get("sticker_query") or ctx.get("original_text") or "").lower()
    scenes = set(ctx.get("scenes") or [])
    intents = set(ctx.get("intent") or [])
    groups = list(ctx.get("emotion") or [])
    distress = "安慰" in scenes

    if "求婚" in scenes or ("亲密互动" in scenes and not distress):
        return "affection"
    if distress:
        return "comfort"
    if "庆祝" in scenes:
        return "celebrate"
    if "gratitude" in intents or "感谢" in groups:
        return "gratitude"
    if ctx.get("playful") and not distress and _teasing_target(text):
        return "teasing"

    for group, intent in _GROUP_FALLBACK:
        if group in groups:
            return intent
    return None


def intent_debug(ctx):
    """日志用的一行摘要（不含原文）。"""
    intent = ctx.get("assistant_intent")
    if not intent:
        return "assistant_intent=none"
    return "assistant_intent=%s family=%s" % (intent, intent_family(intent) or "-")
