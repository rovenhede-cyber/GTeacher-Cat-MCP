# -*- coding: utf-8 -*-
"""GTeacher Cat MCP 服务入口。

tool: send_cat_companion(user_emotional_context, sticker_id=None,
                        explicit_request=False, relationship_context="",
                        assistant_response_intent=None)

- explicit_request=True：客户端已确认这是“用户点名要表情包”，闸门不再按自动陪伴规则判断。
- sticker_id：直接指定某张图（旧接口，保留；仍受危机/关系/avoid_when 约束）。
- relationship_context：不传时用 DEFAULT_RELATIONSHIP_CONTEXT（默认 intimate）。
- assistant_response_intent：R5 新增，可选。助手这条回复想做什么（10 类之一）。
"""
import base64
from typing import Optional

import requests
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ImageContent, TextContent

from emotion_engine import analyze_context
from intent_engine import normalize_intent
from logger_config import logger
from sticker_config import CONFIG
from sticker_engine import (
    StickerImageError,
    StickerLibraryError,
    StickerNotFoundError,
    build_image_url,
    fetch_image,
    intent_mode,
    search_sticker,
    select_sticker,
)
from taxonomy import ASSISTANT_INTENTS
from trigger_engine import gate_reason as should_send_sticker_reason
from trigger_engine import should_send_sticker

mcp = MCPServer("GTeacher Cat")

RELATIONSHIP_ALIASES = {
    "": "default",
    "default": "default",
    "unknown": "unknown",
    "none": "unknown",
    "intimate": "intimate",
    "亲密": "intimate",
    "情侣": "intimate",
    "couple": "intimate",
    "friend": "friend",
    "朋友": "friend",
    "formal": "formal",
    "正式": "formal",
    "工作": "formal",
}


def normalize_relationship(value):
    """未显式传入时返回 DEFAULT_RELATIONSHIP_CONTEXT（默认 intimate）。"""
    key = (value or "").strip().lower()
    mapped = RELATIONSHIP_ALIASES.get(key)
    if mapped == "default":
        return CONFIG.default_relationship
    if mapped:
        return mapped
    logger.warning(
        "Unknown relationship_context %r, fallback to default %r",
        value, CONFIG.default_relationship,
    )
    return CONFIG.default_relationship


def _text(message):
    return TextContent(type="text", text=message)


# 选不出图时的原因 -> 对外文案。保留“没有找到合适猫猫”前缀（旧客户端可能按它判断），
# 后面补一句人/模型都能看懂的原因，便于定位到底是图库缺图还是输入缺信号。
_NO_MATCH_HINTS = {
    "no_request_signal": "没识别到具体情绪或画面要求，换个说法或补一句现在的心情",
    "requested_emotion_unavailable": "图库里没有这个情绪的表情",
    "visual_feature_unavailable": "图库里没有符合这个画面的表情",
    "no_semantic_match": "候选都不够贴合",
    "apology_no_candidate": "图库里没有合适的道歉图",
    "no_generic_candidate": "图库里没有适合直接发送的通用图片",
    "blocked_by_safety": "这张图在当前语境下不适合发送",
}


def _no_match_text(reason):
    hint = _NO_MATCH_HINTS.get(reason)
    if hint:
        return "没有找到合适猫猫（%s）" % hint
    return "没有找到合适猫猫"


@mcp.tool()
def send_cat_companion(
    user_emotional_context: str = "",
    sticker_id: Optional[str] = None,
    explicit_request: bool = False,
    relationship_context: str = "",
    assistant_response_intent: Optional[str] = None,
):
    """
    Use this tool when the user explicitly asks for a cat sticker, even if
    ordinary emotion-based auto-send rules would not trigger. Pass the user's
    actual wording in user_emotional_context. If they identify a known sticker,
    pass sticker_id to send that exact image.

    Also use this tool to send a cat companion reaction when the user may benefit
    from emotional support or celebration.

    Use this tool when the user:
    - asks for a cat sticker of a specific emotion or look
    - expresses sadness, frustration, disappointment, or needs comfort
    - celebrates achievements or shares exciting news
    - expresses gratitude, affection, or wants emotional companionship

    Do not automatically use this tool for the following unless the user
    explicitly requests a sticker:
    - academic questions
    - technical explanations
    - coding problems
    - factual information requests
    - crisis or self-harm situations (reply as a human instead)

    relationship_context is optional and must NOT be guessed from the text.
    Leave it empty to use the server default (DEFAULT_RELATIONSHIP_CONTEXT,
    default "intimate"). Override explicitly with "friend" / "formal" / "unknown".

    assistant_response_intent is optional and must be decided by YOU, the caller:
    what is this reply of yours trying to express? Allowed values:
    comfort / accompany / encourage / celebrate / gratitude / affection /
    apology / teasing / agree / acknowledge. The server cannot see the
    conversation, and it cannot read the reply you are about to send; it only
    sees the strings you pass in. An invalid value is logged and ignored, and
    the intent is then derived from user_emotional_context instead.

    Safety: this intent never bypasses the send gate. Crisis, technical tasks,
    relationship context and avoid_when filters are always applied first, so an
    intent can only choose among the stickers that are already allowed.
    """

    relationship = normalize_relationship(relationship_context)
    mode = intent_mode()

    raw_context = str(user_emotional_context or "")
    if not raw_context.strip() and not sticker_id:
        # 客户端没把用户原话传进来：这不是“场景不需要发图”，而是输入缺失。
        # 必须在日志与返回里区分开，否则会被误读成闸门/选图缺陷。
        logger.warning(
            "r5_input_empty hit=True explicit_request=%s exact_id=False intent=%s relationship=%s",
            bool(explicit_request), assistant_response_intent or "none", relationship,
        )
        return _text(
            "没有收到用户原话（user_emotional_context 为空），本次不发表情包。"
            "请把用户刚说的那句话原文传进来。"
        )

    raw_intent = assistant_response_intent
    intent = normalize_intent(raw_intent)
    if raw_intent not in (None, "") and intent is None:
        logger.warning(
            "Unknown assistant_response_intent %r, fallback to derived intent", raw_intent
        )

    analysis = analyze_context(user_emotional_context, explicit_request=bool(explicit_request))
    analysis["relationship"] = relationship
    if mode != "off" and intent:
        analysis["assistant_intent"] = intent
        analysis["intent_source"] = "explicit"

    gate_triggered, gate = should_send_sticker_reason(analysis)
    triggered = bool(sticker_id) or gate_triggered

    logger.info(
        "trigger_result triggered=%s gate_reason=%s signal_count=%s exact_id=%s "
        "explicit_request=%s context_hash=%s "
        "detected_intent=%s user_emotion=%s requested_emotion=%s detected_intensity=%s "
        "actions=%s scenes=%s relationship=%s r5_mode=%s assistant_response_intent=%s "
        "intent_source=%s",
        triggered, gate, analysis.get("signal_count"),
        bool(sticker_id), analysis["explicit_sticker_request"],
        analysis["context_hash"], analysis["intent"], analysis["user_emotion"],
        analysis["requested_sticker_emotion"], analysis["intensity"],
        analysis["actions"], analysis["scenes"], relationship, mode,
        intent or "none", analysis.get("intent_source", "none"),
    )

    if not triggered:
        if gate == "no_signal":
            return _text(
                "当前场景不需要发送猫猫"
                "（未识别到情绪/动作/场景信号，请确认 user_emotional_context 传的是用户原话）"
            )
        return _text("当前场景不需要发送猫猫")

    trace = {}
    try:
        if sticker_id:
            result = search_sticker(analysis, sticker_id=sticker_id,
                                    relationship=relationship, trace=trace)
        else:
            result = select_sticker(analysis, relationship=relationship, trace=trace)
    except StickerNotFoundError as exc:
        return _text(str(exc))
    except StickerLibraryError as exc:
        logger.error("Sticker library unavailable: %s", exc)
        return _text("表情库暂时不可用，本次跳过猫猫：%s" % exc)
    except requests.RequestException as exc:
        logger.error("Sticker index failed: %s", exc)
        return _text("猫猫图库加载失败，请稍后重试。")

    if result is None:
        reason = trace.get("reason", "unknown")
        logger.info(
            "r5_outcome result=none reason=%s r5_mode=%s assistant_intent=%s "
            "signal_count=%s context_hash=%s",
            reason, mode, analysis.get("assistant_intent") or "none",
            analysis.get("signal_count"), analysis.get("context_hash", ""),
        )
        return _text(_no_match_text(reason))

    file_path = result.get("file")
    if not file_path:
        logger.error("Sticker %s has no file field", result.get("id"))
        return _text("猫猫图片路径缺失（id=%s）" % result.get("id", "?"))

    url = build_image_url(file_path)
    description = (
        "猫猫名称：%s\n描述：%s\n图片地址：%s"
        % (result["name"], result["description"], url)
    )

    try:
        content = fetch_image(file_path)
    except StickerImageError as exc:
        logger.warning("image_download_failed sticker_id=%s reason=%s", result.get("id"), exc)
        return _text("%s\n（图片下载失败，请稍后再试）" % description)

    ext = file_path.lower().rsplit(".", 1)[-1]
    mime_type = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")

    return [
        _text(description),
        ImageContent(
            type="image",
            data=base64.b64encode(content).decode("utf-8"),
            mimeType=mime_type,
        ),
    ]


security = TransportSecuritySettings(
    allowed_hosts=[
        "cat.hedecat.cc",
        "localhost",
        "localhost:8000",
        "127.0.0.1",
        "127.0.0.1:8000",
    ],
    allowed_origins=[
        "http://cat.hedecat.cc",
        "https://cat.hedecat.cc",
    ],
)

app = mcp.streamable_http_app(
    transport_security=security,
    host="0.0.0.0",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
