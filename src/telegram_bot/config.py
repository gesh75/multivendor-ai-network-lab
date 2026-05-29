"""
config.py — immutable, env-driven configuration for the ChatOps bot.

Loaded once at startup. Missing token is fatal; the chat-ID allowlist is parsed
here so a bad value fails loudly before the bot ever goes online.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .auth import parse_chat_ids

DEFAULT_DCN_API_URL = "http://localhost:5757"


@dataclass(frozen=True)
class BotConfig:
    token: str
    allowed_chat_ids: frozenset[int]
    admin_chat_ids: frozenset[int]
    dcn_api_url: str = DEFAULT_DCN_API_URL
    rate_limit_per_min: int = 20
    request_timeout: float = 30.0
    ask_timeout: float = 120.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BotConfig":
        env = env if env is not None else os.environ
        token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is required (create a bot via @BotFather)"
            )
        return cls(
            token=token,
            allowed_chat_ids=parse_chat_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS")),
            admin_chat_ids=parse_chat_ids(env.get("TELEGRAM_ADMIN_CHAT_IDS")),
            dcn_api_url=(env.get("DCN_API_URL") or DEFAULT_DCN_API_URL).rstrip("/"),
            rate_limit_per_min=int(env.get("TELEGRAM_RATE_LIMIT_PER_MIN", "20")),
            request_timeout=float(env.get("TELEGRAM_REQUEST_TIMEOUT", "30")),
            ask_timeout=float(env.get("TELEGRAM_ASK_TIMEOUT", "120")),
        )
