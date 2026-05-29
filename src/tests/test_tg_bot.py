"""
test_tg_bot.py — python-telegram-bot wiring layer.

Covers the two things in bot.py worth asserting without a live Telegram:
  1. every expected command is registered on the Application;
  2. the auth guard denies non-allowlisted chats, allows allowlisted ones, and
     enforces the per-chat rate limit — exercised with lightweight fakes so we
     don't need real telegram.Update objects.
"""

import asyncio

from telegram.error import BadRequest

from telegram_bot.bot import ChatOpsBot
from telegram_bot.config import BotConfig
from telegram_bot.dcn_client import DCNError


# ── Lightweight fakes for the guard tests ────────────────────────────────────
class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies: list = []
        self.child: "FakeMessage | None" = None

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        self.child = FakeMessage()
        return self.child

    async def edit_text(self, text, **kwargs):
        self.replies.append(("edit", text))
        return self


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeUser:
    username = "tester"
    full_name = "Test User"


class FakeUpdate:
    def __init__(self, chat_id, text=""):
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser()
        self.effective_message = FakeMessage(text)


def _bot(**env):
    base = {"TELEGRAM_BOT_TOKEN": "123:abc"}
    base.update(env)
    return ChatOpsBot(BotConfig.from_env(base))


class TestHandlerRegistration:
    def test_expected_commands_registered(self):
        app = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1").build()
        names: set[str] = set()
        for group in app.handlers.values():
            for handler in group:
                commands = getattr(handler, "commands", None)
                if commands:
                    names |= set(commands)
        expected = {"start", "help", "health", "devices", "sites",
                    "topo", "bgp", "incident", "ask"}
        assert expected <= names


class TestAuthGuard:
    def test_denies_unauthorized_chat(self):
        bot = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1")
        called: list = []

        async def inner(update, context):
            called.append(True)

        update = FakeUpdate(999, "/health")
        asyncio.run(bot._guard(inner)(update, None))
        assert called == []  # handler never ran
        assert update.effective_message.replies  # a denial was sent

    def test_allows_authorized_chat(self):
        bot = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1")
        called: list = []

        async def inner(update, context):
            called.append(True)

        asyncio.run(bot._guard(inner)(FakeUpdate(1, "/health"), None))
        assert called == [True]

    def test_enforces_rate_limit(self):
        bot = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1", TELEGRAM_RATE_LIMIT_PER_MIN="1")
        calls: list = []

        async def inner(update, context):
            calls.append(True)

        guarded = bot._guard(inner)
        asyncio.run(guarded(FakeUpdate(1, "/health"), None))  # allowed
        asyncio.run(guarded(FakeUpdate(1, "/health"), None))  # blocked
        assert calls == [True]  # only the first ran


# ── Fakes for exercising command handlers without a live DCN API ─────────────
class FakeContext:
    def __init__(self, args=None):
        self.args = args or []


class FakeDCN:
    def __init__(self, **canned):
        self._canned = canned
        self.calls: list = []

    async def health(self):
        self.calls.append("health")
        return self._canned.get("health", {"status": "ok", "devices_loaded": 3})

    async def list_sites(self):
        self.calls.append("sites")
        return self._canned.get("sites", ["DE-FRA"])

    async def list_devices(self, search=""):
        self.calls.append(("devices", search))
        return self._canned.get("devices", [{"hostname": "de-fra-core-01"}])

    async def topology(self):
        self.calls.append("topo")
        return self._canned.get("topo", {"nodes": 2})

    async def report_bgp(self, site=""):
        self.calls.append(("bgp", site))
        return self._canned.get("bgp", {"down_sessions": 0})

    async def incident(self, ip, dtype="junos"):
        self.calls.append(("incident", ip))
        return self._canned.get("incident", {"ok": True})

    async def ask(self, prompt):
        self.calls.append(("ask", prompt))
        return self._canned.get("ask", {"rendered": "all good", "agent": "IncidentAgent"})


class FakeErrorDCN(FakeDCN):
    async def health(self):
        raise DCNError("api down")


class FlakyMessage(FakeMessage):
    """Rejects the first Markdown send (BadRequest), accepts the plain retry."""

    async def reply_text(self, text, **kwargs):
        if "parse_mode" in kwargs:
            raise BadRequest("can't parse entities")
        self.replies.append(text)
        return FakeMessage()


class TestCommandHandlers:
    def _ready_bot(self, dcn=None, **env):
        bot = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1", **env)
        bot._dcn = dcn or FakeDCN()
        return bot

    def test_health_replies_status(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/health")
        asyncio.run(bot.cmd_health(upd, FakeContext()))
        assert any("ok" in str(r).lower() for r in upd.effective_message.replies)

    def test_sites_lists(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/sites")
        asyncio.run(bot.cmd_sites(upd, FakeContext()))
        assert any("DE-FRA" in str(r) for r in upd.effective_message.replies)

    def test_devices_passes_search_filter(self):
        dcn = FakeDCN()
        bot = self._ready_bot(dcn)
        upd = FakeUpdate(1, "/devices core")
        asyncio.run(bot.cmd_devices(upd, FakeContext(["core"])))
        assert ("devices", "core") in dcn.calls

    def test_topo_renders(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/topo")
        asyncio.run(bot.cmd_topo(upd, FakeContext()))
        assert any("Topology" in str(r) for r in upd.effective_message.replies)

    def test_bgp_passes_site(self):
        dcn = FakeDCN()
        bot = self._ready_bot(dcn)
        upd = FakeUpdate(1, "/bgp DE-FRA")
        asyncio.run(bot.cmd_bgp(upd, FakeContext(["DE-FRA"])))
        assert ("bgp", "DE-FRA") in dcn.calls

    def test_incident_requires_ip(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/incident")
        asyncio.run(bot.cmd_incident(upd, FakeContext([])))
        assert any("usage" in str(r).lower() for r in upd.effective_message.replies)

    def test_incident_with_ip_calls_client(self):
        dcn = FakeDCN()
        bot = self._ready_bot(dcn)
        upd = FakeUpdate(1, "/incident 10.0.0.1")
        asyncio.run(bot.cmd_incident(upd, FakeContext(["10.0.0.1"])))
        assert ("incident", "10.0.0.1") in dcn.calls

    def test_ask_requires_prompt(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/ask")
        asyncio.run(bot.cmd_ask(upd, FakeContext([])))
        assert any("usage" in str(r).lower() for r in upd.effective_message.replies)

    def test_ask_edits_placeholder_with_answer(self):
        bot = self._ready_bot()
        upd = FakeUpdate(1, "/ask why is bgp down")
        asyncio.run(bot.cmd_ask(upd, FakeContext(["why", "is", "bgp", "down"])))
        placeholder = upd.effective_message.child
        assert placeholder is not None
        assert any("all good" in str(e) for e in placeholder.replies)

    def test_health_handles_dcn_error_gracefully(self):
        bot = self._ready_bot(FakeErrorDCN())
        upd = FakeUpdate(1, "/health")
        asyncio.run(bot.cmd_health(upd, FakeContext()))
        assert any("api down" in str(r) for r in upd.effective_message.replies)


class TestSendFallback:
    def test_falls_back_to_plain_text_on_bad_request(self):
        bot = _bot(TELEGRAM_ALLOWED_CHAT_IDS="1")
        upd = FakeUpdate(1, "/health")
        upd.effective_message = FlakyMessage()
        asyncio.run(bot._send(upd, "*markdown*"))
        assert "*markdown*" in upd.effective_message.replies
