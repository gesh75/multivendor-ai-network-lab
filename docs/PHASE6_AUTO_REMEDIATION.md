# Phase 6 — Event-Initiated Auto-Remediation (A–E, complete)

> Closes the last gap in the AI-SRE loop: a **detected anomaly auto-triggers the existing
> closed-loop change pipeline**, risk-gated. LOW-risk events execute with no human button
> press; MEDIUM/HIGH queue for one-click operator approval; CRIT pages out and never
> auto-acts. Phase 6 ships as five sub-items **A** through **E** — all done.

```
anomaly ──match(auto.yaml)──▶ runbook ──risk_tier──▶ ┌ LOW          → execute now
 (/api/anomaly/detect                                ├ MEDIUM/HIGH  → queue → one-click approve/decline
  ADTK z-score / flap)                               └ CRIT         → webhook page-out (never auto-acts)
                                                          │
                                                          ▼
                              config → POST /api/change/closed-loop (6-stage, auto-rollback)
                              exec/collect → device command path
```

| Item | What | Status |
|---|---|---|
| **A** | Auto-remediate engine + background poll loop (`src/auto_remediate.py`) | ✅ done |
| **B** | 8-runbook catalog (`src/runbooks/auto.yaml`) — anomaly→remediation + risk tiers | ✅ done |
| **C** | UI "Auto-Remediation Queue" tab with per-action Approve/Decline (`demo/index.html`) | ✅ done |
| **D** | 6 API endpoints behind the global `X-API-Key` gate | ✅ done |
| **E** | 5 `mv_auto_*` MCP tools (`src/mcp_dcn_server.py`) | ✅ done |

---

## A / B / D — engine, runbooks, endpoints (with the security hardening)

### Files

| File | Role |
|---|---|
| `src/runbooks/auto.yaml` | Runbook catalog — 8 anomaly→remediation mappings + risk-tier floors (item **B**) |
| `src/auto_remediate.py` | Engine: load · normalize · match · fill · tier · decide · execute · queue · loop · blueprint (items **A** + **D**) |
| `src/tests/test_auto_remediate.py` | 27 unit + endpoint tests (`cd src && python tests/test_auto_remediate.py`, or via the repo `venv` + pytest) |
| `src/app.py` | Fail-safe registration block + the global `X-API-Key` `before_request` gate (`[AUTO-REMEDIATE] …` on boot) |

### Risk model

`risk_tier` in `auto.yaml` is a **floor**. The engine escalates it with Blast-Radius BFS
(`/api/batfish/blast-radius`): ≥3 downstream devices → +1 tier, ≥8 → +2, capped at CRIT.
It **never demotes** below the floor.

| Tier | Behavior |
|---|---|
| `LOW` | Auto-execute immediately |
| `MEDIUM` / `HIGH` | Queue `pending_approval` → one-click `approve` / `decline` |
| `CRIT` | GAIT entry + webhook page-out; **never auto-acts** |

A config runbook whose template still has unresolved `{placeholders}` is parked
`needs_enrichment` and is **never fired half-filled**, regardless of tier.

### Action-record status enum

`mv_auto_queue` / `/api/auto-remediate/queue` records carry one of:

`pending_approval` · `auto_executed` · `needs_enrichment` · `paged` · `declined` ·
`rejected_invalid_field` · `execute_failed`

### Endpoints (item D)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/auto-remediate/status` | open | loop health, action counts by status |
| GET | `/api/auto-remediate/queue?limit=N` | open | recent + pending actions (top-level key `actions`, newest-first; `ts` is epoch **seconds**) |
| GET | `/api/auto-remediate/runbook` | open | loaded catalog summary (8 runbooks) — note the **singular** path |
| POST | `/api/auto-remediate/approve/<id>` | **X-API-Key** | approve a queued MED/HIGH action → execute |
| POST | `/api/auto-remediate/decline/<id>` | **X-API-Key** | decline + GAIT reason |
| POST | `/api/auto-remediate/simulate` | **X-API-Key** + `MVLAB_AUTO_REMEDIATE_SIMULATE=1` | inject a synthetic anomaly (debug/demo) — **OFF by default** |

> **Auth env var:** the Flask app's `X-API-Key` gate reads **`MVLAB_API_KEY`** (see the
> security model below). The earlier draft of this doc referenced `DCN_API_KEY` for the app
> gate — that was env-var rot; the app gate is `MVLAB_API_KEY`. (`DCN_API_KEY` is a
> *separate* secret used only by the stdio MCP process — see Item E.)

---

## Security model (A / B / D defense-in-depth)

Three independent controls protect the auto-remediation surface. Each was verified against
the on-disk code on 2026-05-31.

### 1. `simulate` is gated OFF by default (env-gated debug surface)

`/api/auto-remediate/simulate` accepts an **arbitrary anomaly body**, so it is an
arbitrary-anomaly execution surface. It is only registered when
`MVLAB_AUTO_REMEDIATE_SIMULATE=1` (`src/auto_remediate.py`), and even then it still sits
behind the `X-API-Key` gate. Real operation never needs it — anomalies arrive from
`/api/anomaly/detect`. The Phase 6E MCP tools **deliberately do not wrap `/simulate`**.

### 2. `valid_field()` per-placeholder whitelist (command-injection defense, layer 1)

`valid_field(name, value)` (`src/auto_remediate.py:137`) is the **single** injection guard,
defined once and reused in `evaluate()` against **every** `{placeholder}` value
(`interface`, `peer_ip`, `asn`, `expected`, `host`, …) before it is substituted into any
config/command payload. It rejects control characters, shell/config metacharacters, and
malformed IPs. A failing value parks the action `rejected_invalid_field` — it is **never
executed**, even from an untrusted source — and the injected content is never surfaced in
`rec["payload"]`. There is no second/parallel validator: one guard, reused everywhere.

### 3. Audit-integrity status guards on approve **and** decline (defense-in-depth, layer 2)

Both approval verbs refuse to act on a record that is not awaiting a verdict:

* `approve()` (`src/auto_remediate.py:262`) only proceeds when
  `rec["status"] in ("pending_approval", "needs_enrichment")`; otherwise returns
  `{"error": "not approvable (status=…)"}`.
* `decline()` (`src/auto_remediate.py:277`) was previously **missing** this guard — it
  overwrote *any* status to `declined`, letting a confused-deputy decline rewrite the status
  of an already-executed / paged / injection-rejected record (an audit-integrity defect).
  Phase 6 adds the mirrored guard (line 285): decline only proceeds when
  `rec["status"] in ("pending_approval", "needs_enrichment", "pending")`; otherwise returns
  `{"error": "not declinable (status=…)"}` and **leaves the record untouched**.

So a declined run can never be subsequently approved/executed, and an executed/paged run can
never be silently rewritten to `declined`.

### 4. Untrusted decline-reason coercion + cap at the route boundary

The decline reason is operator free text that is stored in the record, written to the GAIT
audit log, and later rendered in the UI. The Flask decline route now treats the body as
untrusted and coerces + caps it before it reaches the engine
(`src/auto_remediate.py`, decline route):

```python
reason = str(body.get("reason", ""))[:500]
return jsonify(remediator.decline(action_id, reason))
```

This guarantees a string, bounds its length to 500 chars, and matches the untrusted-input
discipline already used for placeholder values. The **approve** route is intentionally
body-less and hardcodes `actor="mcp-approved"` — there is no operator-attribution body to
inject through.

### 5. Sanctioned `runbook_exec` path + honest GAIT (2026-06-12)

LOW-tier exec runbooks (`bgp_flap_reset` → `clear bgp * soft`,
`interface_error_spike` → `clear counters {interface}`) auto-execute through
`_ar_run_exec` → `POST /api/run`. The interactive `/api/run` guard
(`is_command_blocked`) still **403s** any `clear …` for normal callers.

An authenticated caller may set `"runbook_exec": true`. That flag only unlocks
this operational allowlist (`is_runbook_exec_allowed` in `src/app.py`):

```
clear bgp … | clear counters… | clear ip bgp … | clear ipv6 bgp …
```

`configure` / `set` / `delete` / `commit` / `request system` / `file` stay
blocked even **with** the flag. The interactive UI never sends the flag.

Audit integrity: `_ar_run_exec` now surfaces non-2xx **and** `success: false`
as `{ok: false, …}`. `_execute()` uses `exec_failed()`; on failure it writes
status `execute_failed` and a GAIT verdict **`failed`** — never `executed`.
The exception path also logs `failed`. Tests:
`src/tests/test_auto_remediate_run_audit.py`.

```bash
# sanctioned (already past X-API-Key; auto-remediate engine does this)
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"hostname":"de-fra-core-01","raw":"clear bgp * soft","runbook_exec":true}' \
  http://127.0.0.1:5757/api/run

# interactive caller, no flag → 403
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"hostname":"de-fra-core-01","raw":"clear bgp * soft"}' \
  http://127.0.0.1:5757/api/run
```

### 6. Single global `X-API-Key` gate (no per-route auth, no double-gating)

`src/app.py` carries a global `before_request` gate (`src/app.py:111`) that protects **every
non-GET/HEAD/OPTIONS** request via `_is_protected_request()` (`src/app.py:102`). It:

* reads the shared secret from **`MVLAB_API_KEY`** (`src/app.py:96`),
* is **fail-closed**: if `MVLAB_API_KEY` is unset, protected routes return **503**,
* compares the supplied `X-API-Key` with `hmac.compare_digest` (timing-safe), returning
  **403** on mismatch.

Because this gate already covers `approve`, `decline`, and `simulate` (all POST), **no
per-route decorator was added** — a second gate would risk double-gating bugs. The open GET
reads (`status` / `queue` / `runbook`) are intentionally unauthenticated read-only surfaces.

> **Two-secret rule (never cross-wire):** the Flask **app** gate uses `MVLAB_API_KEY`; the
> stdio **MCP** process uses `DCN_API_KEY` (different process, different env var — see Item E).

---

## C — operator Approve/Decline queue UI

A new dashboard tab in `demo/index.html` surfaces the pending queue and gives the operator
one-click Approve/Decline. It is **collision-free** and kept strictly distinct from the
unrelated Day-5/6 `auto-remediate` tab (which drives `/api/mv/remediation/*`).

### Tab + panel

* **Tab pill:** `data-tab="auto-remediate-queue"` (label "Auto-Remediation Queue", P6 tag),
  placed in the `#tabs` strip next to the existing Day-5/6 pill.
* **Panel:** `id="tab-auto-remediate-queue"` (the `tab-` + `data-tab` id convention is
  auto-handled by `switchTab` / `switchTabById` — no tab-machinery change).
* **Stat tiles** bound to `/status` `by_status`:
  `pending_approval` (amber) · `auto_executed` (green) · `needs_enrichment` (accent) ·
  `declined` / `paged` / `rejected` / `failed` (red).
* **Empty-state placeholder** that teaches the flow even with an empty queue:
  `anomaly → runbook → risk-tier gate → approve / decline`.
* **Scroll body:** `id="arq-out"`, JS prefix `arq*`.

### JS contract (`arq*` handlers, all exported on `window`)

`window.arqRefresh` · `window.arqApprove` · `window.arqDecline` — the operator behavior:

1. **Escapes every server string** with `escapeHtmlSafe()` (payload/config/command text is
   an XSS sink; also host, runbook, anomaly_type, metric, decline_reason, id, status,
   missing/invalid fields) before injecting into `arq-out.innerHTML`.
2. **Renders Approve/Decline buttons only when `status === "pending_approval"`** — terminal
   and parked statuses get a plain colored label, so the UI never offers an action the
   backend would reject.
3. **`X-API-Key` auto-injects** via the existing `attachApiKey()` wrapper for any `/api/`
   URL (read from `localStorage["MVLAB_API_KEY"]`). The key is never hardcoded.
4. **LIVE-gated** — when the global `LIVE` flag is off, the panel shows a
   "requires LIVE mode" placeholder instead of calling the backend.
5. **In-flight feedback** — the clicked button is disabled and shows a loading label, then on
   success the panel re-calls `/queue` (there is **no** get-single-action endpoint in Phase 6;
   the UI never polls `/get/<id>`).
6. `ts` is epoch **seconds** → `*1000` for `new Date()`. The queue's top-level key is
   `actions` (not `proposals`). Tiles read from `status.by_status`.
7. Decline prompts for an optional reason and POSTs `{reason}` (the backend caps it at 500).

### API usage examples (curl)

```bash
# read the key from the local .env (never echo it into a committed file)
KEY=$(grep ^MVLAB_API_KEY= .env | cut -d= -f2-)
BASE=http://localhost:5757

# 1) open read surfaces (no key needed)
curl -s "$BASE/api/auto-remediate/status"   | jq '{ticks,last_tick_ts,runbooks_loaded,by_status}'
curl -s "$BASE/api/auto-remediate/queue?limit=5" | jq '.actions[] | {id,host,runbook,risk_tier,status}'
curl -s "$BASE/api/auto-remediate/runbook"  | jq 'length'   # 8

# 2) approve a pending action (X-API-Key required; body ignored, actor is server-set)
curl -s -X POST -H "X-API-Key: $KEY" \
  "$BASE/api/auto-remediate/approve/ar-0123456789" | jq '.status'   # -> auto_executed | execute_failed

# 3) decline a pending action with a reason (reason coerced to str + capped to 500)
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"reason":"superseded by maintenance window MW-4471"}' \
  "$BASE/api/auto-remediate/decline/ar-0123456789" | jq '{status,decline_reason}'

# gate behavior: missing/invalid key on a POST -> 403 (503 if MVLAB_API_KEY is unset server-side)
```

---

## E — the 5 `mv_auto_*` MCP tools (total now 68)

Five new `@mcp.tool()` functions were added to `src/mcp_dcn_server.py` under a
`# ── Phase 6E: Event-Initiated Auto-Remediation ──` banner, inserted between
`mv_device_health` and the `__main__` block. They mirror the existing tool conventions
exactly: **GET tools return the raw `_get(...)` string; POST tools return
`json.dumps(_post(...))`.** Auth auto-attaches via `_auth_headers()` from the MCP process's
`DCN_API_KEY` env var — no secret is hardcoded.

| Tool | Signature | Calls | Returns |
|---|---|---|---|
| `mv_auto_status` | `() -> str` | `GET /api/auto-remediate/status` | raw `_get` string |
| `mv_auto_queue` | `(limit: int = 50) -> str` | `GET /api/auto-remediate/queue` `{"limit": str(limit)}` | raw `_get` string |
| `mv_auto_runbooks` | `() -> str` | `GET /api/auto-remediate/runbook` (singular) | raw `_get` string |
| `mv_auto_approve` | `(action_id: str) -> str` | `POST /api/auto-remediate/approve/<id>` `{}` | `json.dumps(_post(...))` |
| `mv_auto_decline` | `(action_id: str, reason: str = "") -> str` | `POST /api/auto-remediate/decline/<id>` `{"reason": reason}` | `json.dumps(_post(...))` |

Design notes:

* `mv_auto_queue` casts `limit` to `str()` because the `_get` query-string builder does not
  URL-encode; this matches every other GET tool and avoids touching the shared helper.
* `mv_auto_runbooks` uses the **singular** `/api/auto-remediate/runbook` path.
* `mv_auto_approve` **omits** an `actor` parameter — the route hardcodes
  `actor="mcp-approved"` and ignores the body, so the tool posts an empty `{}`.
* `/simulate` is **not** wrapped (debug-only, env-gated, arbitrary-anomaly surface).
* The docstrings are the LLM-facing descriptions and enumerate the status and risk-tier
  enums so the model picks the right action.

### Tool count: 68 documented, 69 on disk

* Documented baseline was **63** tools (Phase 5). Adding the 5 Phase 6E tools = **68
  documented** — the project headline.
* On disk there are exactly **69** `@mcp.tool()` decorators. The extra one is
  `mv_device_health`, added *after* the docs last stated 63 (post-Phase-5). No real tool was
  dropped to force the count to 68 — that would be a silent functionality regression.
* Each of the 5 new `mv_auto_*` defs appears exactly once
  (`src/mcp_dcn_server.py:511,517,523,529,535`).

### MCP usage example (LLM tool calls)

```text
# inspect the queue
mv_auto_status()                          -> "{ \"ticks\":…, \"runbooks_loaded\":8, \"by_status\":{…} }"
mv_auto_queue(limit=10)                    -> "{ \"actions\":[ {id,host,runbook,risk_tier,status}, … ] }"
mv_auto_runbooks()                         -> "[ {id,description,risk_tier,action_type}, … ]"   # 8 entries

# act on a pending action (DCN_API_KEY auto-attached by _auth_headers())
mv_auto_approve(action_id="ar-0123456789")
mv_auto_decline(action_id="ar-0123456789", reason="not in approved change window")
```

To register the 5 new tools with an MCP client, **re-launch the stdio MCP server / reconnect
the client** (e.g. restart Claude Desktop). No running web service is touched, and `:5757`
must **not** be restarted — a restart drops the in-memory `pending_approval` queue.

---

## Verification (read-only, no service restart)

* `py_compile` clean on the 3 edited Python files (`mcp_dcn_server.py`, `auto_remediate.py`,
  and the two bind files) plus the test files.
* `grep -c '@mcp.tool()' src/mcp_dcn_server.py` → **69**; each `mv_auto_*` name appears once.
* HTML structure: exactly one `data-tab="auto-remediate-queue"` pill and one
  `id="tab-auto-remediate-queue"` panel; every `arq*` onclick has a matching `window.arq*`
  export.
* **34/34 tests pass** via the repo `venv`:
  `venv/bin/python -m pytest src/tests/test_auto_remediate.py src/tests/test_mcp_auto_tools.py -q`
  (27 in `test_auto_remediate.py` — original 17 + 10 new: decline status-guard ×4,
  reason cap/coerce ×2, X-API-Key gate ×4; plus 7 hermetic MCP smoke tests).

### Security scan verdict (already-pushed public range)

A read-only secret scan of the already-pushed Phase 6 + hardening commit range on the public
mirror found **no secrets** — no API keys, tokens, passwords, or `.env` content. All key
material is read from environment variables (`MVLAB_API_KEY` / `DCN_API_KEY` via
`os.environ`). Two non-secret follow-ups were flagged (an "AEGIS"-naming mention in one
commit message, and lab hostnames in test fixtures) — see `SECURITY_HARDENING.md`.

## Architecture note

The engine is dependency-injected (`auto_remediate.Deps`) so the pure logic unit-tests with
zero Flask/network/InfluxDB dependency; `app.py` injects the real implementations (in-process
HTTP to the closed-loop / anomaly / blast-radius endpoints with the API key, `_agent_emit`
for the agent log, `vendor_canonical` lookup from `DEVICES`).
