# -*- coding: utf-8 -*-
"""可配置的打分权重。所有数值都可用环境变量覆盖，改权重不需要动引擎代码。

**加载顺序很重要**：本模块在创建 CONFIG 之前先执行 load_dotenv()。
sticker_engine 里的 load_dotenv() 执行得太晚（它 import 本模块时 CONFIG 已经建好），
只靠那里读 .env 会让 `.env` 中的 W_* 权重全部失效。

字段职责（互不替代）：
- emotion / tags / name / description / use_when / scene  -> 语义匹配
- trigger_actions  -> 动作意图匹配（用户想做的动作）
- action           -> 仅作 trigger_actions 缺失时的降级来源
- intensity_range  -> 对话强度是否落在图片适用区间
- mood_strength    -> 图片自身情绪浓度，仅做数据校验，不参与打分
- priority         -> 纯排序权重（很小的常数项 + 同分时的次序）
"""
import os

from dotenv import load_dotenv

# 关键：必须在 CONFIG 创建之前读 .env（默认读当前工作目录下的 .env）
load_dotenv()


RELATIONSHIPS = ("intimate", "friend", "formal", "unknown")

DEFAULT_RELATIONSHIP_FALLBACK = "intimate"

# R5 意图模式：off（回滚到 R4）/ shadow（只观察，返回仍是 R4 结果）/ auto（意图生效）
INTENT_MODES = ("off", "shadow", "auto")
DEFAULT_INTENT_MODE = "shadow"


def _intent_mode():
    raw = (os.getenv("R5_INTENT_MODE") or "").strip().lower()
    return raw if raw in INTENT_MODES else DEFAULT_INTENT_MODE


def _default_relationship():
    """DEFAULT_RELATIONSHIP_CONTEXT 的取值；非法值回落到 intimate 并保留告警线索。"""
    raw = (os.getenv("DEFAULT_RELATIONSHIP_CONTEXT") or "").strip().lower()
    if raw in RELATIONSHIPS:
        return raw
    return DEFAULT_RELATIONSHIP_FALLBACK


def _num(name, default, cast=float):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


def _values():
    """按当前环境变量算出全部权重；reload_config() 复用同一份定义。"""
    return {
        # 语义匹配
        "emotion_group": _num("W_EMOTION", 5.0),
        "tag_hit": _num("W_TAG", 3.0),
        "name_hit": _num("W_NAME", 4.0),
        "description_hit": _num("W_DESC", 1.0),
        "use_when_hit": _num("W_USE_WHEN", 2.0),
        # 动作意图
        "trigger_action": _num("W_TRIGGER", 8.0),
        "action_fallback": _num("W_ACTION_FALLBACK", 3.0),
        # 强度区间
        "intensity_in_range": _num("W_INTENSITY_IN", 4.0),
        "intensity_near_edge": _num("W_INTENSITY_EDGE", 1.0),
        # 距区间 2 分时的扣分起点（默认 -8），每多 1 分再叠加 intensity_out_step
        "intensity_out_of_range": _num("W_INTENSITY_OUT", -8.0),
        "intensity_out_step": _num("W_INTENSITY_OUT_STEP", -2.0),
        # R5 助手回应意图（只在 R5_INTENT_MODE=auto 时参与打分）
        "intent_exact": _num("W_INTENT_EXACT", 8.0),
        "intent_family": _num("W_INTENT_FAMILY", 4.0),
        "intent_conflict": _num("W_INTENT_CONFLICT", -10.0),
        "intent_persona": _num("W_INTENT_PERSONA", 2.0),
        # 已知意图时情绪组匹配的权重（低于默认 5.0：意图比情绪更接近"该发哪张"）
        "emotion_when_intent": _num("W_EMOTION_WHEN_INTENT", 2.5),
        "intent_mode": _intent_mode(),
        # 排序权重（很小，不能盖过语义与强度）
        "priority_weight": _num("W_PRIORITY", 0.2),
        # 阈值
        "min_score": _num("MIN_SCORE", 0.5),
        "min_match_score": _num("MIN_MATCH_SCORE", 2.0),
        "max_emotion_groups": _num("MAX_EMOTION_GROUPS", 2, int),
        # 关系语境默认值：HedeCat 的主场景是用户与 G 老师的日常聊天/亲密互动
        "default_relationship": _default_relationship(),
    }


class ScoringConfig:
    def __init__(self):
        for key, value in _values().items():
            setattr(self, key, value)

    EXPLAIN = {
        "emotion_group": "用户情绪组与图片 emotion（按组映射）一致",
        "tag_hit": "关键词精确命中 tags",
        "name_hit": "关键词出现在名称里",
        "description_hit": "关键词出现在描述里",
        "use_when_hit": "关键词出现在 use_when/scene 里",
        "trigger_action": "动作意图命中 trigger_actions",
        "action_fallback": "无 trigger_actions 时，动作意图命中 action",
        "intensity": "对话强度落在 intensity_range 内/边缘/区间外",
        "intent_exact": "助手回应意图与图片表达行为精确一致",
        "intent_family": "意图与图片行为同属一个近义家族",
        "intent_conflict": "意图与图片行为明显矛盾（扣分，不参与过滤）",
        "intent_persona": "图片是助手视角的表达（道谢/陪伴/鼓励），与意图叠加",
        "priority": "排序权重 = priority * priority_weight（只影响同分次序与轻微偏移）",
    }


CONFIG = ScoringConfig()


def reset_config():
    """只按当前 os.environ 重算权重（不读 .env）。测试清理与热更新都用它。"""
    for key, value in _values().items():
        setattr(CONFIG, key, value)
    return CONFIG


def reload_config(env_file=None, override=True):
    """重新读 .env 后重算权重；原地更新 CONFIG，已 import 的模块立即生效。"""
    load_dotenv(env_file, override=override)
    return reset_config()
