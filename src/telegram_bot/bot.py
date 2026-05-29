"""
bot.py — python-telegram-bot (v20+/async) wiring for the DCN ChatOps bot.

Thin glue: every handler is wrapped by an auth guard (allowlist + rate limit +
audit log), then calls the async DCNClient and a pure formatter. Long-running
work (notably /ask, which routes through the Qwen3->Claude orchestrator) is run
with concurrent updates enabled and a "working…" placeholder that is edited in
place, so one slow request never blocks the others.

Security posture (see references/best-practices in the package README):
  * fail-closed allowlist on EVERY command,
  * per-chat rate limiting,
  * every command (and every denial) is audit-logged,
  * long-polling — no inbound port or public TLS endpoint required,
  * read-only + diagnose only; no config-push from chat.
"""

from __future__ import annotations

import functools
import logging
from typing import Awaitable, Callable

import httpx
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .auth import RateLimiter, is_authorized
from .config import BotConfig
from .dcn_client import DCNClient, DCNError
from . import formatting as fmt

log = logging.getLogger("dcn.telegram")

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_HELP = (
    "🛰️ *DCN ChatOps*\n"
    "Read-only access to the DCN Network Tool.\n\n"
    "/health — API + lab health\n"
    "/sites — list datacenter sites\n"
    "/devices [filter] — list devices (optional hostname filter)\n"
    "/topo — multivendor topology snapshot\n"
    "/bgp [site] — network-wide BGP session health\n"
    "/incident <ip> — collect incident data for a device\n"
    "/ask <question> — ask the AI orchestrator (Qwen3→Claude)\n"
)

_COMMANDS = [
    BotCommand("health", "API + lab health"),
    BotCommand("sites", "List datacenter sites"),
    BotCommand("devices", "List devices [filter]"),
    BotCommand("topo", "Topology snapshot"),
    BotCommand("bgp", "BGP session health [site]"),
    BotCommand("incident", "Incident data <ip>"),
    BotCommand("ask", "Ask the AI orchestrator <question>"),
    BotCommand("help", "Show help"),
]


class ChatOpsBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.limiter = RateLimiter(config.rate_limit_per_min, 60.0)
        self._dcn: DCNClient | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def build(self) -> Application:
        app = (
            ApplicationBuilder()
            .token(self.config.token)
            .concurrent_updates(True)
            .post_init(self._on_start)
            .post_shutdown(self._on_stop)
            .build()
        )
        app.add_handler(CommandHandler("start", self._guard(self.cmd_help)))
        app.add_handler(CommandHandler("help", self._guard(self.cmd_help)))
        app.add_handler(CommandHandler("health", self._guard(self.cmd_health)))
        app.add_handler(CommandHandler("sites", self._guard(self.cmd_sites)))
        app.add_handler(CommandHandler("devices", self._guard(self.cmd_devices)))
        app.add_handler(CommandHandler("topo", self._guard(self.cmd_topo)))
        app.add_handler(CommandHandler("bgp", self._guard(self.cmd_bgp)))
        app.add_handler(CommandHandler("incident", self._guard(self.cmd_incident)))
        app.add_handler(CommandHandler("ask", self._guard(self.cmd_ask)))
        app.add_error_handler(self._on_error)
        return app

    async def _on_start(self, app: Application) -> None:
        client = httpx.AsyncClient()
        app.bot_data["http"] = client
        self._dcn = DCNClient(
            base_url=self.config.dcn_api_url,
            client=client,
            timeout=self.config.request_timeout,
            ask_timeout=self.config.ask_timeout,
        )
        await app.bot.set_my_commands(_COMMANDS)
        log.info("ChatOps bot online — DCN API %s", self.config.dcn_api_url)

    async def _on_stop(self, app: Application) -> None:
        client = app.bot_data.get("http")
        if client is not None:
            await client.aclose()

    # ── auth guard ───────────────────────────────────────────────────────────
    def _guard(self, handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            chat = update.effective_chat
            chat_id = chat.id if chat else None
            user = update.effective_user
            who = (user.username or user.full_name) if user else "?"
            msg = update.effective_message
            text = (msg.text if msg else "") or ""

            if not is_authorized(chat_id, self.config.allowed_chat_ids):
                log.warning("DENIED chat_id=%s user=%s cmd=%r", chat_id, who, text)
                if msg:
                    await msg.reply_text("⛔ Not authorized for this bot.")
                return
            if not self.limiter.allow(chat_id):
                log.warning("RATELIMIT chat_id=%s user=%s", chat_id, who)
                if msg:
                    await msg.reply_text("⏳ Rate limit reached — try again shortly.")
                return
            log.info("CMD chat_id=%s user=%s cmd=%r", chat_id, who, text)
            await handler(update, context)

        return wrapper

    # ── reply helpers ──────────────────────────────────────────────────────────
    @staticmethod
    async def _send(update: Update, text: str) -> None:
        """Send Markdown, falling back to plain text if Telegram rejects entities."""
        msg = update.effective_message
        if msg is None:
            return
        try:
            await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await msg.reply_text(text)

    # ── command handlers ───────────────────────────────────────────────────────
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send(update, _HELP)

    async def cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._run(update, lambda: self._dcn.health(), fmt.format_health)

    async def cmd_sites(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._run(update, lambda: self._dcn.list_sites(), fmt.format_sites)

    async def cmd_devices(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        search = " ".join(context.args) if context.args else ""
        await self._run(
            update, lambda: self._dcn.list_devices(search=search), fmt.format_devices
        )

    async def cmd_topo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._run(
            update,
            lambda: self._dcn.topology(),
            lambda d: fmt.format_report("Topology", d),
        )

    async def cmd_bgp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        site = context.args[0] if context.args else ""
        await self._run(
            update,
            lambda: self._dcn.report_bgp(site=site),
            lambda d: fmt.format_report("BGP sessions", d),
        )

    async def cmd_incident(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await self._send(update, "Usage: `/incident <device-ip>`")
            return
        ip = context.args[0]
        await self._run(
            update,
            lambda: self._dcn.incident(ip),
            lambda d: fmt.format_report(f"Incident {ip}", d),
        )

    async def cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        prompt = " ".join(context.args) if context.args else ""
        if not prompt.strip():
            await self._send(update, "Usage: `/ask <your question>`")
            return
        msg = update.effective_message
        placeholder = await msg.reply_text("🤖 Thinking… (Qwen3→Claude)")
        try:
            data = await self._dcn.ask(prompt)
            text = fmt.format_ask(data)
        except DCNError as exc:
            text = fmt.format_error(str(exc))
        try:
            await placeholder.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await placeholder.edit_text(text)

    async def _run(
        self,
        update: Update,
        call: Callable[[], Awaitable],
        formatter: Callable[[object], str],
    ) -> None:
        """Execute a DCN call, format the result, reply — turning DCNError into a
        friendly message rather than an unhandled exception."""
        try:
            data = await call()
        except DCNError as exc:
            await self._send(update, fmt.format_error(str(exc)))
            return
        await self._send(update, formatter(data))

    # ── error handler ──────────────────────────────────────────────────────────
    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("Unhandled error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text("⚠️ Internal error — logged.")
            except Exception:  # noqa: BLE001 — never let the error handler raise
                pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = BotConfig.from_env()
    if not config.allowed_chat_ids:
        log.warning(
            "TELEGRAM_ALLOWED_CHAT_IDS is empty — bot will DENY all chats "
            "(fail-closed). Set it to your @userinfobot chat id to enable."
        )
    bot = ChatOpsBot(config)
    app = bot.build()
    log.info("Starting DCN ChatOps bot (long-polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
