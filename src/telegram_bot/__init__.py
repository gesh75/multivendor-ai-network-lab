"""
telegram_bot — bi-directional Telegram ChatOps front-end for the DCN Network Tool.

A thin, read-only interface over the existing DCN Flask API (the same endpoints the
MCP server wraps). It does NOT add new network capability — it gives the operator a
fourth way to reach the tools that already exist (web UI, MCP/Claude, alerts → phone).

Design split (keeps the logic testable without Telegram installed):
  config       — immutable settings loaded from the environment
  auth         — allowlist + RBAC + rate limiting (fail-closed)
  dcn_client   — async httpx client for the DCN API
  formatting   — API JSON -> Telegram-safe message text
  bot          — python-telegram-bot wiring (handlers, audit log, error handler)
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
