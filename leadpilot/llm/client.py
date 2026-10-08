"""OpenAI-compatible LLM client with caching, retry, and JSON validation."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from leadpilot.config import Settings, get_settings
from leadpilot.storage.cache import LLMCache

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Wrapper around an OpenAI-compatible API with caching and structured output."""

    def __init__(self, settings: Settings | None = None, cache: LLMCache | None = None):
        self.settings = settings or get_settings()
        self.client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
        )
        self._cache = cache

    @property
    def cache(self) -> LLMCache:
        if self._cache is None:
            self._cache = LLMCache(self.settings.cache_dir / "llm_cache.db")
        return self._cache

    def _cache_key(self, messages: list[dict], model: str) -> str:
        """Deterministic hash of the request for caching."""
        payload = json.dumps({"messages": messages, "model": model}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _raw_completion(self, messages: list[dict]) -> str:
        """Send a chat completion request (with retry on transient failures)."""
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
        )
        return response.choices[0].message.content or ""

    def complete(self, messages: list[dict], use_cache: bool = True) -> str:
        """Get a text completion, using cache if available."""
        key = self._cache_key(messages, self.settings.llm_model)

        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                logger.debug("LLM cache hit for key %s", key[:12])
                return cached

        result = self._raw_completion(messages)

        if use_cache:
            self.cache.set(key, result, ttl=self.settings.cache_ttl_lm)

        return result

    def complete_json(
        self,
        messages: list[dict],
        response_model: Type[T],
        use_cache: bool = True,
    ) -> T:
        """Get a structured JSON response validated against a Pydantic model.

        On validation failure, sends the error back to the LLM for one retry.
        """
        raw = self.complete(messages, use_cache=use_cache)

        # Attempt 1: parse
        try:
            return self._parse_json_response(raw, response_model)
        except (ValidationError, json.JSONDecodeError, ValueError) as first_err:
            logger.warning(
                "LLM JSON parse failed (attempt 1): %s — retrying with error feedback",
                first_err,
            )

        # Attempt 2: send error back to LLM and ask for correction
        schema_str = json.dumps(response_model.model_json_schema(), indent=2)
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"Your previous response could not be parsed as valid JSON "
                    f"matching this schema:\n```json\n{schema_str}\n```\n\n"
                    f"Error: {first_err}\n\n"
                    f"Please respond with ONLY valid JSON matching the schema above. "
                    f"No markdown fences, no explanation — just the JSON object."
                ),
            },
        ]

        raw_retry = self.complete(retry_messages, use_cache=False)
        return self._parse_json_response(raw_retry, response_model)

    @staticmethod
    def _parse_json_response(raw: str, model: Type[T]) -> T:
        """Extract JSON from LLM response and validate against Pydantic model."""
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Try to find JSON object or array
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in response: {text[:200]}")

        json_str = text[start:end]
        data = json.loads(json_str)
        return model.model_validate(data)
