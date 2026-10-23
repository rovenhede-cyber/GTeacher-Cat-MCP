# -*- coding: utf-8 -*-
"""表情检索：拉库 -> 语境过滤 -> 打分 -> 稳定选择。

管线：
1. load_library()        从 GitHub 拉 instructions.json（TTL 缓存 / force_refresh 强刷）
2. apply_filters()       relationship / avoid_when / 持刀类语境 先剔除
3. score_item()          情绪组、关键词、动作意图、场景、强度区间分别计分
4. search_sticker()      普通场景走 rank；明确索图走「画面约束 + 请求情绪 + 排名」
5. 日志                  context_hash / detected_intensity / candidate_scores / matched_tags 等，
                         不记录原始文本

兼容的旧接口：search_sticker(..., sticker_id=, deterministic=)、load_library(force_refresh=, ttl_seconds=)、
refresh_library()、StickerNotFoundError、模块级 random / time（便于测试替换）。
"""
import os
import random
import re
import time

import requests
from dotenv import load_dotenv

import intent_engine
from emotion_engine import VISUAL_PATTERNS, EMOTION_LABELS
from fallback_engine import evaluate as fallback_evaluate
from fallback_engine import select_generic
from logger_config import logger
from sticker_config import CONFIG, RELATIONSHIPS
from taxonomy import (
    ASSISTANT_INTENTS,
    AVOID_TRIGGER_WORDS,
    DANGER_MARKERS,
    RELATIONSHIP_ALLOWED,
    group_of,
    item_groups,
)
from trigger_engine import gate_reason as should_send_sticker_reason
from trigger_engine import should_send_sticker

# 权重相关的 .env 读取已由 sticker_config 在创建 CONFIG 之前完成；
# 这里再读一次是为了 STICKER_REPO_URL / STICKER_IMAGE_BASE 等运行期变量。
load_dotenv()

DEFAULT_REPO_BASE = "https://raw.githubusercontent.com/rovenhede-cyber/stickersforGPT/main/"
CACHE_TTL_SECONDS = 300

# R5 三模式（值来自 sticker_config，可在 .env 里用 R5_INTENT_MODE 覆盖）
INTENT_MODES = ("off", "shadow", "auto")

_library_cache = None
_library_loaded_at = 0.0
_warned = set()

LABEL_TO_GROUP = {label: group for group, label in EMOTION_LABELS.items()}


def intent_mode():
    """每次现读 CONFIG，便于测试与热更新（不缓存到模块级）。"""
    mode = getattr(CONFIG, "intent_mode", "shadow")
    return mode if mode in INTENT_MODES else "shadow"


class StickerError(Exception):
    """表情服务的基类异常。"""


class StickerLibraryError(StickerError, requests.RequestException):
    """表情库拉取/解析失败。同时是 requests 异常，兼容旧调用方 except RequestException。"""


class StickerImageError(StickerError):
    """表情图片地址缺失、下载失败或为空。"""


class StickerNotFoundError(LookupError):
    """指定 sticker_id 不存在。"""


# ------------------------------------------------------------------ 配置
def repo_base():
    base = os.getenv("STICKER_REPO_URL") or DEFAULT_REPO_BASE
    return base.rstrip("/") + "/"


def library_url(bust=False):
    """图库地址。bust=True 时追加 ?v=<ts> 绕过 CDN 缓存（只给显式强刷用）。"""
    url = repo_base() + "instructions.json"
    if bust:
        # 用 time.time() 而不是 monotonic：monotonic 是进程内相对时间，
        # 每次重启都会归零，做缓存击穿键会撞车。
        url += "?v=%d" % int(time.time() * 1000)
    return url


def image_base():
    return (os.getenv("STICKER_IMAGE_BASE") or DEFAULT_REPO_BASE).rstrip("/") + "/"


# ------------------------------------------------------------------ 库加载
def reset_library_cache():
    global _library_cache, _library_loaded_at
    _library_cache = None
    _library_loaded_at = 0.0


def set_library(data):
    """注入已加载的库（测试或离线校验用）。"""
    global _library_cache, _library_loaded_at
    if isinstance(data, list):
        data = {"stickers": data}
    items = [normalize_item(x) for x in data.get("stickers", [])]
    # 人工标注写错（证据引用了不存在的文本）应当立刻暴露，而不是线上静默失效
    intent_engine.validate_overlay(intent_engine.load_overlay(), items, warn_orphans=False)
    _library_cache = {"version": data.get("version"), "stickers": items}
    _library_loaded_at = time.monotonic()
    logger.info("Sticker library injected: %d entries", len(items))
    return _library_cache


def normalize_item(item):
    """补齐可选字段的缺省值，不改动已有值。"""
    normalized = dict(item)
    for key in ("tags", "emotion", "use_when", "avoid_when", "action", "scene",
                "trigger_actions", "relationship"):
        value = normalized.get(key)
        normalized[key] = list(value) if isinstance(value, (list, tuple)) else []
    try:
        normalized["priority"] = int(normalized.get("priority", 5))
    except (TypeError, ValueError):
        normalized["priority"] = 5
    return normalized


def load_library(force=False, force_refresh=False, ttl_seconds=None):
    """返回图库。默认 TTL 缓存；force_refresh=True 立即重拉（并绕过 CDN 缓存）。"""
    global _library_cache, _library_loaded_at

    # 只有显式 force_refresh 才改 URL；旧参数 force 保持原样（不改 URL，避免影响旧调用方）
    refresh = bool(force_refresh)
    force = bool(force or refresh)
    ttl = CACHE_TTL_SECONDS if ttl_seconds is None else max(0, ttl_seconds)
    now = time.monotonic()

    if not force and _library_cache is not None and now - _library_loaded_at < ttl:
        logger.info(
            "sticker_index cache_hit=True index_version=%s count=%d",
            _library_cache.get("version", "unknown"), len(_library_cache["stickers"]),
        )
        return _library_cache

    url = library_url(bust=refresh)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        # 强刷失败时保留旧缓存：宁可继续用上一次成功加载的库，也不要让服务空转
        raise StickerLibraryError(
            "表情库拉取失败：%s（%s）。请检查网络或 STICKER_REPO_URL 配置。" % (url, exc)
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise StickerLibraryError("表情库不是合法 JSON：%s" % url) from exc

    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list) or not data["stickers"]:
        raise StickerLibraryError("表情库结构异常：缺少非空的 stickers 数组（%s）" % url)

    items = [normalize_item(x) for x in data["stickers"] if isinstance(x, dict)]
    missing_range = [x.get("id") for x in items if not x.get("intensity_range")]
    if missing_range:
        logger.warning(
            "以下图片缺少 intensity_range，强度项按中性/标题线索处理（不丢弃）：%s",
            ", ".join(str(x) for x in missing_range),
        )
    for item in items:
        _check_mood_strength(item)
    # 标注写坏（证据引用不存在 / JSON 损坏）要留 ERROR 日志，但不能拖垮整条选图链路：
    # 否则连 R5_INTENT_MODE=off 这个回滚开关也会跟着失效（加载图库时都会校验）。
    try:
        intent_engine.validate_overlay(intent_engine.load_overlay(), items)
    except intent_engine.OverlayError as exc:
        intent_engine.disable_overlay(str(exc))

    _library_cache = {"version": data.get("version"), "stickers": items}
    _library_loaded_at = now
    logger.info(
        "sticker_index_refreshed cache_hit=False index_version=%s count=%d",
        data.get("version", "unknown"), len(items),
    )
    return _library_cache


def refresh_library():
    """发布新图库后强制刷新。"""
    return load_library(force_refresh=True)


def _check_mood_strength(item):
    mood = item.get("mood_strength")
    rng = item.get("intensity_range")
    if mood is None or not rng or len(rng) != 2:
        return
    lo, hi = rng
    if not (lo <= mood <= hi):
        key = "mood:%s" % item.get("id")
        if key not in _warned:
            _warned.add(key)
            logger.warning(
                "mood_strength 与 intensity_range 不一致：%s mood_strength=%s, intensity_range=[%s,%s]"
                "（mood_strength 不参与打分，仅提示数据待修）",
                item.get("id"), mood, lo, hi,
            )


# ------------------------------------------------------------------ 过滤
def is_dangerous(item):
    text = " ".join(
        [str(item.get("name", "")), str(item.get("description", ""))]
        + [str(x) for x in item.get("tags", [])]
        + [str(x) for x in item.get("action", [])]
    )
    return any(marker in text for marker in DANGER_MARKERS)


def _active_avoid_words(ctx):
    words = set()
    for flag, triggers in AVOID_TRIGGER_WORDS.items():
        if ctx.get(flag):
            words.update(triggers)
    return words


def resolve_relationship(value=None):
    """未提供时使用 DEFAULT_RELATIONSHIP_CONTEXT（默认 intimate）。"""
    raw = (value or "").strip().lower()
    if not raw or raw == "default":
        return CONFIG.default_relationship
    if raw not in RELATIONSHIPS:
        logger.warning(
            "Unknown relationship %r, fallback to default %r", value, CONFIG.default_relationship
        )
        return CONFIG.default_relationship
    return raw


def apply_filters(items, ctx, relationship=None):
    """剔除不该出现的候选，返回 (kept, dropped)。"""
    kept = []
    dropped = []

    rel = resolve_relationship(relationship)
    allowed_rel = RELATIONSHIP_ALLOWED.get(rel, RELATIONSHIP_ALLOWED["unknown"])
    avoid_words = _active_avoid_words(ctx)
    risky_context = bool(
        ctx.get("crisis") or ctx.get("serious") or ctx.get("conflict")
        or ctx.get("fear") or ctx.get("strong_negative")
    )
    playful = bool(ctx.get("playful"))

    for item in items:
        if ctx.get("crisis"):
            dropped.append({"id": item.get("id"), "reason": "crisis"})
            continue

        declared = set(item.get("relationship") or [])
        if declared and not declared & allowed_rel:
            dropped.append({"id": item.get("id"), "reason": "relationship:%s" % rel})
            continue

        hit = None
        for condition in item.get("avoid_when", []):
            if any(word in condition for word in avoid_words):
                hit = condition
                break
        if hit:
            dropped.append({"id": item.get("id"), "reason": "avoid_when:%s" % hit})
            continue

        if is_dangerous(item) and (risky_context or not playful):
            dropped.append({"id": item.get("id"), "reason": "dangerous_context"})
            continue

        kept.append(item)

    if dropped:
        logger.info(
            "Filtered out %d/%d stickers（relationship=%s, risky=%s, playful=%s）",
            len(dropped), len(items), rel, risky_context, playful,
        )
    return kept, dropped


# ------------------------------------------------------------------ 强度
ANGRY_STRONG_RE = re.compile(r"暴怒|气死|炸毛|怒火中烧|激动生气")
ANGRY_MILD_RE = re.compile(r"轻微不满|小小抗议|气鼓鼓")
ANGRY_MID_RE = re.compile(r"恼火|火焰|怒气符号")


def intensity_bounds(item):
    """返回 (bounds, source)。legacy 图（没有 intensity_range）用标题线索兜底，绝不按 priority 猜。"""
    bounds = item.get("intensity_range")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        try:
            low, high = (float(v) for v in bounds)
            if 1 <= low <= high <= 10:
                return (low, high), "metadata"
        except (TypeError, ValueError):
            pass

    labels = {str(x) for x in item.get("emotion", [])}
    if "生气" in labels or any(group_of(x) == "生气" for x in labels):
        evidence = " ".join([str(item.get("description") or ""), " ".join(item.get("tags", []))])
        if ANGRY_STRONG_RE.search(evidence):
            return (8, 10), "caption_hint"
        if ANGRY_MILD_RE.search(evidence):
            return (1, 3), "caption_hint"
        if ANGRY_MID_RE.search(evidence):
            return (4, 7), "caption_hint"
    return None, "unknown"


def _intensity_score(item, intensity):
    bounds, source = intensity_bounds(item)
    if bounds is None or not intensity:
        return 0.0, None

    lo, hi = bounds
    if lo <= intensity <= hi:
        score = CONFIG.intensity_in_range - 0.5 * abs(intensity - (lo + hi) / 2.0)
        if source == "caption_hint":
            score += 3  # 标题线索与强度吻合时额外加分（legacy 图专用）
        return round(score, 3), None

    distance = lo - intensity if intensity < lo else intensity - hi
    if distance == 1:
        return CONFIG.intensity_near_edge, None
    return CONFIG.intensity_out_of_range + CONFIG.intensity_out_step * (distance - 2), None


# ------------------------------------------------------------------ 文本工具
def _values(item, field):
    value = item.get(field) or []
    if isinstance(value, str):
        value = [value]
    return {str(part).strip().lower() for part in value if str(part).strip()}


def _has_phrase(text, phrase, negated=None):
    phrase = (phrase or "").lower().strip()
    if not phrase or (negated and phrase in negated):
        return False
    if re.search(r"[a-z0-9]", phrase):
        pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    else:
        if len(phrase) < 2:
            return False
        pattern = re.escape(phrase)
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        prefix = text[max(0, match.start() - 8):match.start()]
        if not re.search(r"(?:不是(?:在)?|并非|没有|没在|不想|(?<!特)别|不要|不)$", prefix):
            return True
    return False


def visible_features(item):
    """图片里**确实可见**的元素，只认 action/描述/名称/标签里的证据。"""
    evidence = " ".join(str(item.get(field) or "") for field in
                        ("action", "description", "name", "tags"))
    return {feature for feature, patterns in VISUAL_PATTERNS.items()
            if any(re.search(p, evidence, flags=re.IGNORECASE) for p in patterns)}


def _action_aliases(action):
    from taxonomy import ACTION_PATTERNS

    return set(ACTION_PATTERNS.get(action, [action])) | {action}


INTENT_SCENES = {
    "comfort": {"安慰", "陪伴"},
    "celebrate": {"庆祝"},
    "affection": {"求婚", "亲密互动", "示爱"},
}
SCENE_BONUS = 6.0


# ------------------------------------------------------------------ 打分
def score_item(item, ctx):
    """单图打分。intensity_range 参与打分；mood_strength 不打分；priority 只作排序权重。

    意图项只在 auto 模式（或 shadow 的影子打分）里生效：
    - `_intent_active` 显式为 False -> 不算意图（off / 返回给调用方的 R4 结果）
    - 未提供该标记 -> 按 CONFIG.intent_mode 判断（直接调用 score_item 时用得上）
    """
    breakdown = {}
    warnings = []

    user_groups = list(dict.fromkeys(ctx.get("emotion") or []))
    keywords = [k.lower() for k in (ctx.get("keywords") or [])]
    actions = ctx.get("actions") or []
    scenes = ctx.get("scenes") or []
    intents = ctx.get("intent") or []
    intensity = (ctx.get("intensity") or 0) if user_groups else 0

    active = ctx.get("_intent_active")
    if active is None:
        active = intent_mode() == "auto"
    assistant_intent = ctx.get("assistant_intent") if active else None
    if assistant_intent not in ASSISTANT_INTENTS:
        assistant_intent = None

    tags = [str(x).lower() for x in item.get("tags", [])]
    name = str(item.get("name", "")).lower()
    description = str(item.get("description", "")).lower()
    use_when = [str(x).lower() for x in item.get("use_when", [])]
    item_scene = [str(x).lower() for x in item.get("scene", [])]
    trigger_actions = [str(x).lower() for x in item.get("trigger_actions", [])]
    displayed_actions = [str(x).lower() for x in item.get("action", [])]

    if user_groups:
        groups = item_groups(item)
        matched = [g for g in user_groups if g in groups]
        if matched:
            # 已知助手意图时，情绪匹配降权：意图比"用户情绪对上了"更接近"该发哪张"
            weight = CONFIG.emotion_when_intent if assistant_intent else CONFIG.emotion_group
            breakdown["emotion_group"] = round(
                weight * len(matched[: CONFIG.max_emotion_groups]), 4)

    if keywords:
        tag_hits = [k for k in keywords if k in tags]
        if tag_hits:
            breakdown["tag_hit"] = CONFIG.tag_hit * len(tag_hits)
        if any(k in name for k in keywords):
            breakdown["name_hit"] = CONFIG.name_hit
        if any(k in description for k in keywords):
            breakdown["description_hit"] = CONFIG.description_hit
        if any(k in s for k in keywords for s in use_when + item_scene):
            breakdown["use_when_hit"] = CONFIG.use_when_hit

    if actions:
        trigger_hit = False
        for action in actions:
            if _action_aliases(action) & set(trigger_actions):
                trigger_hit = True
                break
        if trigger_hit:
            breakdown["trigger_action"] = CONFIG.trigger_action
        elif not trigger_actions:
            for action in actions:
                aliases = _action_aliases(action)
                if any(alias in text for alias in aliases for text in displayed_actions) \
                        or aliases & set(tags):
                    breakdown["action_fallback"] = CONFIG.action_fallback
                    warnings.append("trigger_actions missing, used action/tag fallback: %s" % item.get("id"))
                    break

    scene_hits = [s for s in scenes if s.lower() in item_scene]
    if scene_hits:
        breakdown["scene_hit"] = SCENE_BONUS
    if not assistant_intent:
        # R4 的 intent_scene 是"场景≈意图"的代理分。R5 已知真实意图时不再叠加，
        # 否则同一个信号（scene=安慰）会被计两次，压过真正的行为匹配。
        for intent in intents:
            if set(item_scene) & INTENT_SCENES.get(intent, set()):
                breakdown["intent_scene"] = round(SCENE_BONUS / 2, 3)
                break

    if assistant_intent:
        behavior = intent_engine.behaviors_for(item)
        behaviors = set(behavior["behaviors"])
        if assistant_intent in behaviors:
            breakdown["intent_exact"] = CONFIG.intent_exact
        elif behaviors & intent_engine.family_behaviors(assistant_intent):
            breakdown["intent_family"] = CONFIG.intent_family
        if behaviors & intent_engine.conflicting(assistant_intent):
            breakdown["intent_conflict"] = CONFIG.intent_conflict
        if behavior["persona_fit"] == "assistant":
            breakdown["intent_persona"] = CONFIG.intent_persona

    value, warning = _intensity_score(item, intensity)
    if value:
        breakdown["intensity"] = round(value, 3)
    if not item.get("intensity_range"):
        warnings.append("missing intensity_range: %s" % item.get("id"))
    if warning:
        warnings.append(warning)

    breakdown["priority"] = round(item.get("priority", 5) * CONFIG.priority_weight, 3)

    score = round(sum(breakdown.values()), 4)
    semantic = round(score - breakdown.get("priority", 0.0), 4)
    return {
        "id": item.get("id"),
        "item": item,
        "score": score,
        "semantic_score": semantic,
        "breakdown": breakdown,
        "warnings": warnings,
    }


def _lexical_overlap(item, query):
    """请求词与图片元数据的字面重合度（仅用于明确索图的兜底排序）。"""
    query = (query or "").lower()
    if not query:
        return 0
    score = 0
    for phrase in _values(item, "action"):
        if len(phrase) >= 2 and phrase in query:
            score += 3
    for phrase in _values(item, "tags"):
        if len(phrase) >= 2 and phrase in query:
            score += 1
    name = str(item.get("name") or "").lower()
    for phrase in _values(item, "action") | _values(item, "tags"):
        if len(phrase) >= 2 and phrase in name:
            score += 1
    return score


def _rank(ctx, items):
    scored = [score_item(item, ctx) for item in items]
    scored = [
        row for row in scored
        if row["score"] >= CONFIG.min_score and row["semantic_score"] >= CONFIG.min_match_score
    ]
    scored.sort(key=lambda r: (-r["score"], -r["item"].get("priority", 5), str(r["id"])))
    return scored


def rank_stickers(ctx, items=None, relationship="default"):
    """过滤 + 排序，便于排查「为什么选了这张」。"""
    if items is None:
        items = load_library()["stickers"]
    kept, _ = apply_filters(items, ctx, relationship=relationship)
    return _rank(ctx, kept)


# ------------------------------------------------------------------ 明确索图
def _select_explicit(ctx, items, deterministic=True, trace=None):
    raw_text = str(ctx.get("sticker_query") or ctx.get("original_text") or "").lower()

    def fail(reason):
        if trace is not None:
            trace["reason"] = reason
        return None

    # 1) 用户点名某张图
    named = [item for item in items
             if item.get("name") and _has_phrase(raw_text, str(item["name"]).lower())]
    if named:
        selected = max(named, key=lambda i: (len(str(i["name"])), i.get("priority", 5)))
        logger.info("sticker_selected mode=explicit_name selected_sticker_id=%s", selected.get("id"))
        if trace is not None:
            trace["reason"] = "explicit_name"
        return selected

    features = set(ctx.get("requested_visual_features") or [])
    requested = [LABEL_TO_GROUP.get(label, label) for label in ctx.get("requested_sticker_emotion") or []]

    # 信号检查必须排在打分之前：auto 模式下意图加分本身会产生非零分，
    # 如果放到 _rank 之后再判断，“零用户信号的索图”就会被意图分撑起来，
    # 变成为了发图而发图。用户侧没有任何信号时，一律不猜。
    if not (requested or features or ctx.get("actions") or ctx.get("keywords")):
        logger.info("sticker_candidates count=0 reason=no_request_signal")
        return fail("no_request_signal")

    pool = items
    if features:
        pool = [item for item in pool if features.issubset(visible_features(item))]
        if not pool:
            logger.info("sticker_candidates count=0 reason=visual_feature_unavailable")
            return fail("visual_feature_unavailable")
        logger.info("sticker_filter stage=visual filtered_candidates=%s", [i.get("id") for i in pool])

    if requested:
        matching = [item for item in pool if item_groups(item) & set(requested)]
        if matching:
            pool = matching
            logger.info("sticker_filter stage=emotion filtered_candidates=%s", [i.get("id") for i in pool])
        elif not features:
            logger.info("sticker_candidates count=0 reason=requested_emotion_unavailable")
            return fail("requested_emotion_unavailable")

    ranked = _rank(ctx, pool)
    if not ranked:
        query = str(ctx.get("sticker_query") or "")
        scored = [score_item(item, ctx) for item in pool]
        scored = [r for r in scored if r["score"] > CONFIG.min_score]
        scored.sort(key=lambda r: (-r["score"], -r["item"].get("priority", 5), str(r["id"])))
        if not scored or all(r["semantic_score"] <= 0 for r in scored):
            # 特征/情绪已经过滤过，但没有任何语义加分（只剩 priority）时，
            # 按请求词与元数据的字面重合度排序，避免“谁的 priority 高就选谁”
            scored = sorted(
                (score_item(item, ctx) for item in pool),
                key=lambda r: (-_lexical_overlap(r["item"], query),
                               -r["item"].get("priority", 5), str(r["id"])),
            )
        ranked = scored
    if not ranked:
        logger.info("sticker_candidates count=0 fallback_reason=no_semantic_match")
        return fail("no_semantic_match")

    top = ranked[0]
    close = [r for r in ranked
             if r["breakdown"].keys() == top["breakdown"].keys() and top["score"] - r["score"] <= 1]
    if len(close) > 1 and not deterministic:
        selected = random.choice([r["item"] for r in close])
    else:
        selected = top["item"]

    logger.info(
        "sticker_candidates candidate_scores=%s",
        [(r["id"], r["score"], r["breakdown"].get("intensity"), intensity_bounds(r["item"])[1])
         for r in ranked[:5]],
    )
    if trace is not None:
        trace["reason"] = "selected"
    return selected


# ------------------------------------------------------------------ 选择
def _exact_pick(items, ctx, sticker_id):
    """按 id 精确选图。仍受危机 / 关系 / avoid_when 约束（R5 安全不变式 I4）。"""
    item = next((x for x in items if x.get("id") == sticker_id), None)
    if item is None:
        logger.warning("sticker_id_not_found id=%s", sticker_id)
        raise StickerNotFoundError("未找到指定表情包 ID：%s" % sticker_id)

    if ctx.get("crisis"):
        logger.info("sticker_id_blocked id=%s reason=crisis", sticker_id)
        return None

    rel = ctx.get("relationship") or resolve_relationship(None)
    allowed = RELATIONSHIP_ALLOWED.get(rel, RELATIONSHIP_ALLOWED["unknown"])
    declared = set(item.get("relationship") or [])
    if declared and not declared & allowed:
        logger.info("sticker_id_blocked id=%s reason=relationship:%s", sticker_id, rel)
        return None

    avoid_words = _active_avoid_words(ctx)
    hit = next((condition for condition in item.get("avoid_when", [])
                if any(word in condition for word in avoid_words)), None)
    if hit:
        logger.info("sticker_id_blocked id=%s reason=avoid_when:%s", sticker_id, hit)
        return None

    logger.info("sticker_selected mode=exact selected_sticker_id=%s", sticker_id)
    return item


def _ranked_pick(ctx, items, deterministic, trace=None):
    ranked = _rank(ctx, items)
    if not ranked:
        if trace is not None:
            trace["reason"] = "no_semantic_match"
        return None, []
    top = ranked[0]
    close = [r for r in ranked
             if r["breakdown"].keys() == top["breakdown"].keys() and top["score"] - r["score"] <= 1]
    selected = (random.choice([r["item"] for r in close])
                if len(close) > 1 and not deterministic else top["item"])
    if trace is not None:
        trace["reason"] = "selected"
    return selected, ranked


def _choose(ctx, kept, deterministic, trace=None):
    """在**已经过滤过**的候选里选一张（意图只能在这里起作用）。"""
    if ctx.get("_intent_active") and ctx.get("assistant_intent") == "apology":
        pool = [x for x in kept if "apology" in intent_engine.behaviors_for(x)["behaviors"]]
        if not pool:
            # 图库确实没有合格的道歉图：返回 None，绝不拿感谢/安慰图顶替
            logger.info("r5_fallback fallback_reason=apology_no_candidate")
            if trace is not None:
                trace["reason"] = "apology_no_candidate"
            return None
        # 人工标注本身就是最强证据：候选池已由标注决定，语义分不足以筛选时按 priority 定序
        if not _rank(ctx, pool):
            logger.info("r5_fallback fallback_reason=apology_pool_priority_only")
            if trace is not None:
                trace["reason"] = "selected"
            return sorted(pool, key=lambda i: (-i.get("priority", 5), str(i.get("id"))))[0]
        kept = pool

    if ctx.get("explicit_sticker_request"):
        return _select_explicit(ctx, kept, deterministic=deterministic, trace=trace)
    selected, _ranked = _ranked_pick(ctx, kept, deterministic, trace=trace)
    return selected


# ------------------------------------------------------------------ 弱信号兜底（R7.1）
def _generic_fallback_decision(ctx, kept):
    """兜底判定（纯函数，不写日志、不改 ctx）。"""
    eligible, reason = fallback_evaluate(ctx)
    if not eligible:
        return {"eligible": False, "reason": None, "block_reason": reason,
                "item": None, "rank": None, "skipped": []}
    item, detail = select_generic(kept)
    if item is None:
        return {"eligible": True, "reason": reason, "block_reason": "no_generic_candidate",
                "item": None, "rank": None, "skipped": detail.get("skipped", [])}
    return {"eligible": True, "reason": reason, "block_reason": None,
            "item": item, "rank": detail.get("rank"), "skipped": detail.get("skipped", [])}


def _trace_fallback(trace, decision):
    """trace 只做诊断，不参与任何判定。"""
    if trace is None:
        return
    trace["fallback_eligible"] = decision["eligible"]
    trace["fallback_reason"] = decision["reason"]
    trace["fallback_block_reason"] = decision["block_reason"]
    trace["fallback_selected_id"] = (
        decision["item"].get("id") if decision["item"] is not None else None)


def _apply_generic_fallback(ctx, kept, mode, trace):
    """`_choose` 返回 None 之后的兜底。

    只有 auto 会改变返回值：off 是 R4 回滚开关（不评估），shadow 只记录"如果开 auto
    会发哪张"，返回仍然是 None —— 保证 shadow 与 off 对外结果一致。
    候选池 kept 已经过 apply_filters，所以危机/关系/avoid_when/危险图全部先生效。
    """
    if mode == "off":
        return None

    decision = _generic_fallback_decision(ctx, kept)
    _trace_fallback(trace, decision)
    item = decision["item"]
    selected_id = item.get("id") if item is not None else None

    if mode == "shadow":
        logger.info(
            "r71_shadow r71_would_select=%s fallback_eligible=%s fallback_reason=%s "
            "fallback_block_reason=%s context_hash=%s",
            selected_id, decision["eligible"], decision["reason"],
            decision["block_reason"], ctx.get("context_hash", ""),
        )
        return None

    logger.info(
        "r71_fallback fallback_eligible=%s fallback_reason=%s fallback_selected_id=%s "
        "fallback_rank=%s fallback_block_reason=%s skipped=%s signal_count=%s "
        "relationship=%s r5_mode=%s context_hash=%s",
        decision["eligible"], decision["reason"], selected_id, decision["rank"],
        decision["block_reason"], decision["skipped"], ctx.get("signal_count"),
        ctx.get("relationship"), mode, ctx.get("context_hash", ""),
    )

    if item is None:
        if decision["block_reason"] == "no_generic_candidate" and trace is not None:
            # 用户确实要图、也确实没有安全通用图：把原因说清楚，不要含糊成“没识别到情绪”
            trace["reason"] = "no_generic_candidate"
        return None
    if trace is not None:
        trace["reason"] = "generic_fallback"
    return item


def choose_with_fallback(ctx, kept, mode=None, deterministic=True, trace=None):
    """正常选择 + 弱信号兜底。search_sticker 与诊断工具共用同一条链路。"""
    mode = intent_mode() if mode is None else mode
    ctx["_intent_active"] = mode == "auto"
    selected = _choose(ctx, kept, deterministic=deterministic, trace=trace)
    if selected is None:
        selected = _apply_generic_fallback(ctx, kept, mode=mode, trace=trace)
    return selected


def _log_selection(ctx, item, score, matched_tags, candidates=None, index_version="unknown"):
    logger.info(
        "sticker_selected selected_sticker_id=%s score=%.2f matched_tags=%s candidate_scores=%s "
        "detected_intensity=%s index_version=%s context_hash=%s",
        item.get("id") if item else None, score, matched_tags,
        candidates or [], ctx.get("intensity"), index_version, ctx.get("context_hash", ""),
    )


def search_sticker(context, sticker_id=None, *, deterministic=True, relationship=None, trace=None):
    """选图。context 可以是 analyze_context 的结果，也可以是原始文本。

    秩序不可颠倒：闸门 -> 过滤 -> 打分 -> （意图）-> 选择。
    意图只在 `auto` 模式下参与打分；`shadow` 只把 R5 结果写进日志。

    trace：可选 dict，回填 {"reason": ...} 供调用方区分“闸门拦住 / 没有信号 /
    没有匹配 / 正常选中”，不参与任何判定，也不改变返回值。
    """
    from emotion_engine import analyze_context

    ctx = analyze_context(context) if isinstance(context, str) else dict(context or {})
    ctx["relationship"] = resolve_relationship(relationship)

    # 输入侧体检：只记长度与信号量，绝不记原文
    logger.info(
        "r5_input input_len=%d signal_count=%d explicit_request=%s context_hash=%s",
        len(str(ctx.get("original_text") or "")), int(ctx.get("signal_count") or 0),
        bool(ctx.get("explicit_sticker_request")), ctx.get("context_hash", ""),
    )

    mode = intent_mode()
    data = load_library()
    items = data["stickers"]

    if mode == "off":
        # 回滚开关：完全不看意图，与 R4 逐条一致
        ctx.pop("assistant_intent", None)
        ctx["intent_source"] = "off"
    else:
        explicit = intent_engine.normalize_intent(ctx.get("assistant_intent"))
        if explicit:
            ctx["assistant_intent"] = explicit
            ctx["intent_source"] = ctx.get("intent_source") or "explicit"
        else:
            derived = intent_engine.derive_intent(ctx)
            ctx["assistant_intent"] = derived
            ctx["intent_source"] = "derived" if derived else "none"

    if sticker_id:
        picked = _exact_pick(items, ctx, sticker_id)
        if trace is not None:
            trace["reason"] = "selected" if picked is not None else "blocked_by_safety"
        return picked

    triggered, reason = should_send_sticker_reason(ctx)
    if not triggered:
        logger.info(
            "trigger_result triggered=False gate_reason=%s context_hash=%s",
            reason, ctx.get("context_hash", ""),
        )
        if trace is not None:
            trace["reason"] = "gate:" + reason
        return None

    kept, _dropped = apply_filters(items, ctx, relationship=ctx["relationship"])

    # 返回给调用方的那一份：只有 auto 才启用意图打分（兜底同样只在 auto 生效）
    selected = choose_with_fallback(
        ctx, kept, mode=mode, deterministic=deterministic, trace=trace)

    if mode == "shadow":
        # 影子打分：算一遍"如果开 auto 会选谁"，只写日志，绝不改变返回值
        shadow_ctx = dict(ctx)
        shadow_ctx["_intent_active"] = True
        shadow = _choose(shadow_ctx, kept, deterministic=deterministic)
        changed = (shadow.get("id") if shadow else None) != (selected.get("id") if selected else None)
        logger.info(
            "r5_shadow r5_mode=shadow r5_shadow_intent=%s intent_source=%s "
            "r5_shadow_id=%s r4_selected_id=%s r5_shadow_would_change=%s context_hash=%s",
            ctx.get("assistant_intent") or "none", ctx.get("intent_source"),
            shadow.get("id") if shadow else None,
            selected.get("id") if selected else None,
            changed, ctx.get("context_hash", ""),
        )

    if selected is None:
        logger.info("r5_decision r5_mode=%s assistant_intent=%s intent_source=%s "
                    "selected_sticker_id=None reason=%s context_hash=%s",
                    mode, ctx.get("assistant_intent") or "none", ctx.get("intent_source"),
                    (trace or {}).get("reason", "unknown"), ctx.get("context_hash", ""))
        return None

    behavior = intent_engine.behaviors_for(selected)
    matched = sorted(t for t in _values(selected, "tags")
                     if _has_phrase(str(ctx.get("sticker_query") or ctx.get("original_text") or "").lower(), t))
    ranked_all = _rank(ctx, kept)
    candidates = [(r["id"], r["score"]) for r in ranked_all[:5]]
    score = next((r["score"] for r in ranked_all if r["id"] == selected.get("id")), 0.0)
    logger.info(
        "r5_decision r5_mode=%s assistant_intent=%s intent_source=%s behavior_source=%s "
        "selected_sticker_id=%s context_hash=%s",
        mode, ctx.get("assistant_intent") or "none", ctx.get("intent_source"),
        behavior["source"], selected.get("id"), ctx.get("context_hash", ""),
    )
    _log_selection(ctx, selected, score, matched, candidates, data.get("version", "unknown"))
    return selected


def select_sticker(context, relationship=None, library=None, trace=None):
    """R3 旧名字，保留。library 参数仅用于测试注入。"""
    if library is not None:
        set_library(library)
    return search_sticker(context, relationship=relationship, trace=trace)


# ------------------------------------------------------------------ 图片
def build_image_url(file_path):
    if not file_path or not isinstance(file_path, str):
        raise StickerImageError("图片路径缺失，无法拼接下载地址")
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    return image_base() + file_path.lstrip("/")


def fetch_image(file_path):
    url = build_image_url(file_path)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise StickerImageError("猫猫图片读取失败：%s（%s）" % (url, exc)) from exc

    content = response.content
    if not content:
        raise StickerImageError("猫猫图片为空：%s" % url)
    return content
