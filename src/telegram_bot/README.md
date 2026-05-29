# DCN Telegram ChatOps Bot

A bi-directional Telegram interface for the DCN Network Tool. It is a **thin,
read-only front-end** over the existing Flask/MCP API — it adds no new network
capability, it just gives you a fourth way to reach the tools that already exist
(web UI, MCP/Claude, push alerts) directly from your phone.

> Inspired by the "engineers shouldn't be locked into one interface" idea. Your
> stack already had the web dashboard and the MCP/Claude interface — this fills the
> missing *phone* interface.

## Commands

| Command | Backend endpoint | What it does |
|---|---|---|
| `/health` | `GET /api/health` | API + lab health |
| `/sites` | `GET /api/sites` | List datacenter sites |
| `/devices [filter]` | `GET /api/devices` | List devices (optional hostname filter) |
| `/topo` | `GET /api/mv/topology` | Multivendor topology snapshot |
| `/bgp [site]` | `GET /api/report/bgp` | Network-wide BGP session health |
| `/incident <ip>` | `POST /api/incident` | Collect incident data for a device |
| `/ask <question>` | `POST /api/mv/orchestrator` | Free-text Q&A via the Qwen3→Claude orchestrator |
| `/help` | — | Show help |

## Run it

```bash
# 1. Install deps (opt-in; not pulled in by the main DCN app)
python -m venv .venv && source .venv/bin/activate
pip install -r telegram_bot/requirements.txt

# 2. Configure
cp telegram_bot/.env.example telegram_bot/.env
#    edit: TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS (your @userinfobot id)
set -a && source telegram_bot/.env && set +a

# 3. Run (long-polling — no inbound port / public TLS needed)
python -m telegram_bot.bot
```

The DCN API must be reachable at `DCN_API_URL` (default `http://localhost:5757`).

## Security model

- **Fail-closed allowlist** on every command — an empty `TELEGRAM_ALLOWED_CHAT_IDS`
  denies everyone. Group IDs (negative) are supported.
- **Per-chat rate limiting** (sliding window).
- **Audit logging** — every command and every denial is logged (chat id, user,
  command), consistent with the GAIT/AEGIS evidence ethos.
- **Long-polling**, not webhooks — no inbound firewall port, no public TLS cert.
- **Read + diagnose only.** No config push from chat by design. A future
  `/preflight` should *trigger* an AEGIS run but still require the human authorize
  step in the web UI — never seal a change from a phone tap.
- Keep the token in `.env` (never commit it) and **rotate** it periodically.

> ⚠️ **Air-gap boundary:** Telegram relays messages through Telegram's cloud. This
> is fine for the lab/DCN observability tier, but it must **not** carry a regulated
> air-gapped AEGIS customer's topology/config — that would break AEGIS's "no egress
> ever" promise. For that tier, keep it dashboard-only or use self-hosted Matrix.

## Architecture (testable split)

```
config.py      immutable env-driven settings (token, allowlist, timeouts)
auth.py        parse_chat_ids / is_authorized / is_admin / RateLimiter   (pure)
dcn_client.py  async httpx client over the DCN API (DCNError normalisation)
formatting.py  API JSON -> Telegram-safe text (length-capped, defensive)  (pure)
bot.py         python-telegram-bot wiring: guard + handlers + audit + errors
```

`auth`, `config`, `dcn_client`, and `formatting` carry no Telegram dependency, so
the logic is unit-tested without it. See `../tests/test_tg_*.py` (65 tests, 88%
coverage; auth/config 100%).

## Tests

```bash
pip install pytest pytest-cov httpx
pytest tests/test_tg_*.py --cov=telegram_bot --cov-report=term-missing
```

## References (best practices applied)

- python-telegram-bot docs/architecture — async `Application`, modular handlers.
- "Building Robust Telegram Bots" — async, edit-in-place UX, env config.
- Telegram bot access control (Advanced Web Machinery) & Home Assistant ACL —
  allowlisting chat IDs.
- BAZU "How to secure a Telegram bot" — token hygiene, rotation, rate limiting.
- TechTarget "ChatOps to automate network tasks" — start read-only, fixed commands.
- Ported patterns: nautobot-chatops (dispatcher), telegram-ha-monitor (RBAC),
  telegram-librenms-bot (self-monitoring).
