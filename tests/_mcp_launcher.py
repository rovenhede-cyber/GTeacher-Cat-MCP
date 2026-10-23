# -*- coding: utf-8 -*-
"""测试用 MCP 启动器：复用真实 server 模块，只把测试端口加入 Host 白名单。

生产入口 server.py 的 allowed_hosts 是固定白名单（cat.hedecat.cc / 127.0.0.1:8000…），
在随机端口上启动真实服务会被传输层以 421 拒绝。测试不该改生产配置，
所以在测试端口上重建一个只放宽 Host 白名单的 app，其余逻辑完全一致。

用法：PORT=xxxx python -m uvicorn tests._mcp_launcher:app
"""
import os

from mcp.server.transport_security import TransportSecuritySettings

import server  # noqa: E402  真实服务模块（含 mcp 实例与 send_cat_companion）

_port = os.getenv("PORT", "")
_hosts = ["127.0.0.1", "localhost"]
if _port:
    _hosts += ["127.0.0.1:%s" % _port, "localhost:%s" % _port]

app = server.mcp.streamable_http_app(
    transport_security=TransportSecuritySettings(
        allowed_hosts=_hosts,
        allowed_origins=["http://127.0.0.1%s" % (":%s" % _port if _port else "")],
    ),
    host="127.0.0.1",
)
