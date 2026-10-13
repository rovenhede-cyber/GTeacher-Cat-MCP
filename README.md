\# 🐈 GTeacher Cat MCP Server



一个基于 MCP（Model Context Protocol）的猫猫表情包智能检索服务器。



\## ✨ 项目介绍



GTeacher Cat MCP Server 可以根据用户输入的关键词或场景，

从 GitHub 表情包数据库中自动寻找最匹配的猫猫表情。



功能：



\- GitHub 表情包库读取

\- JSON 语义标签匹配

\- 猫猫表情智能检索

\- MCP Server 接口提供



\---



\## 📂 项目结构

GTeacher-Cat-MCP

├── server.py

├── sticker\_engine.py

├── client\_test.py

├── requirements.txt

└── README.md



\---



\## 🛠️ 安装



创建虚拟环境：



```bash

python -m venv venv

启动：

Windows:

venv\\Scripts\\activate

安装依赖：

pip install -r requirements.txt



🚀 启动服务器

运行：

python server.py



成功后：

🐈 GTeacher Cat MCP Server 启动



🐾 测试

运行：

python client\_test.py



返回：

找到猫猫啦！



📌 数据来源

表情包数据库：

GitHub sticker repository

通过 instructions.json

保存：

\- 名称

\- 描述

\- 标签

\- 使用场景

\- 优先级

Future

计划支持：

\- AI 情绪识别

\- 自动选择表情包

\- ChatGPT MCP 调用

\- 多模态猫猫推荐

## MCP Tool

Available tools:

### get_cat_sticker

根据关键词返回匹配猫猫表情包。

Input:

{
 "keyword":"开心"
}

Output:

{
 "name":"爱心气球猫",
 "url":"..."
}

GTeacher Cat MCP v0.1.0
GTeacher Cat MCP v0.2.0
## Version History

### v0.2.0

- Added context-based sticker recommendation
- Added scoring system
- Added library caching
- Improved MCP tool response





