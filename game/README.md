# 狼人杀 — AI 版

8名 AI 玩家 + AI 裁判的狼人杀命令行游戏，支持人类玩家参与。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API key
cp .env.example .env
# 编辑 .env 填入你的 API key

# 运行
python main.py
```

## 配置说明 (.env)

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商：`anthropic` 或 `openai` | `anthropic` |
| `LLM_MODEL` | 模型名称 | `claude-haiku-3-5` |
| `LLM_API_KEY` | API 密钥 | (必填) |
| `LLM_BASE_URL` | 自定义 API 地址（可选） | 空 |
| `LLM_TEMPERATURE` | LLM 温度 (0-2) | `0.8` |
| `LLM_MAX_TOKENS` | 最大输出 token | `300` |
| `GAME_SPEED_DELAY` | AI裁判模式阶段间隔（秒） | `2.0` |

支持 OpenAI 兼容接口（如中转代理），设置 `LLM_PROVIDER=openai` 和 `LLM_BASE_URL` 即可。

## 角色配置（默认）

- 3 狼人 — 每晚击杀一名玩家
- 1 预言家 — 每晚查验一名玩家身份
- 1 女巫 — 拥有一瓶解药和一瓶毒药
- 1 猎人 — 被放逐或狼刀时可开枪带走一人
- 3 村民 — 无特殊技能

## 游戏模式

启动后选择游戏模式：

- **AI裁判模式**：游戏自动推进（可设置 `GAME_SPEED_DELAY` 控制速度）
- **人类玩家模式**：你参与游戏，作为9名玩家之一进行决策

## 项目结构

```
main.py          — 入口，选择游戏模式
game.py          — 游戏引擎，状态机
player.py        — Player 基类
ai_player.py     — AI 玩家，LLM 决策
role.py          — 角色定义
memory.py        — AI 记忆管理
prompts.py       — LLM 提示词模板
llm_client.py    — LLM API 客户端（Anthropic/OpenAI）
config.py        — 配置加载
utils.py         — 日志、解析工具
```

## 游戏流程

```
夜晚 → 宣布死亡 → 轮流发言 → 投票放逐 → 检查胜负 → 下一夜 → ...
```

## 日志

游戏日志同时输出到控制台和 `werewolf.log` 文件，包含所有 AI 决策细节。
