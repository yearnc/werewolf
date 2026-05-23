"""LLM client abstraction supporting Anthropic and OpenAI APIs."""

from __future__ import annotations

import asyncio
from typing import Optional

from config import Config
from utils import logger


class LLMClient:
    """Async wrapper around Anthropic / OpenAI chat APIs.

    Each instance uses its own API key to allow load distribution across keys.
    """

    def __init__(self, config: Config, api_key: str):
        self.config = config
        self.api_key = api_key
        self.provider = config.llm_provider
        self.model = config.llm_model
        self.temperature = config.llm_temperature
        self.max_tokens = config.llm_max_tokens
        self._anthropic_client = None
        self._openai_client = None

    def _get_anthropic(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._anthropic_client

    def _get_openai(self):
        if self._openai_client is None:
            import openai
            kwargs = {"api_key": self.api_key}
            if self.config.llm_base_url:
                kwargs["base_url"] = self.config.llm_base_url
            self._openai_client = openai.AsyncOpenAI(**kwargs)
        return self._openai_client

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        retries: int = 2,
    ) -> Optional[str]:
        """Send a chat request with retry logic.

        Returns the model's text response, or None on persistent failure.
        """
        for attempt in range(retries + 1):
            try:
                if self.provider == "anthropic":
                    return await self._chat_anthropic(system_prompt, user_message)
                else:
                    return await self._chat_openai(system_prompt, user_message)
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt + 1}/{retries + 1}): {e}")
                if attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def _chat_anthropic(self, system_prompt: str, user_message: str) -> str:
        client = self._get_anthropic()
        response = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def _chat_openai(self, system_prompt: str, user_message: str) -> str:
        client = self._get_openai()
        response = await client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        content = response.choices[0].message.content
        return content or ""
