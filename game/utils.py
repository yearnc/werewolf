"""Utility functions for the Werewolf game."""

import logging
import re
import sys
from typing import Optional


def setup_logging(console_level: int = logging.INFO) -> None:
    logger = logging.getLogger("werewolf")
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers to prevent duplicates on re-initialization
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler("werewolf.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(file_handler)


logger = logging.getLogger("werewolf")


def extract_player_number(text: str, alive_ids: list[int]) -> Optional[int]:
    """Extract a player number from LLM output text.

    Returns the first number found that is in alive_ids, or None if no
    valid number can be extracted. Callers are responsible for fallback.
    """
    numbers = re.findall(r"\d+", text)
    for num_str in numbers:
        num = int(num_str)
        if num in alive_ids:
            return num
    return None


def parse_witch_decision(text: str, alive_ids: list[int]) -> tuple[str, Optional[int]]:
    """Parse witch's LLM decision.

    Returns (action, target_id) where action is "save", "poison", or "none".
    Uses prefix matching (compliant LLMs) with word-boundary fallback.
    """
    text = text.strip().lower()
    # Fast path: LLM follows the "save" / "poison N" / "none" format
    if text.startswith("save"):
        return ("save", None)
    if text.startswith("poison"):
        target = extract_player_number(text, alive_ids)
        return ("poison", target)
    if text.startswith("none"):
        return ("none", None)
    # Fallback: word-boundary search to avoid matching "not-save" etc.
    if re.search(r"\bpoison\b", text):
        target = extract_player_number(text, alive_ids)
        return ("poison", target)
    if re.search(r"\bsave\b", text):
        return ("save", None)
    return ("none", None)
