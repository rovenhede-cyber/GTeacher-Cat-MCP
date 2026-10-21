# -*- coding: utf-8 -*-
"""GTeacher Cat MCP 服务入口。

tool: send_cat_companion(user_emotional_context, sticker_id=None,
                        explicit_request=False, relationship_context="")

- explicit_request=True：客户端已确认这是“用户点名要表情包”，闸门不再按自动陪伴规则判断。
- sticker_id：直接指定某张图（旧接口，保留）。
- relationship_context：不传时用 DEFAULT_RELATIONSHIP_CONTEXT（默认 intimate）。
"""
import base64
from typing import Optional

import requests
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ImageContent, TextContent

from emotion_engine import analyze_context
from logger_config import logger
from sticker_config import CONFIG
from sticker_engine import (
    StickerImageError,
    StickerLibraryError,
    StickerNotFoundError,
    build_image_url,
    fetch_image,
    search_sticker,
    select_sticker,
)
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


@mcp.tool()
def send_cat_companion(
    user_emotional_context: str = "",
    sticker_id: Optional[str] = None,
    explicit_request: bool = False,
    relationship_context: str = "",
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
    """

    relationship = normalize_relationship(relationship_context)

    analysis = analyze_context(user_emotional_context, explicit_request=bool(explicit_request))
    analysis["relationship"] = relationship

    triggered = bool(sticker_id) or should_send_sticker(analysis)

    logger.info(
        "trigger_result triggered=%s exact_id=%s explicit_request=%s context_hash=%s "
        "detected_intent=%s user_emotion=%s requested_emotion=%s detected_intensity=%s "
        "actions=%s scenes=%s relationship=%s",
        triggered, bool(sticker_id), analysis["explicit_sticker_request"],
        analysis["context_hash"], analysis["intent"], analysis["user_emotion"],
        analysis["requested_sticker_emotion"], analysis["intensity"],
        analysis["actions"], analysis["scenes"], relationship,
    )

    if not triggered:
        return _text("当前场景不需要发送猫猫")

    try:
        if sticker_id:
            result = search_sticker(analysis, sticker_id=sticker_id, relationship=relationship)
        else:
            result = select_sticker(analysis, relationship=relationship)
    except StickerNotFoundError as exc:
        return _text(str(exc))
    except StickerLibraryError as exc:
        logger.error("Sticker library unavailable: %s", exc)
        return _text("表情库暂时不可用，本次跳过猫猫：%s" % exc)
    except requests.RequestException as exc:
        logger.error("Sticker index failed: %s", exc)
        return _text("猫猫图库加载失败，请稍后重试。")

    if result is None:
        return _text("没有找到合适猫猫")

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
