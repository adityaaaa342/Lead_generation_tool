"""Centralized configuration loaded from environment variables / .env file."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings — all values can be overridden via env vars or .env."""

    # ── LLM ──────────────────────────────────────────────────────────
    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="OpenAI-compatible API base URL",
    )
    llm_model: str = Field(
        default="qwen2.5:7b",
        description="Model identifier",
    )
    llm_api_key: str = Field(
        default="ollama",
        description="API key (use 'ollama' for local Ollama)",
    )
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=64)

    # ── Cache ────────────────────────────────────────────────────────
    cache_dir: Path = Field(default=Path("./data"))
    cache_ttl_http: int = Field(default=86400, description="HTTP cache TTL in seconds")
    cache_ttl_lm: int = Field(
        default=604800,
        alias="CACHE_TTL_LLM",
        description="LLM cache TTL in seconds",
    )

    # ── Rate limiting ────────────────────────────────────────────────
    rate_limit_rps: float = Field(default=1.0, gt=0.0)

    # ── Collection ───────────────────────────────────────────────────
    max_leads: int = Field(default=50, ge=1)
    skip_personal_emails: bool = Field(default=False)

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── Misc ─────────────────────────────────────────────────────────
    user_agent: str = Field(
        default="LeadPilot/1.0 (+https://github.com/leadpilot; research)",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


def get_settings(**overrides) -> Settings:
    """Create a Settings instance, optionally overriding values."""
    return Settings(**overrides)


def setup_logging(settings: Settings | None = None) -> None:
    """Configure root logger based on settings."""
    level = (settings or get_settings()).log_level.upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
