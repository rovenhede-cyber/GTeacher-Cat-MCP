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
│   MCP Server 主程序（send_cat_companion）
│
├── sticker_engine.py
│   表情检索：拉库 / 语境过滤 / 打分 / 稳定选择
│
├── emotion_engine.py
│   文本 -> 情绪组、意图、动作、强度、危机/技术判定
│
├── trigger_engine.py
│   发送闸门（危机、技术任务、无信号不发送）
│
├── taxonomy.py
│   情绪组 / 动作意图 / 语境词表
│
├── sticker_config.py
│   可配置打分权重（支持环境变量覆盖）
│
├── stickers/
│   猫猫图片资源（远程库，位于 stickersforGPT 仓库）
│
├── tests/
│   离线单元 + 服务层集成测试（77 张真实元数据 fixture）
│
├── tools/explain.py
│   本地排查：打印分析、过滤结果与候选排名
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
send_cat_companion(user_emotional_context, sticker_id=None, explicit_request=False, relationship_context="")
根据用户情绪、动作意图与场景返回最匹配猫猫表情。

参数：
- user_emotional_context：用户最近的情绪场景描述（不是单个关键词）
- sticker_id：可选，直接指定某张图（旧接口保留）
- explicit_request：可选，客户端已确认「用户在点名要表情包」时置 True；此闸门优先于技术任务判定
- relationship_context：可选，关系上下文，只能由调用方明确传入，不要从文本猜测
  - 不传（或传 ""）= 使用 `DEFAULT_RELATIONSHIP_CONTEXT`，默认 **intimate**
  - "intimate" 亲密/情侣/角色扮演（默认：HedeCat 的日常聊天与亲密互动场景）
  - "friend" 朋友
  - "formal" 工作/正式（不出现任何带关系声明的图片）
  - "unknown" 仅在明确需要「未知关系测试/通用场景」时显式传入

Example:
{
"user_emotional_context":"今天实验终于成功了，好开心"
}

Return:
文本（名称 + 描述 + 图片路径）+ ImageContent（base64 图片）

---

# 🧠 选图逻辑（v0.4.0，r4 兼容修复）

```
user_emotional_context
        │
        ▼
emotion_engine.analyze_context()   -> emotion(情绪组) / intent / actions / intensity / crisis / serious
        │
        ▼
trigger_engine.should_send_sticker()  -> 否：直接返回（危机 / 技术任务 / 无信号）
        │
        ▼
sticker_engine.apply_filters()     -> avoid_when 语境 / relationship / 持刀类语境
        │
        ▼
sticker_engine.score_item()        -> 情绪组 + 关键词 + 动作意图 + 强度区间 + priority 排序权重
        │
        ▼
rank: (-score, -priority, id)      -> 稳定取第一，同分不随机
```

打分项（默认值，可用环境变量覆盖，见 `.env.example`）：

| 项 | 默认分 | 说明 |
| --- | --- | --- |
| 情绪组命中 | +5 / 组（最多 2 组） | 文本情绪组与图片 emotion 按 `taxonomy.EMOTION_GROUPS` 归组比对 |
| 关键词命中 tags | +3 / 个 | 精确相同 |
| 关键词出现在名称 | +4 | 只计一次 |
| 关键词出现在描述 | +1 | 只计一次 |
| 关键词出现在 use_when/scene | +2 | 只计一次 |
| 动作命中 trigger_actions | +8 | 「用户想做的动作」精确匹配 |
| 动作降级 action/tags | +3 | 仅当该图**没有** trigger_actions 时启用 |
| 强度落在 intensity_range 内 | +4 | 对话 intensity 1–10 |
| 距区间 1 分 | +1 | 近似可接受 |
| 距区间 2 分 | -8（`W_INTENSITY_OUT`） | 抑制错误强度 |
| 距区间 n>2 分 | -8 + (n-2)×(-2)（`W_INTENSITY_OUT_STEP`） | 越远扣得越多 |
| priority | `priority × 0.2` | **只是排序权重**，不是情绪强度 |

强度与字段的边界：

- `intensity_range` 参与打分；缺失时按中性处理并在日志里给出 id，不会丢图。
- `mood_strength` **不参与打分**，只在越出 `intensity_range` 时打印告警（当前 `cat-042` 会触发该告警，属于数据待修项）。
- `priority` 只作排序权重，不能替代关系限制、avoid_when 或强度区间。

过滤规则（先过滤，再打分）：

1. 危机表达（自伤/轻生）→ 全部不发送。
2. `relationship` 存在时，按 `intimate / friend / formal / unknown` 取交集：
   - `intimate`（**默认**）允许「朋友 / 亲密关系 / 亲昵角色扮演」
   - `friend`、`unknown` 只允许「朋友」类（`unknown` 只在显式要求时使用）
   - `formal` **不放行任何带关系声明的图片**（包括只标了「朋友」的）；没有 `relationship` 字段的通用图片不受影响
   - 字段语义是「**适用关系**」：只声明一个值＝专属（如 `cat-042` 只属亲密），声明多个＝通用型亲昵
3. `avoid_when` 命中当前语境（冲突、恐惧、严肃、严重负面）→ 剔除。
4. 持刀/威慑类图片：只在玩笑语境且无风险信号时可用。

### 用户自述 vs 明确索图

| 输入 | user_emotion | requested_sticker_emotion | 结果 |
| --- | --- | --- | --- |
| 宝宝，我今天好生气 | `["angry"]` | `[]` | 按用户情绪自动安慰 |
| 给我一张生气的猫猫 | `[]` | `["angry"]` | 走索图：情绪筛选后排名 |
| 我气死了，请发一张有点生气的猫猫 | `["angry"]` | `["angry"]` | 用**索图语气**（有点=2），不受“气死了”影响 |

- 索图请求支持画面约束：`给我一张头顶冒火的猫猫` / `挥拳头` / `揪衣领` / `抱爱心` / `点赞` / `亲亲`。
  约束只在图片的 `action / 描述 / 名称 / 标签` 里找证据；找不到证据就返回“没有找到合适猫猫”，不会硬凑。
- `给我一张摸头的猫猫` 这类图库中不存在的画面 → 安全返回 None（有测试覆盖）。

### 强度分级（cue-based，1–10）

| 说法 | 强度 |
| --- | --- |
| 有点 / 稍微 / 一点点 + 情绪词 | 2 |
| 只出现情绪词 | 5 |
| 真的 / 很 / 好 / 挺 + 情绪词 | 6 |
| 特别 / 非常 / 超级 / 太 + 情绪词；气死 / 崩溃 / 痛哭 | 9 |
| 重复情绪词 +2、双重程度词 +1、连续感叹号 +1 | 在中档以上累加 |

强度只来自**语气线索**，不再用命中词数量堆叠；索图时取索图语气，自述时取用户语气。

### 兼容旧接口

| 旧调用 | 现在的行为 |
| --- | --- |
| `search_sticker(ctx, deterministic=True/False)` | 支持；True 按 score→priority→id 稳定取第一，False 在近平票集合里随机 |
| `search_sticker(ctx, sticker_id="cat-009")` | 精确返回；不存在抛 `StickerNotFoundError` |
| `load_library(force_refresh=True)` / `load_library(ttl_seconds=5)` | 支持；默认 TTL 300s，`refresh_library()` 强刷 |
| `except requests.RequestException` | `StickerLibraryError` 同时继承 `requests.RequestException`，旧捕获仍生效 |
| 图片下载 mock | 改成 mock `server.fetch_image`（下载逻辑已迁到 `sticker_engine.fetch_image`） |

本地验证：

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q                       # 145 个用例，全部离线
python tools/explain.py "我有点难过，抱抱我"        # 看分析 + 过滤 + 候选排名
python tools/explain.py "爱你，媳妇～" --relationship intimate
```

部署注意：

- 先合并 `stickersforGPT` 的 `instructions.json`（v3.0，77 条）再上线服务端，否则新图不会被选中。
- `cat-042` 的 `relationship` 是 `["亲密关系","亲昵角色扮演"]`：默认 `intimate` 下可以正常被选中；
  显式传 `friend` / `formal` / `unknown` 时会被过滤掉。
- 部署时可用 `DEFAULT_RELATIONSHIP_CONTEXT` 切换默认语境（见 `.env.example`），改动无需改代码。

---

# 🎬 Demo

## Example: Find a cat sticker

User:
今天实验成功啦！

AI:
分析：
情绪 = 开心
场景 = 庆祝


Call MCP Tool:

```json
{
  "context": "开心庆祝"
}
Return:
{
  "name": "爱心气球猫",
  "file": "stickers/t-1.jpg"
}
Result:
🐈🎈 爱心气球猫

Example:

![GTeacher Cat MCP Demo](docs/demo.png)

📌 Version History
v0.4.0
Current version.
Added / Fixed:
- 修复情绪匹配永远不生效（分析侧输出英文 sad/happy，图库侧是中文标签）
- 修复 `intent` 匹配失效（instructions.json 里没有 intent 字段）
- intensity 改为「情绪基准 + 强度词 + 标点」的 1–10 估算，并按 intensity_range 匹配
- 动作意图（抱抱/亲亲/求婚/比心/送花）走 trigger_actions，旧图用 action/tags 有限回退
- 新增 avoid_when / relationship 过滤与持刀类语境限制
- priority 降级为排序权重（0.2×），不再当强度用
- 选择改为确定性排序（同分按 priority → id），不再随机
- 新增 StickerLibraryError / StickerImageError，库或图片失败不再抛裸异常
- 新增离线测试（当前 76 个）、tools/explain.py 排查工具、.env.example
- r4 兼容修复：区分 `user_emotion` / `requested_sticker_emotion`；支持点名索图与画面约束
  （冒火/挥拳/揪衣领/抱爱心/点赞）；强度改为 cue-based 三档；修复“通过插件”被误判为庆祝；
  恢复 `deterministic` / `force_refresh` / `ttl_seconds` / `sticker_id` / `refresh_library` 等旧接口；
  日志改为 hash + 诊断字段（不落原始文本）
- r3 调整：新增 `DEFAULT_RELATIONSHIP_CONTEXT`（默认 `intimate`），缺省不再降级为 `unknown`；
  `unknown` 只能显式指定；明确 `relationship` 是「适用关系」，缺字段的通用图片不排除
- r2 修正：`.env` 权重在 `CONFIG` 创建前加载（此前 .env 里的 W_* 全部失效）；
  强度区间外扣分默认值统一为 -8（此前代码 -6 / 文档 -8 不一致）；
  `formal` 语境不再自动放行「仅朋友」的图片
v0.3.0
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