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

from emotion_engine import VISUAL_PATTERNS, EMOTION_LABELS
from logger_config import logger
from sticker_config import CONFIG, RELATIONSHIPS
from taxonomy import (
    AVOID_TRIGGER_WORDS,
    DANGER_MARKERS,
    RELATIONSHIP_ALLOWED,
    group_of,
    item_groups,
)
from trigger_engine import should_send_sticker

# 权重相关的 .env 读取已由 sticker_config 在创建 CONFIG 之前完成；
# 这里再读一次是为了 STICKER_REPO_URL / STICKER_IMAGE_BASE 等运行期变量。
load_dotenv()

DEFAULT_REPO_BASE = "https://raw.githubusercontent.com/rovenhede-cyber/stickersforGPT/main/"
CACHE_TTL_SECONDS = 300

_library_cache = None
_library_loaded_at = 0.0
_warned = set()

LABEL_TO_GROUP = {label: group for group, label in EMOTION_LABELS.items()}


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


def library_url():
    return repo_base() + "instructions.json"


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
    """返回图库。默认 TTL 缓存；force_refresh=True 立即重拉。"""
    global _library_cache, _library_loaded_at

    force = bool(force or force_refresh)
    ttl = CACHE_TTL_SECONDS if ttl_seconds is None else max(0, ttl_seconds)
    now = time.monotonic()

    if not force and _library_cache is not None and now - _library_loaded_at < ttl:
        logger.info(
            "sticker_index cache_hit=True index_version=%s count=%d",
            _library_cache.get("version", "unknown"), len(_library_cache["stickers"]),
        )
        return _library_cache

    url = library_url()
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
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
    """单图打分。intensity_range 参与打分；mood_strength 不打分；priority 只作排序权重。"""
    breakdown = {}
    warnings = []

    user_groups = list(dict.fromkeys(ctx.get("emotion") or []))
    keywords = [k.lower() for k in (ctx.get("keywords") or [])]
    actions = ctx.get("actions") or []
    scenes = ctx.get("scenes") or []
    intents = ctx.get("intent") or []
    intensity = (ctx.get("intensity") or 0) if user_groups else 0

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
            breakdown["emotion_group"] = CONFIG.emotion_group * len(matched[: CONFIG.max_emotion_groups])

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
    for intent in intents:
        if set(item_scene) & INTENT_SCENES.get(intent, set()):
            breakdown["intent_scene"] = round(SCENE_BONUS / 2, 3)
            break

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
def _select_explicit(ctx, items, deterministic=True):
    raw_text = str(ctx.get("sticker_query") or ctx.get("original_text") or "").lower()

    # 1) 用户点名某张图
    named = [item for item in items
             if item.get("name") and _has_phrase(raw_text, str(item["name"]).lower())]
    if named:
        selected = max(named, key=lambda i: (len(str(i["name"])), i.get("priority", 5)))
        logger.info("sticker_selected mode=explicit_name selected_sticker_id=%s", selected.get("id"))
        return selected

    features = set(ctx.get("requested_visual_features") or [])
    requested = [LABEL_TO_GROUP.get(label, label) for label in ctx.get("requested_sticker_emotion") or []]

    pool = items
    if features:
        pool = [item for item in pool if features.issubset(visible_features(item))]
        if not pool:
            logger.info("sticker_candidates count=0 reason=visual_feature_unavailable")
            return None
        logger.info("sticker_filter stage=visual filtered_candidates=%s", [i.get("id") for i in pool])

    if requested:
        matching = [item for item in pool if item_groups(item) & set(requested)]
        if matching:
            pool = matching
            logger.info("sticker_filter stage=emotion filtered_candidates=%s", [i.get("id") for i in pool])
        elif not features:
            logger.info("sticker_candidates count=0 reason=requested_emotion_unavailable")
            return None

    ranked = _rank(ctx, pool)
    if not ranked:
        # 没有任何可识别信号（无请求情绪/无画面约束/无动作/无关键词）时，
        # 不能退化成"按 priority 给一张"——直接返回 None。
        has_signal = bool(requested or features or ctx.get("actions") or ctx.get("keywords"))
        if not has_signal:
            logger.info("sticker_candidates count=0 reason=no_request_signal")
            return None
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
        return None

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
    return selected


# ------------------------------------------------------------------ 选择
def _log_selection(ctx, item, score, matched_tags, candidates=None, index_version="unknown"):
    logger.info(
        "sticker_selected selected_sticker_id=%s score=%.2f matched_tags=%s candidate_scores=%s "
        "detected_intensity=%s index_version=%s context_hash=%s",
        item.get("id") if item else None, score, matched_tags,
        candidates or [], ctx.get("intensity"), index_version, ctx.get("context_hash", ""),
    )


def search_sticker(context, sticker_id=None, *, deterministic=True, relationship=None):
    """选图。context 可以是 analyze_context 的结果，也可以是原始文本。"""
    from emotion_engine import analyze_context

    ctx = analyze_context(context) if isinstance(context, str) else dict(context or {})
    ctx["relationship"] = resolve_relationship(relationship)

    data = load_library()
    items = data["stickers"]

    if sticker_id:
        for item in items:
            if item.get("id") == sticker_id:
                logger.info("sticker_selected mode=exact selected_sticker_id=%s", sticker_id)
                return item
        logger.warning("sticker_id_not_found id=%s", sticker_id)
        raise StickerNotFoundError("未找到指定表情包 ID：%s" % sticker_id)

    if not should_send_sticker(ctx):
        logger.info("trigger_result triggered=False context_hash=%s", ctx.get("context_hash", ""))
        return None

    kept, _dropped = apply_filters(items, ctx, relationship=ctx["relationship"])

    if ctx.get("explicit_sticker_request"):
        selected = _select_explicit(ctx, kept, deterministic=deterministic)
    else:
        ranked = _rank(ctx, kept)
        if not ranked:
            logger.info(
                "sticker_candidates count=0 fallback_reason=no_semantic_match context_hash=%s",
                ctx.get("context_hash", ""),
            )
            return None
        top = ranked[0]
        close = [r for r in ranked
                 if r["breakdown"].keys() == top["breakdown"].keys() and top["score"] - r["score"] <= 1]
        selected = (random.choice([r["item"] for r in close])
                    if len(close) > 1 and not deterministic else top["item"])
        _log_selection._last_candidates = [(r["id"], r["score"]) for r in ranked[:5]]

    if selected is None:
        return None

    matched = sorted(t for t in _values(selected, "tags")
                     if _has_phrase(str(ctx.get("sticker_query") or ctx.get("original_text") or "").lower(), t))
    ranked_all = _rank(ctx, kept)
    candidates = [(r["id"], r["score"]) for r in ranked_all[:5]]
    score = next((r["score"] for r in ranked_all if r["id"] == selected.get("id")), 0.0)
    _log_selection(ctx, selected, score, matched, candidates, data.get("version", "unknown"))
    return selected


def select_sticker(context, relationship=None, library=None):
    """R3 旧名字，保留。library 参数仅用于测试注入。"""
    if library is not None:
        set_library(library)
    return search_sticker(context, relationship=relationship)


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
