"""
test_tg_config.py — immutable env-driven configuration for the ChatOps bot.

Config is the boundary where misconfiguration must fail loudly (no token => no
bot) and where the security-relevant allowlist is parsed.
"""

import pytest

from telegram_bot.config import BotConfig


def test_from_env_minimal_parses_token_and_allowlist():
    cfg = BotConfig.from_env(
        {"TELEGRAM_BOT_TOKEN": "abc:123", "TELEGRAM_ALLOWED_CHAT_IDS": "1,2"}
    )
    assert cfg.token == "abc:123"
    assert cfg.allowed_chat_ids == frozenset({1, 2})
    assert cfg.dcn_api_url == "http://localhost:5757"  # default


def test_token_is_required():
    with pytest.raises(ValueError):
        BotConfig.from_env({})


def test_trailing_slash_stripped_from_api_url():
    cfg = BotConfig.from_env(
        {"TELEGRAM_BOT_TOKEN": "t", "DCN_API_URL": "http://x:5757/"}
    )
    assert cfg.dcn_api_url == "http://x:5757"


def test_admins_and_rate_limit_parsed():
    cfg = BotConfig.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ADMIN_CHAT_IDS": "9",
            "TELEGRAM_RATE_LIMIT_PER_MIN": "5",
        }
    )
    assert cfg.admin_chat_ids == frozenset({9})
    assert cfg.rate_limit_per_min == 5


def test_config_is_immutable():
    cfg = BotConfig.from_env({"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(Exception):
        cfg.token = "tampered"  # frozen dataclass -> FrozenInstanceError
