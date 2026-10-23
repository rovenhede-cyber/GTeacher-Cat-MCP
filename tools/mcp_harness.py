# -*- coding: utf-8 -*-
"""MCP 联调脚手架：本地图库站点 + 隔离端口的 MCP 服务子进程 + 客户端调用。

被 `tools/mcp_smoke.py`（人工联调）和 `tests/test_mcp_e2e.py`（自动化用例）共用。
只使用临时端口与临时目录，不触碰 8000 / 8001 / 8010 以及生产配置。
"""
import asyncio
import atexit
import functools
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")

# 1x1 透明 PNG：端到端能拿到真实 image content，又不依赖外网
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001a5f645400000000049454e44ae426082"
)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_library_dir(tmpdir):
    """把 fixture 铺成 HTTP 可读站点：instructions.json + stickers/*.png。"""
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(tmpdir, "instructions.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    for item in data["stickers"]:
        path = os.path.join(tmpdir, item["file"].replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(TINY_PNG)
    return data


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # 静音访问日志
        pass


def start_static(port, directory):
    handler = functools.partial(_QuietHandler, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def wait_http(url, timeout=40.0):
    """等到端口能返回 HTTP 响应。4xx 也算就绪（只是缺 header 或会话）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return exc.code
            last = exc
        except Exception as exc:  # noqa: BLE001 连不上就重试
            last = exc
        time.sleep(0.2)
    raise RuntimeError("服务未在 %.0fs 内就绪：%s（%s）" % (timeout, url, last))


async def _call_async(url, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read, write):  # 两个流
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            tool = next(t for t in tools.tools if t.name == "send_cat_companion")
            result = await session.call_tool("send_cat_companion", args)
            return {
                "server": init.server_info.name,
                "schema": sorted((tool.input_schema or {}).get("properties", {})),
                "is_error": result.is_error,
                "text": "".join(c.text for c in result.content if c.type == "text"),
                "images": [c.mime_type for c in result.content if c.type == "image"],
            }


def call(url, args):
    return asyncio.run(_call_async(url, args))


class CatServer:
    """本地图库站点 + MCP 服务子进程，with 语句退出即清理。"""

    def __init__(self, mode="shadow", env_extra=None):
        self.mode = mode
        self.env_extra = env_extra or {}
        self.dir = None
        self.httpd = None
        self.proc = None
        self.output = []
        self.static_port = None
        self.port = None

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="catmcp_")
        make_library_dir(self.dir)
        self.static_port, self.port = free_port(), free_port()
        self.httpd = start_static(self.static_port, self.dir)

        env = dict(os.environ)
        env.update({
            "STICKER_REPO_URL": "http://127.0.0.1:%d/" % self.static_port,
            "STICKER_IMAGE_BASE": "http://127.0.0.1:%d/" % self.static_port,
            "R5_INTENT_MODE": self.mode,
            "GTEACHER_LOG": os.path.join(self.dir, "server.log"),
            "GTEACHER_LOG_LEVEL": "INFO",
            "DEFAULT_RELATIONSHIP_CONTEXT": "intimate",
            "PORT": str(self.port),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        env.update(self.env_extra)

        # 生产入口 allowed_hosts 是固定白名单（cat.hedecat.cc / 127.0.0.1:8000），
        # 随机端口会被传输层 421 拒绝。测试用 launcher 只放宽 Host 白名单。
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests._mcp_launcher:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        atexit.register(self.close)  # 异常路径兜底，避免留下监听端口
        wait_http(self.url)
        return self

    @property
    def url(self):
        return "http://127.0.0.1:%d/mcp" % self.port

    @property
    def log_path(self):
        return os.path.join(self.dir, "server.log")

    def log_text(self):
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def __exit__(self, *exc):
        self.close()
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = None
        return False

    def close(self):
        """幂等清理：子进程 + 静态站点。异常退出时由 atexit 兜底。"""
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.output = self.proc.communicate(timeout=10)[0].decode(
                    "utf-8", "replace").splitlines()
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.output = []
            self.proc = None
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
