"""配置层：.env 加载顺序、权重生效、强度扣分默认值与文档一致。"""
import os
import subprocess
import sys

import pytest

import sticker_config
from sticker_config import CONFIG, reload_config, reset_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def clean_weights():
    """测试结束后把 W_* 环境变量清掉并重算权重，避免污染其它用例。"""
    keys = [k for k in os.environ if k.startswith("W_") or k.startswith("MIN_") or k.startswith("MAX_")]
    saved = {k: os.environ[k] for k in keys}
    yield
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(saved)
    reset_config()


def test_intensity_out_default_matches_docs(clean_weights):
    """文档写「距区间 2 分扣 -8」，代码默认值必须是 -8，不能再是 -6。"""
    assert CONFIG.intensity_out_of_range == -8.0
    assert CONFIG.intensity_out_step == -2.0


def test_out_of_range_penalty_uses_configured_default(clean_weights):
    from sticker_engine import score_item

    item = {"id": "t", "name": "测试", "description": "", "emotion": ["喜欢"], "tags": [],
            "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/t.png",
            "intensity_range": [5, 8]}
    ctx = {"emotion": ["喜欢"], "intensity": 3, "keywords": [], "actions": [], "intent": []}
    # 距区间 2 分 -> -8；再远 1 分 -> -10
    assert score_item(item, ctx)["breakdown"]["intensity"] == -8.0
    ctx_far = dict(ctx, intensity=1)
    assert score_item(item, ctx_far)["breakdown"]["intensity"] == -12.0


def test_env_file_weights_take_effect(tmp_path, clean_weights):
    env_file = tmp_path / ".env"
    env_file.write_text("W_TRIGGER=12\nW_INTENSITY_OUT=-9\n", encoding="utf-8")

    reload_config(str(env_file))

    assert CONFIG.trigger_action == 12.0
    assert CONFIG.intensity_out_of_range == -9.0

    # 打分真的用上了新权重，而不只是字段变了
    from sticker_engine import score_item

    item = {"id": "t2", "name": "抱抱", "description": "", "emotion": [], "tags": [],
            "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/t2.png",
            "trigger_actions": ["拥抱"], "intensity_range": [4, 8]}
    ctx = {"emotion": [], "intensity": 5, "keywords": [], "actions": ["抱抱"], "intent": []}
    assert score_item(item, ctx)["breakdown"]["trigger_action"] == 12.0

    item2 = dict(item, trigger_actions=[])
    # 区间 [4,8]，强度 2 => 距区间 2 分 => 用配置的 -9
    ctx2 = {"emotion": ["喜欢"], "intensity": 2, "keywords": [], "actions": [], "intent": []}
    assert score_item(item2, ctx2)["breakdown"]["intensity"] == -9.0


def test_env_is_loaded_before_config_is_created(tmp_path):
    """子进程里用带 .env 的目录做 cwd 导入模块，验证 CONFIG 创建前已读 .env。"""
    (tmp_path / ".env").write_text("W_EMOTION=7\n", encoding="utf-8")
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("W_") and not k.startswith("MIN_") and not k.startswith("MAX_")
    }
    env["PYTHONPATH"] = ROOT

    result = subprocess.run(
        [sys.executable, "-c", "import sticker_config; print(sticker_config.CONFIG.emotion_group)"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7.0", result.stdout


def test_invalid_env_value_falls_back_to_default(tmp_path, clean_weights):
    env_file = tmp_path / ".env"
    env_file.write_text("W_TRIGGER=abc\n", encoding="utf-8")
    reload_config(str(env_file))
    assert CONFIG.trigger_action == 8.0


def test_config_module_is_the_same_object_used_by_engine(clean_weights):
    """引擎 import 的是同一个 CONFIG 对象，reload 后立即生效（无需重启）。"""
    import sticker_engine

    assert sticker_engine.CONFIG is sticker_config.CONFIG
