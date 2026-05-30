"""
test_tg_auth.py — Telegram ChatOps bot: authorization + rate limiting.

Security-critical pure logic (no Telegram, no network). These are the gates that
decide who may talk to the bot and how often, so they get exhaustive coverage,
including the fail-closed default (empty allowlist denies everyone).
"""

import pytest

from telegram_bot.auth import (
    parse_chat_ids,
    is_authorized,
    is_admin,
    RateLimiter,
    summarize_command,
)


class TestParseChatIds:
    def test_parses_comma_separated(self):
        assert parse_chat_ids("123,456,789") == frozenset({123, 456, 789})

    def test_handles_spaces_and_trailing_comma(self):
        assert parse_chat_ids(" 123 , 456 , ") == frozenset({123, 456})

    def test_none_returns_empty(self):
        assert parse_chat_ids(None) == frozenset()

    def test_blank_string_returns_empty(self):
        assert parse_chat_ids("   ") == frozenset()

    def test_negative_group_ids_allowed(self):
        # Telegram group/supergroup chat IDs are negative.
        assert parse_chat_ids("-1001234567890") == frozenset({-1001234567890})

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError):
            parse_chat_ids("123,not-an-id")


class TestIsAuthorized:
    def test_member_allowed(self):
        assert is_authorized(123, frozenset({123, 456})) is True

    def test_non_member_denied(self):
        assert is_authorized(999, frozenset({123})) is False

    def test_empty_allowlist_fails_closed(self):
        # The most important security default: no allowlist => nobody is allowed.
        assert is_authorized(123, frozenset()) is False

    def test_none_chat_id_denied(self):
        assert is_authorized(None, frozenset({123})) is False


class TestIsAdmin:
    def test_admin(self):
        assert is_admin(1, frozenset({1})) is True

    def test_not_admin(self):
        assert is_admin(2, frozenset({1})) is False

    def test_none_denied(self):
        assert is_admin(None, frozenset({1})) is False


class TestRateLimiter:
    def test_allows_up_to_limit(self):
        clock = [1000.0]
        rl = RateLimiter(max_per_window=3, window_seconds=60, clock=lambda: clock[0])
        assert [rl.allow(7) for _ in range(3)] == [True, True, True]

    def test_blocks_over_limit(self):
        clock = [1000.0]
        rl = RateLimiter(3, 60, clock=lambda: clock[0])
        for _ in range(3):
            rl.allow(7)
        assert rl.allow(7) is False

    def test_window_slides(self):
        clock = [1000.0]
        rl = RateLimiter(2, 60, clock=lambda: clock[0])
        rl.allow(7)
        rl.allow(7)
        assert rl.allow(7) is False
        clock[0] += 61  # advance past the window
        assert rl.allow(7) is True

    def test_per_chat_isolation(self):
        clock = [1000.0]
        rl = RateLimiter(1, 60, clock=lambda: clock[0])
        assert rl.allow(1) is True
        assert rl.allow(2) is True  # different chat is unaffected
        assert rl.allow(1) is False


class TestRateLimiterMisconfiguration:
    """Sourcery #2: a non-positive limit must not silently block everyone.

    Treat max_per_window <= 0 as 'no rate limit' (e.g. a mistyped
    TELEGRAM_RATE_LIMIT_PER_MIN=0 should not brick the bot)."""

    def test_zero_means_unlimited(self):
        clock = [1000.0]
        rl = RateLimiter(0, 60, clock=lambda: clock[0])
        assert all(rl.allow(1) for _ in range(50))

    def test_negative_means_unlimited(self):
        rl = RateLimiter(-5, 60)
        assert rl.allow(1) is True
        assert rl.allow(1) is True


class TestSummarizeCommand:
    """Sourcery re-review #3: audit logs keep the command but truncate args
    so sensitive /ask prompts aren't recorded verbatim."""

    def test_command_only(self):
        assert summarize_command("/health") == "/health"

    def test_short_args_kept(self):
        assert summarize_command("/bgp DE-FRA") == "/bgp DE-FRA"

    def test_long_args_truncated(self):
        out = summarize_command("/ask " + "x" * 100, max_args_len=10)
        assert out.startswith("/ask ")
        assert out.endswith("…")
        assert len(out) < 30

    def test_empty_text(self):
        assert summarize_command("") == "(empty)"
        assert summarize_command("   ") == "(empty)"
