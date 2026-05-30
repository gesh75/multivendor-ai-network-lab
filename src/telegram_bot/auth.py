"""
auth.py — authorization and rate limiting for the Telegram ChatOps bot.

Pure, dependency-free logic so it can be unit-tested in isolation and reasoned
about for security. Two principles:

  * Fail closed — an empty allowlist authorizes nobody. A misconfigured bot is a
    silent bot, never an open one.
  * Per-chat rate limiting with an injectable clock so the sliding window is
    deterministic under test.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict


def parse_chat_ids(raw: str | None) -> frozenset[int]:
    """Parse a comma/space separated list of Telegram chat IDs from an env var.

    Group/supergroup IDs are negative, so signs are preserved. Blank entries are
    ignored; a genuinely non-numeric token raises ValueError so a misconfigured
    allowlist fails loudly at startup rather than silently dropping an admin.
    """
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for token in raw.replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError as exc:  # noqa: PERF203 — clarity over micro-perf
            raise ValueError(f"invalid Telegram chat id: {token!r}") from exc
    return frozenset(ids)


def is_authorized(chat_id: int | None, allowed: frozenset[int]) -> bool:
    """True only if chat_id is explicitly allowlisted. Empty allowlist => deny all."""
    if chat_id is None:
        return False
    return chat_id in allowed


def is_admin(chat_id: int | None, admins: frozenset[int]) -> bool:
    """True only if chat_id is in the admin set."""
    if chat_id is None:
        return False
    return chat_id in admins


def summarize_command(text: str, max_args_len: int = 24) -> str:
    """Reduce a raw message to 'command + truncated args' for audit logging.

    Keeps the command verb (e.g. ``/ask``) for auditability but truncates the
    arguments, so a potentially sensitive ``/ask`` prompt is never recorded
    verbatim in the logs.
    """
    text = (text or "").strip()
    if not text:
        return "(empty)"
    parts = text.split(maxsplit=1)
    command = parts[0]
    if len(parts) == 1:
        return command
    args = parts[1]
    if len(args) > max_args_len:
        args = args[:max_args_len] + "…"
    return f"{command} {args}"


class RateLimiter:
    """Sliding-window per-chat rate limiter.

    Allows at most ``max_per_window`` calls per ``window_seconds`` for each chat.
    The clock is injectable to keep tests deterministic (no real sleeping).
    """

    def __init__(
        self,
        max_per_window: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._clock = clock
        self._hits: Dict[int, Deque[float]] = defaultdict(deque)

    def allow(self, chat_id: int) -> bool:
        """Record an attempt; return True if it is within the limit, else False.

        A non-positive ``max_per_window`` disables rate limiting (so a mistyped
        ``TELEGRAM_RATE_LIMIT_PER_MIN=0`` does not silently block every chat)."""
        if self._max <= 0:
            return True
        now = self._clock()
        bucket = self._hits[chat_id]
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True
