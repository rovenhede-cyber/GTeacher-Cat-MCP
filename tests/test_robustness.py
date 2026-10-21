"""健壮性：库拉取失败、图片缺失/下载失败、缓存重置。"""
import requests
import pytest

import sticker_engine
from sticker_engine import (
    StickerImageError,
    StickerLibraryError,
    build_image_url,
    fetch_image,
    load_library,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("status %s" % self.status_code)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_library_network_error_raises_clear_exception(monkeypatch):
    sticker_engine.reset_library_cache()
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("boom")))
    with pytest.raises(StickerLibraryError) as exc:
        load_library()
    assert "表情库" in str(exc.value) or "instructions.json" in str(exc.value)


def test_library_payload_without_stickers_raises(monkeypatch):
    sticker_engine.reset_library_cache()
    monkeypatch.setattr(sticker_engine.requests, "get", lambda *a, **k: FakeResponse(200, {"foo": 1}))
    with pytest.raises(StickerLibraryError):
        load_library()


def test_library_caches_after_success(monkeypatch):
    sticker_engine.reset_library_cache()
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, {"stickers": [{"id": "a", "file": "stickers/a.png"}]})

    monkeypatch.setattr(sticker_engine.requests, "get", fake_get)
    load_library()
    load_library()
    assert len(calls) == 1


def test_image_url_requires_file():
    with pytest.raises(StickerImageError):
        build_image_url("")
    with pytest.raises(StickerImageError):
        build_image_url(None)


def test_image_url_absolute_passthrough():
    assert build_image_url("https://x/y.png") == "https://x/y.png"
    assert build_image_url("stickers/cat-001.png").endswith("/stickers/cat-001.png")


def test_image_download_failure(monkeypatch):
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("timeout")))
    with pytest.raises(StickerImageError) as exc:
        fetch_image("stickers/cat-001.png")
    assert "图片" in str(exc.value)


def test_image_404(monkeypatch):
    monkeypatch.setattr(sticker_engine.requests, "get", lambda *a, **k: FakeResponse(404))
    with pytest.raises(StickerImageError):
        fetch_image("stickers/not-exist.png")


def test_image_success(monkeypatch):
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: FakeResponse(200, content=b"\x89PNG"))
    assert fetch_image("stickers/cat-001.png") == b"\x89PNG"
