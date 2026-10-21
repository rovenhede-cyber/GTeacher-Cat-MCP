"""服务层集成：tool 返回值、闸门、异常回退（不触网）。"""
import pytest

mcp = pytest.importorskip("mcp", reason="需要 mcp 2.3.0 才能测服务层")

import server                      # noqa: E402
import sticker_engine              # noqa: E402


@pytest.fixture()
def fake_image(monkeypatch):
    monkeypatch.setattr(server, "fetch_image", lambda path: b"\x89PNG-fake-bytes")


def _text_of(result):
    return result.text if not isinstance(result, list) else result[0].text


def test_tool_returns_text_and_image(fake_image):
    result = server.send_cat_companion("今天好开心")
    assert isinstance(result, list) and len(result) == 2
    assert result[0].type == "text" and "猫猫名称" in result[0].text
    assert result[1].type == "image"
    assert result[1].mime_type == "image/png"


def test_tool_skips_plain_statement():
    result = server.send_cat_companion("今天下午三点开会")
    assert "不需要" in _text_of(result)


def test_tool_skips_crisis():
    result = server.send_cat_companion("我真的不想活了")
    assert "不需要" in _text_of(result)


def test_tool_skips_tech_question():
    result = server.send_cat_companion("这个接口报错怎么排查")
    assert "不需要" in _text_of(result)


def test_tool_respects_explicit_unknown(fake_image):
    result = server.send_cat_companion("爱你，媳妇～", relationship_context="unknown")
    assert "天使送心团子" not in _text_of(result)


def test_tool_default_relationship_is_intimate(fake_image):
    from sticker_config import CONFIG

    assert server.normalize_relationship("") == "intimate" == CONFIG.default_relationship
    assert server.normalize_relationship("unknown") == "unknown"
    assert server.normalize_relationship("正式") == "formal"
    assert server.normalize_relationship("随便写点什么") == CONFIG.default_relationship
    result = server.send_cat_companion("想亲亲你")
    assert isinstance(result, list)


def test_tool_accepts_intimate_relationship(fake_image):
    result = server.send_cat_companion("爱你，媳妇～", relationship_context="亲密")
    assert isinstance(result, list)


def test_tool_library_error_is_reported(monkeypatch):
    def boom(*args, **kwargs):
        raise sticker_engine.StickerLibraryError("库挂了")

    monkeypatch.setattr(server, "select_sticker", boom)
    result = server.send_cat_companion("今天好开心")
    assert "表情库" in _text_of(result)


def test_tool_image_error_is_reported(monkeypatch):
    def boom(path):
        raise sticker_engine.StickerImageError("图片挂了")

    monkeypatch.setattr(server, "fetch_image", boom)
    result = server.send_cat_companion("今天好开心")
    assert "图片下载失败" in _text_of(result)
