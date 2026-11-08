"""LLM provider abstraction supporting Anthropic, OpenAI, Groq, and OpenAI-compatible APIs."""

import logging
from typing import Optional

import httpx

from quantix.config import Settings, get_settings

logger = logging.getLogger(__name__)

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMProvider:
    """Unified async client for LLM completions."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_settings()
        self._client = http_client
        self._owns_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate text from selected LLM provider without hardcoded models."""
        provider = self.settings.llm_provider.lower().strip()
        model = self.settings.llm_model.strip()
        api_key = self.settings.get_llm_api_key()

        # If no API key configured, return deterministic fallback summary
        if not api_key:
            logger.info("No LLM API key configured; returning structured template synthesis.")
            fallback = (
                "[LLM Summary simulated: No GROQ_API_KEY / LLM_API_KEY / "
                "OPENAI_API_KEY provided in env]\n"
                f"Summary synthesized from extracted filing data for {model}."
            )
            return fallback

        client = await self._get_client()

        if provider == "anthropic":
            return await self._call_anthropic(client, model, api_key, prompt, system_prompt)

        # Default to OpenAI / Groq / OpenAI-compatible endpoint
        base_url = self.settings.llm_base_url
        if not base_url and provider == "groq":
            base_url = GROQ_DEFAULT_BASE_URL

        return await self._call_openai_compatible(
            client=client,
            model=model,
            api_key=api_key,
            prompt=prompt,
            system_prompt=system_prompt,
            base_url=base_url,
        )

    async def _call_anthropic(
        self,
        client: httpx.AsyncClient,
        model: str,
        api_key: str,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error("Anthropic API error: %d - %s", resp.status_code, resp.text[:200])
            return f"Error communicating with Anthropic API: HTTP {resp.status_code}"

        data = resp.json()
        content_blocks = data.get("content", [])
        text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return "".join(text_parts).strip()

    async def _call_openai_compatible(
        self,
        client: httpx.AsyncClient,
        model: str,
        api_key: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> str:
        effective_base = base_url or self.settings.llm_base_url or "https://api.openai.com/v1"
        url = f"{effective_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 1500,
            "temperature": 0.2,
        }

        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error("API error (%s): %d - %s", effective_base, resp.status_code, resp.text[:200])
            return f"Error communicating with LLM API: HTTP {resp.status_code}"

        data = resp.json()
        choices = data.get("choices", [])
        if choices and "message" in choices[0]:
            return str(choices[0]["message"].get("content", "")).strip()

        return "No text returned from LLM provider."


# Singleton
_llm_instance: Optional[LLMProvider] = None


def get_llm(settings: Optional[Settings] = None) -> LLMProvider:
    global _llm_instance
    if _llm_instance is None or (settings and _llm_instance.settings != settings):
        _llm_instance = LLMProvider(settings=settings)
    return _llm_instance
