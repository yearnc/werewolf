"""AI Werewolf Game — entry point.

Launches a 9-player werewolf game. Supports two modes:
  1. AI referee (game auto-advances)
  2. Human player (you play as one of 9 players)
"""

import asyncio
import logging
import sys

# Windows console defaults to GBK, which can't encode emoji. Force UTF-8.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import Config
from game import Game
from utils import logger, setup_logging


async def main() -> None:
    setup_logging()

    # Load and validate config
    config = Config.load()
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"配置错误：{e}")
        logger.error("\n请检查 .env 文件配置。复制 .env.example 为 .env 并填入你的 API key。")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("🐺 狼人杀 — AI 版")
    logger.info("=" * 50)
    logger.info(f"LLM 提供商：{config.llm_provider}")
    logger.info(f"模型：{config.llm_model}")
    logger.info("")

    # Choose mode
    print("请选择游戏模式：")
    print("  1 — AI 裁判（游戏自动推进）")
    print("  2 — 人类玩家（你作为9名玩家之一参与游戏）")
    choice = input("请输入 1 或 2：").strip()

    while True:
        game = Game(config)

        if choice == "2":
            setup_logging(console_level=logging.INFO)
            print("\n👤 人类玩家模式启动...\n")
            await game.run_human_player_mode()
        else:
            setup_logging(console_level=logging.DEBUG)
            print("\n🤖 AI裁判模式启动，游戏将自动进行...\n")
            await game.run_ai_referee()

        print("\n是否再来一局？")
        print("  1 — 再来一局（同模式）")
        print("  2 — 切换模式再来一局")
        print("  任意键 — 退出")
        again = input("请输入：").strip()

        if again == "1":
            continue
        elif again == "2":
            print("\n请选择游戏模式：")
            print("  1 — AI 裁判")
            print("  2 — 人类玩家")
            choice = input("请输入 1 或 2：").strip()
            continue
        else:
            break

    logger.info("\n感谢游玩！")


if __name__ == "__main__":
    asyncio.run(main())
