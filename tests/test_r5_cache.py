# -*- coding: utf-8 -*-
"""R5 缓存绕过机制：只对显式 force_refresh 生效，普通 TTL 缓存行为不变。

线上教训：raw.githubusercontent.com 也有 CDN 缓存，用固定 URL 强刷可能仍拿到旧库。
所以 refresh_library() / load_library(force_refresh=True) 追加 ?v=<ts>；
普通读取绝不追加，缓存命中不刷新。
"""
from urllib.parse import parse_qs, urlparse

import pytest
import requests

import sticker_engine


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {
            "version": "3.0",
            "stickers": [{"id": "cat-001", "file": "stickers/cat-001.png"}],
        }
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("status %s" % self.status_code)

    def json(self):
        return self._payload


@pytest.fixture()
def recorded(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    sticker_engine.reset_library_cache()
    monkeypatch.setattr(sticker_engine.requests, "get", fake_get)
    return calls


# ---------------------------------------------------------------- URL 形状
def test_normal_url_has_no_query(monkeypatch):
    monkeypatch.delenv("STICKER_REPO_URL", raising=False)
    assert sticker_engine.library_url() == sticker_engine.repo_base() + "instructions.json"
    assert "?" not in sticker_engine.library_url()


def test_bust_flag_appends_version_query(monkeypatch):
    monkeypatch.delenv("STICKER_REPO_URL", raising=False)
    url = sticker_engine.library_url(bust=True)
    parsed = urlparse(url)
    assert parsed.query, url
    assert "v" in parse_qs(parsed.query), url
    # 只多一个查询参数，主机与路径不变
    plain = urlparse(sticker_engine.library_url())
    assert (parsed.scheme, parsed.netloc, parsed.path) == (plain.scheme, plain.netloc, plain.path)


def test_bust_keeps_custom_repo_url(monkeypatch):
    monkeypatch.setenv("STICKER_REPO_URL", "https://example.com/mirror")
    url = sticker_engine.library_url(bust=True)
    assert url.startswith("https://example.com/mirror/instructions.json?v=")


# ---------------------------------------------------------------- 何时绕过
def test_plain_load_never_busts(recorded):
    sticker_engine.load_library()
    assert "?" not in recorded[0]


def test_force_refresh_busts(recorded):
    sticker_engine.load_library(force_refresh=True)
    assert "?v=" in recorded[0]


def test_refresh_library_busts(recorded):
    sticker_engine.refresh_library()
    assert "?v=" in recorded[0]


def test_legacy_force_alias_does_not_bust(recorded):
    """旧参数 force=True 只表示"跳缓存"，不新增查询参数（保持旧调用方 URL 不变）。"""
    sticker_engine.load_library(force=True)
    assert "?" not in recorded[0]


# ---------------------------------------------------------------- 缓存本身不变
def test_ttl_cache_still_serves_second_call(recorded):
    sticker_engine.load_library()
    sticker_engine.load_library()
    assert len(recorded) == 1


def test_force_refresh_always_hits_network(recorded):
    sticker_engine.load_library()
    sticker_engine.load_library(force_refresh=True)
    sticker_engine.load_library(force_refresh=True)
    assert len(recorded) == 3


def test_cache_buster_changes_between_refreshes(recorded, monkeypatch):
    """每次强刷都应该换一个 v 值，否则 CDN 仍可能命中同一缓存。"""
    monkeypatch.setattr(sticker_engine.time, "time", lambda: 1700000000.0)
    sticker_engine.load_library(force_refresh=True)
    monkeypatch.setattr(sticker_engine.time, "time", lambda: 1700000010.0)
    sticker_engine.load_library(force_refresh=True)
    assert recorded[0] != recorded[1]


# ---------------------------------------------------------------- 错误处理
def test_force_refresh_network_error_is_wrapped_with_url(monkeypatch):
    sticker_engine.reset_library_cache()
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    with pytest.raises(sticker_engine.StickerLibraryError) as exc:
        sticker_engine.load_library(force_refresh=True)
    message = str(exc.value)
    assert "instructions.json" in message
    assert "offline" in message
    # 仍然是 requests 异常的子类，旧调用方 except RequestException 不会漏
    assert isinstance(exc.value, requests.RequestException)


def test_force_refresh_bad_json_is_reported(monkeypatch):
    sticker_engine.reset_library_cache()
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: FakeResponse(payload=None, status_code=200))
    monkeypatch.setattr(FakeResponse, "json", lambda self: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(sticker_engine.StickerLibraryError):
        sticker_engine.load_library(force_refresh=True)


def test_force_refresh_does_not_clobber_good_cache(monkeypatch):
    """强刷失败不能把已加载的库清空（旧的缓存仍可用）。"""
    sticker_engine.set_library({"version": "3.0", "stickers": [
        {"id": "cat-001", "file": "stickers/cat-001.png"}]})
    before = sticker_engine.load_library()
    monkeypatch.setattr(sticker_engine.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("boom")))
    with pytest.raises(sticker_engine.StickerLibraryError):
        sticker_engine.load_library(force_refresh=True)
    after = sticker_engine.load_library()
    assert [x["id"] for x in after["stickers"]] == [x["id"] for x in before["stickers"]]
