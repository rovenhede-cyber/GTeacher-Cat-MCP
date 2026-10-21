"""Offline acceptance tests; external HTTP and MCP imports are stubbed."""

import base64
import json
import os
import pathlib
import re
import sys
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

requests = types.ModuleType("requests")
requests.RequestException = type("RequestException", (Exception,), {})
requests.get = lambda *args, **kwargs: None
sys.modules["requests"] = requests
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenv

mcp_package = types.ModuleType("mcp")
mcp_server = types.ModuleType("mcp.server")
mcp_server.__path__ = []
mcp_types = types.ModuleType("mcp.types")
mcp_security = types.ModuleType("mcp.server.transport_security")


class FakeMCPServer:
    def __init__(self, name):
        self.name = name

    def tool(self):
        return lambda fn: fn

    def streamable_http_app(self, **kwargs):
        return kwargs


class FakeContent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


mcp_server.MCPServer = FakeMCPServer
mcp_types.TextContent = FakeContent
mcp_types.ImageContent = FakeContent
mcp_security.TransportSecuritySettings = FakeContent
sys.modules["mcp"] = mcp_package
sys.modules["mcp.server"] = mcp_server
sys.modules["mcp.types"] = mcp_types
sys.modules["mcp.server.transport_security"] = mcp_security
uvicorn = types.ModuleType("uvicorn")
uvicorn.run = lambda *args, **kwargs: None
sys.modules["uvicorn"] = uvicorn

import emotion_engine
import server
import sticker_engine
import trigger_engine


LIBRARY_PATH = pathlib.Path(os.environ.get(
    "HEDECAT_TEST_LIBRARY", ROOT.parent / "stickersforGPT" / "instructions.json"
))
LIBRARY = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
STICKERS_BY_ID = {item["id"]: item for item in LIBRARY["stickers"]}


class FakeResponse:
    def __init__(self, payload=None, image=b"\x89PNG\r\n\x1a\n"):
        self.payload = payload
        self.content = image

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class HedeCat21Tests(unittest.TestCase):
    def setUp(self):
        self.library_patch = patch.object(sticker_engine, "load_library", return_value=LIBRARY)
        self.library_patch.start()
        self.addCleanup(self.library_patch.stop)

    def test_proposal_prefers_actual_ring_picture(self):
        context = emotion_engine.analyze_context("哥哥单膝跪地拿出钻戒向小德求婚")
        self.assertTrue(trigger_engine.should_send_sticker(context))
        self.assertEqual(sticker_engine.search_sticker(context)["id"], "cat-006")
        self.assertEqual(STICKERS_BY_ID["cat-006"]["action"], ["举戒指"])

    def test_comfort_request(self):
        context = emotion_engine.analyze_context("今天实验失败了，求抱抱")
        self.assertTrue(trigger_engine.should_send_sticker(context))
        self.assertEqual(sticker_engine.search_sticker(context)["id"], "cat-005")

    def test_celebration(self):
        context = emotion_engine.analyze_context("我终于把 MCP 做成功了")
        self.assertTrue(trigger_engine.should_send_sticker(context))
        self.assertEqual(sticker_engine.search_sticker(context)["id"], "cat-020")

    def test_technical_question_does_not_trigger(self):
        context = emotion_engine.analyze_context("帮我分析一下 XRD 图谱")
        self.assertFalse(trigger_engine.should_send_sticker(context))
        self.assertIsNone(sticker_engine.search_sticker(context))

    def test_direct_angry_sticker_request(self):
        for wording in ("给我发一张生气猫表情包", "请给我发一张生气猫表情包",
                        "来张生气猫", "我想要生气的表情包"):
            with self.subTest(wording=wording):
                context = emotion_engine.analyze_context(wording)
                self.assertTrue(context["explicit_sticker_request"])
                self.assertTrue(trigger_engine.should_send_sticker(context))
                self.assertIn("生气", sticker_engine.search_sticker(context)["emotion"])

    def test_named_sticker_request(self):
        context = emotion_engine.analyze_context("请发挥拳生气猫表情包")
        self.assertTrue(trigger_engine.should_send_sticker(context))
        self.assertEqual(sticker_engine.search_sticker(context)["id"], "cat-009")

    def test_direct_request_overrides_factual_context(self):
        context = emotion_engine.analyze_context("帮我分析一下 XRD 图谱，再发一张生气猫表情包")
        self.assertEqual(context["request_type"], "factual")
        self.assertTrue(context["explicit_sticker_request"])
        self.assertTrue(trigger_engine.should_send_sticker(context))
        self.assertIn("生气", sticker_engine.search_sticker(context)["emotion"])

    def test_incidental_or_negated_sticker_words_do_not_force_send(self):
        for wording in ("我今天很生气", "请分析生气猫表情包", "不要发生气猫表情包"):
            with self.subTest(wording=wording):
                context = emotion_engine.analyze_context(wording)
                self.assertFalse(context["explicit_sticker_request"])
                self.assertFalse(trigger_engine.should_send_sticker(context))

    def test_negated_proposal_does_not_match(self):
        context = emotion_engine.analyze_context("我不是在求婚，只是问戒指的材质")
        self.assertIn("求婚", context["negated_actions"])
        self.assertFalse(trigger_engine.should_send_sticker(context))
        self.assertIsNone(sticker_engine.search_sticker(context))

    def test_exact_id_and_missing_id(self):
        context = emotion_engine.analyze_context("")
        self.assertEqual(sticker_engine.search_sticker(context, sticker_id="cat-006")["id"], "cat-006")
        with self.assertRaisesRegex(sticker_engine.StickerNotFoundError, "cat-999"):
            sticker_engine.search_sticker(context, sticker_id="cat-999")

    def test_legacy_index_without_new_fields(self):
        legacy = {
            "version": "1.0",
            "stickers": [
                {key: value for key, value in item.items()
                 if key not in {"action", "scene", "trigger_actions", "emotion"}}
                for item in (STICKERS_BY_ID[sticker_id]
                             for sticker_id in ("cat-041", "cat-042", "cat-043"))
            ],
        }
        with patch.object(sticker_engine, "load_library", return_value=legacy):
            result = sticker_engine.search_sticker(emotion_engine.analyze_context("宝宝我好开心"))
        self.assertIsNotNone(result)

    def test_cache_expiry_and_force_refresh(self):
        self.library_patch.stop()
        self.addCleanup(lambda: None)
        sticker_engine._library_cache = None
        sticker_engine._library_loaded_at = 0
        first = {"stickers": [{"id": "old"}]}
        second = {"stickers": [{"id": "new"}]}
        with patch.object(sticker_engine.requests, "get",
                          side_effect=[FakeResponse(first), FakeResponse(second), FakeResponse(first)]) as get:
            with patch.object(sticker_engine.time, "monotonic", side_effect=[0, 3, 6, 7, 8]):
                self.assertEqual(sticker_engine.load_library(ttl_seconds=5), first)
                self.assertEqual(sticker_engine.load_library(ttl_seconds=5), first)
                self.assertEqual(sticker_engine.load_library(ttl_seconds=5), second)
                self.assertEqual(sticker_engine.refresh_library(), first)
            self.assertEqual(get.call_count, 3)
        sticker_engine._library_cache = None

    def test_server_exact_mode_keeps_image_format(self):
        with patch.object(server.requests, "get", return_value=FakeResponse()) as get:
            result = server.send_cat_companion(sticker_id="cat-006")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1].mimeType, "image/png")
        self.assertEqual(base64.b64decode(result[1].data), b"\x89PNG\r\n\x1a\n")
        self.assertIn("stickers/cat-006.png", result[0].text)
        self.assertEqual(get.call_count, 1)

    def test_server_explicit_request_flag_sends_angry_sticker(self):
        with patch.object(server.requests, "get", return_value=FakeResponse()):
            result = server.send_cat_companion(
                user_emotional_context="生气", explicit_request=True
            )
        self.assertEqual(len(result), 2)
        selected_id = re.search(r"cat-\d{3}", result[0].text).group()
        self.assertIn("生气", STICKERS_BY_ID[selected_id]["emotion"])

    def test_server_vocative_angry_request_never_selects_love(self):
        with patch.object(server.requests, "get", return_value=FakeResponse()):
            result = server.send_cat_companion(
                user_emotional_context="宝宝，请发一张生气的猫猫表情包，普通程度的生气。",
                explicit_request=True,
            )
        selected_id = re.search(r"cat-\d{3}", result[0].text).group()
        self.assertIn("生气", STICKERS_BY_ID[selected_id]["emotion"])

    def test_server_missing_id_is_clear(self):
        result = server.send_cat_companion(sticker_id="cat-999")
        self.assertIn("cat-999", result.text)

    def test_download_failure_keeps_url(self):
        with patch.object(server.requests, "get", side_effect=requests.RequestException("HTTP 503")):
            result = server.send_cat_companion(sticker_id="cat-006")
        self.assertIn("猫猫图片读取失败", result.text)
        self.assertIn("stickers/cat-006.png", result.text)
        self.assertIn("HTTP 503", result.text)

    def test_index_failure_returns_clear_error(self):
        with patch.object(server, "search_sticker",
                          side_effect=requests.RequestException("offline")):
            result = server.send_cat_companion(sticker_id="cat-006")
        self.assertIn("图库加载失败", result.text)


if __name__ == "__main__":
    unittest.main()
