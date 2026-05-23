"""Configuration loader for the Werewolf game."""

import os
from dataclasses import dataclass
from pathlib import Path

from crypto_utils import decrypt_env_value
from dotenv import load_dotenv

# Load .env relative to this file — works regardless of CWD
load_dotenv(Path(__file__).parent / ".env")


@dataclass
class Config:
    llm_provider: str = "openai"
    llm_model: str = "deepseek-chat"
    llm_api_keys: list[str] = None  # type: ignore[assignment]
    llm_base_url: str | None = None
    llm_temperature: float = 0.6
    llm_max_tokens: int = 5000
    game_speed_delay: float = 2.0

    def __post_init__(self):
        if self.llm_api_keys is None:
            self.llm_api_keys = []

    @classmethod
    def load(cls) -> "Config":
        # Collect up to 3 API keys
        keys: list[str] = []
        for env_var in ("LLM_API_KEY_1", "LLM_API_KEY_2", "LLM_API_KEY_3"):
            key = os.getenv(env_var, "").strip()
            if key:
                keys.append(decrypt_env_value(key))
        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat").strip(),
            llm_api_keys=keys,
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "5000")),
            game_speed_delay=float(os.getenv("GAME_SPEED_DELAY", "2.0")),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.llm_api_keys:
            errors.append("至少需要设置一个 LLM_API_KEY（LLM_API_KEY_1 / LLM_API_KEY_2 / LLM_API_KEY_3 或 LLM_API_KEY）")
        if self.llm_provider not in ("anthropic", "openai"):
            errors.append(f'Unknown LLM_PROVIDER "{self.llm_provider}" — use "anthropic" or "openai"')
        if self.llm_temperature < 0 or self.llm_temperature > 2:
            errors.append("LLM_TEMPERATURE must be between 0 and 2")
        return errors

    def get_key_for_player(self, player_id: int) -> str:
        """Distribute players across available API keys round-robin."""
        if not self.llm_api_keys:
            return ""
        idx = (player_id - 1) % len(self.llm_api_keys)
        return self.llm_api_keys[idx]
