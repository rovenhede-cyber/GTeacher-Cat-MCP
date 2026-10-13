# 🐈 GTeacher Cat MCP

> A MCP-powered intelligent cat sticker assistant.

一个基于 **Model Context Protocol (MCP)** 的智能猫猫表情包服务。

GTeacher Cat MCP 可以根据用户输入的情绪、场景和语义，
自动检索最匹配的猫猫表情，并通过 MCP Tool 提供给 AI 客户端调用。

---

## ✨ Features

- 🐱 智能猫猫表情检索
- 🧠 基于语义描述匹配表情
- 🔌 MCP Tool 支持
- 🌐 Streamable HTTP 服务模式
- 📦 GitHub 远程表情库管理
- 🚀 可被 AI Agent 调用

---

# 🏗 Architecture
GTeacher Cat MCP architecture overview:

          ```text
                 User

                  ↓

          AI Client / MCP Client

                  ↓

             MCP Protocol

                  ↓

        GTeacher Cat MCP Server

                  ↓

        ┌─────────────────┐
        │                                               │
        ↓                                                ↓
 instructions.json                    stickers/
        │                                               │
        └───────┬─────────┘
 
                              ↓

                 get_cat_sticker()

                              ↓

                 Return Cat Sticker
```
---

# 📦 Project Structure
GTeacher-Cat-MCP
├── server.py
│   MCP Server 主程序
│
├── sticker_engine.py
│   表情检索逻辑
│
├── instructions.json
│   猫猫表情语义数据库
│
├── stickers/
│   猫猫图片资源
│
├── client_mcp_test.py
│   stdio测试客户端
│
├── http_client_test.py
│   HTTP MCP测试客户端
│
├── requirements.txt
│   Python依赖
│
└── README.md

---

# 🚀 Installation

## 1. Clone repository

```bash
git clone https://github.com/rovenhede-cyber/GTeacher-Cat-MCP.git

cd GTeacher-Cat-MCP

2. Create environment
Activate:
python -m venv venv
Windows:
venv\Scripts\activate

3. Install dependencies
pip install -r requirements.txt

▶️ Run Server
Start MCP Server:
python server.py

Default endpoint:
http://127.0.0.1:8000/mcp

🧪 Test MCP Connection
Run:
python http_client_test.py

Expected:
可用工具：

- get_cat_sticker

🐱 MCP Tool
get_cat_sticker
根据用户情绪和场景返回最匹配猫猫表情。
Example:
{
"context":"开心庆祝"
}

Return:
{
"name":"爱心气球猫",
"file":"stickers/t-1.jpg"
}

📌 Version History
v0.3.0
Current version.
Added:
- Streamable HTTP MCP support
- Remote MCP connection
- HTTP client testing
v0.2.0
Initial MCP version.
Added:
- Sticker library
- Search engine
- MCP Tool

❤️ About
GTeacher Cat MCP is a personal AI expression assistant project.
Built with:
- Python
- MCP
- GitHub
- AI Agent workflow
🐈 May every conversation have a suitable cat sticker.