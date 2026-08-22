# Changelog

All notable changes to the DCN / AI Network Tool (`multivendor-ai-network-lab`) are recorded
here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/); dates are
`YYYY-MM-DD`.

## [Unreleased] — 2026-06 → 2026-08

Documentation pass against code that landed after Phase 6. No behavior change
in this section — see the linked commits for the runtime fixes.

### Added (code, already on `main`)
- **Lab B on Ubuntu/Linux** (`91a6644`) — `setup.sh` / `deploy.sh` / `destroy.sh`
  detect OS: native `containerlab` on Linux, `ghcr.io/srl-labs/clab` + `--pid host`
  on macOS. Shared runners in `containerlab-multivendor/scripts/clab-common.sh`.
- **CLI corpus extraction kit** (`beab1f4`) — `scripts/fetch_sources.sh` +
  `scripts/parse_vendor_docs.py`. Cisco IOS MCL (~17,962) and Nokia SR OS (42,
  `os=sros`) extractors validated and merged.
- **cEOS eAPI in startup-config** (`66f54b6`) — `leaf1` / `leaf4` / `spine2`
  enable `management api http-commands` (HTTPS:443) so NAPALM works after a
  clean deploy.

### Changed (code, already on `main`)
- **YubiKey PIN fail-fast** (`2030b3e`) — `DCN_PKCS11_PIN` has no default;
  unset PIN raises in `_pkcs11_init()` and boot falls back to key mode.
- **Honest auto-remediate audit** (`d3a8d72`) — `/api/run` accepts
  `runbook_exec: true` for allowlisted operational `clear` commands;
  failures record `execute_failed` / GAIT `failed`, never a false `executed`.

### Docs (this PR)
- Env + security: `.env.example`, `docs/SECURITY_HARDENING.md`, `src/README.md`.
- Phase 6: `docs/PHASE6_AUTO_REMEDIATION.md`, `docs/PHASE_6_AUTO_REMEDIATE.md`.
- Lab B ops: `docs/BUILD_YOUR_OWN_LAB.md`, `docs/CLOS_EVPN_MACOS_DEPLOY.md`,
  `containerlab-multivendor/{README,EVPN_RUNBOOK}.md`, `CLAUDE.md`.
- Health + corpus: `docs/HEALTH_ENDPOINT.md` (SRL table, correct spine hostnames),
  `docs/CLI_CORPUS_README.md`, `docs/CHANGE_PIPELINE.md` (eAPI vs docker-exec).

## [Phase 6 — Event-Initiated Auto-Remediation] — 2026-05-31

Phase 6 sub-items **C** and **E** finished, plus backend audit-integrity hardening, network-
bind hardening, and a public-push secret scan. A/B/D shipped earlier in Phase 6.

### Added
- **Phase 6 C — Auto-Remediation Queue UI tab** (`demo/index.html`). New
  `data-tab="auto-remediate-queue"` pill + `id="tab-auto-remediate-queue"` panel with
  `by_status` stat tiles and an empty-state that teaches the
  `anomaly → runbook → risk-tier gate → approve/decline` flow. `arq*` JS handlers
  (`window.arqRefresh/arqApprove/arqDecline`) consume `GET /api/auto-remediate/{status,queue}`
  and `POST /api/auto-remediate/{approve,decline}/<id>`. Every server string is escaped via
  `escapeHtmlSafe()`; Approve/Decline render **only** for `status === "pending_approval"`;
  LIVE-gated; re-fetches `/queue` after an action. Kept collision-free and distinct from the
  unrelated Day-5/6 `auto-remediate` tab.
- **Phase 6 E — 5 `mv_auto_*` MCP tools** (`src/mcp_dcn_server.py`): `mv_auto_status`,
  `mv_auto_queue(limit)`, `mv_auto_runbooks`, `mv_auto_approve(action_id)`,
  `mv_auto_decline(action_id, reason)`. GET tools return the raw `_get` string; POST tools
  return `json.dumps(_post(...))`. Auth via the MCP process's `DCN_API_KEY` (separate from the
  Flask app's `MVLAB_API_KEY`). **68 documented** tools (63 baseline + 5); **69** `@mcp.tool()`
  on disk (the +1 is `mv_device_health`, added post-Phase-5 — no tool was dropped).
- New tests: `src/tests/test_mcp_auto_tools.py` (7 hermetic MCP smoke tests) and 10 new tests
  in `src/tests/test_auto_remediate.py`. **34/34** pass via the repo `venv`.
- Docs: `docs/PHASE6_AUTO_REMEDIATION.md` (full A–E story + security model + API/MCP examples)
  and `docs/SECURITY_HARDENING.md` (bind rationale + secret-scan verdict).

### Changed (security hardening)
- **Decline audit-integrity status guard** (`src/auto_remediate.py:285`): `decline()` now
  mirrors `approve()` and only acts on `pending_approval` / `needs_enrichment` / `pending`
  records; otherwise returns `{"error": "not declinable (status=…)"}` and leaves the record
  untouched. Closes a gap where a decline could rewrite the status of an already-executed /
  paged / injection-rejected record. **Behavior change** — flagged for reviewer sign-off.
- **Untrusted decline-reason coercion + cap** (decline Flask route): `reason =
  str(body.get("reason", ""))[:500]` before reaching the engine, GAIT log, and UI.
- **Loopback bind hardening** of `:5858` and `:5959` (source-only; restart pending):
  `DCN_AI_Intelligence/app.py` → `host=os.environ.get("INTEL_BIND_HOST", "127.0.0.1")`;
  `napalm_network/dashboard.py` → `host=os.getenv("DASHBOARD_BIND_HOST", "127.0.0.1")` **and**
  `debug=True → debug=False` (removes the Werkzeug debugger/PIN RCE surface on a `0.0.0.0`
  bind). `:5757` / `:6060` / `:8099` were already loopback; `:8080` demo-ui stays `0.0.0.0`
  by design.

### Security
- No per-route auth was added: the global `MVLAB_API_KEY` `before_request` gate in
  `src/app.py` (fail-closed 503, `hmac.compare_digest`, covers all non-GET) already protects
  approve / decline / simulate.
- Public-push secret scan (read-only `git log -p` + pattern grep over the Phase 6 + hardening
  range): **no secrets found** — all key material reads from env vars. Two non-secret
  follow-ups deferred to finalize: an "AEGIS" mention in commit `7b72bed`'s message body
  (MEDIUM), and a pre-existing `app.py` AEGIS block (LOW). See `docs/SECURITY_HARDENING.md`.
- Doc env-var rot corrected: the Flask app gate is `MVLAB_API_KEY` (not `DCN_API_KEY`); the
  simulate gate is `MVLAB_AUTO_REMEDIATE_SIMULATE`.

### Deferred (operator finalize — see `../../FINALIZATION_RUNBOOK.md`)
- Restart `com.geshlab.dcn-intel` (`:5858`) + `com.geshlab.napalm` (`:5959`) so the bind
  hardening takes effect (`launchctl kickstart -k`). `:5757` is intentionally **not**
  restarted (preserves the in-memory `pending_approval` queue).
- Branch + commit + push the C/E + hardening changes to `mv main`; open a PR. Each git step
  is race-guarded (verify branch + HEAD) and secret-scan gated; never force-push.
- Commit the AEGIS launch WIP (7 files) on its own branch/PR.
- Re-launch the stdio MCP client (Claude Desktop) to register the 5 `mv_auto_*` tools.
