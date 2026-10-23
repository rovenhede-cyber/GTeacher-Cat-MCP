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

`gate_reason()` 返回 (是否发送, 原因)，原因只用于日志/诊断，不改变任何判定。
"""
from logger_config import logger

ALLOW_INTENTS = {"comfort", "celebrate", "affection", "gratitude"}
ALLOW_SCENES = {"安慰", "庆祝", "亲密互动", "求婚"}

# 闸门原因（日志/诊断用；不要把原因当成对外契约）
REASON_CRISIS = "crisis"
REASON_EXPLICIT = "explicit_request"
REASON_SERIOUS = "serious_task"
REASON_SCENE = "scene"
REASON_NO_SIGNAL = "no_signal"
REASON_HELP_ONLY = "help_only"
REASON_SIGNAL = "signal"


def gate_reason(context):
    """返回 (should_send, reason)。判定顺序与原实现完全一致。"""
    if context.get("crisis"):
        logger.info("Gate: skip sticker because crisis detected")
        return False, REASON_CRISIS

    if context.get("explicit_sticker_request"):
        return True, REASON_EXPLICIT

    if context.get("serious"):
        logger.info("Gate: skip sticker because serious/technical task")
        return False, REASON_SERIOUS

    intents = set(context.get("intent") or [])
    emotions = context.get("emotion") or []
    actions = context.get("actions") or []
    scenes = set(context.get("scenes") or [])

    if scenes & ALLOW_SCENES:
        return True, REASON_SCENE

    if not emotions and not actions and not intents:
        return False, REASON_NO_SIGNAL

    if intents and intents <= {"help"} and not emotions and not actions:
        return False, REASON_HELP_ONLY

    if intents & ALLOW_INTENTS or emotions or actions:
        return True, REASON_SIGNAL

    return False, REASON_NO_SIGNAL


def should_send_sticker(context):
    return gate_reason(context)[0]
