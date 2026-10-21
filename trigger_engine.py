# -*- coding: utf-8 -*-
"""发送闸门：什么时候**不该**发表情包。

规则（按顺序）：
1. 危机表达（自伤/轻生）              -> 不发
2. 用户明确索图（工具指令）            -> 发（这是指令，不是自动陪伴判断）
3. 技术/严肃任务                       -> 不发
4. 有场景（安慰/庆祝/亲密互动/求婚）   -> 发
5. 完全没有情绪、动作、意图信号         -> 不发
6. 只有 help 意图且没有情绪表达         -> 不发

说明：明确索图（“给我一张生气的猫猫”）即使发生在技术讨论里也是用户指令，
所以它排在 serious 之前；但危机场景仍然优先拦截。
"""
from logger_config import logger

ALLOW_INTENTS = {"comfort", "celebrate", "affection", "gratitude"}
ALLOW_SCENES = {"安慰", "庆祝", "亲密互动", "求婚"}


def should_send_sticker(context):
    if context.get("crisis"):
        logger.info("Gate: skip sticker because crisis detected")
        return False

    if context.get("explicit_sticker_request"):
        return True

    if context.get("serious"):
        logger.info("Gate: skip sticker because serious/technical task")
        return False

    intents = set(context.get("intent") or [])
    emotions = context.get("emotion") or []
    actions = context.get("actions") or []
    scenes = set(context.get("scenes") or [])

    if scenes & ALLOW_SCENES:
        return True

    if not emotions and not actions and not intents:
        return False

    if intents and intents <= {"help"} and not emotions and not actions:
        return False

    return bool(intents & ALLOW_INTENTS or emotions or actions)
