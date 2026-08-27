# Security Hardening — Network Binding + Public-Push Secret Scan

This note documents the network-exposure hardening applied during the Phase 6 finish and the
secret-scan verdict for the already-pushed public commit range. Verified against on-disk code
and live socket state on 2026-05-31.

---

## Loopback-binding rationale

All of the local dashboards serve **infrastructure detail** (lab configs, diagrams, device
telemetry, AI analysis surfaces). None of it is meant to be reachable from the LAN on a
developer laptop. The default posture is therefore **bind to `127.0.0.1`** so a service is
reachable only from the machine it runs on; LAN exposure is an explicit, env-driven opt-in
(e.g. when fronted by a reverse proxy). Binding to `0.0.0.0` exposes a service on every
interface — and when paired with Flask `debug=True`, exposes the Werkzeug interactive
debugger / PIN console, which is a remote-code-execution surface. Both were the targets of
this hardening.

---

## State of all dashboards

| Service | Port | Launchd label | Bind (intended) | Bind env override | Notes |
|---|---|---|---|---|---|
| DCN/AI Network Tool API | `:5757` | `com.geshlab.dcn-app` | `127.0.0.1` ✅ | — | already loopback |
| netlog-ai web UI | `:6060` | `com.geshlab.netlog` | `127.0.0.1` ✅ | — | already loopback |
| Fabric ops portal | `:8099` | `com.geshlab.portal` | `127.0.0.1` ✅ | (`--bind` in `start_portal.sh`) | already loopback |
| DCN AI Intelligence | `:5858` | `com.geshlab.dcn-intel` | `127.0.0.1` (now) | `INTEL_BIND_HOST` | **hardened this pass** — restart pending |
| NAPALM Dashboard | `:5959` | `com.geshlab.napalm` | `127.0.0.1` (now) | `DASHBOARD_BIND_HOST` | **hardened this pass** (+ `debug=False`) — restart pending |
| Demo UI (static) | `:8080` | `com.geshlab.demo-ui` | `0.0.0.0` | — | **intentionally** LAN-exposed (static demo, no API/secrets) |

### Already loopback (no change)

`:5757`, `:6060`, and `:8099` were already bound to `127.0.0.1` and were not modified. Live
`lsof` confirms `:5757` and `:6060` listening on `127.0.0.1`, and the portal is documented
loopback-bound in its launchd note.

### Hardened this pass — `:5858` and `:5959`

Two single-file Flask apps were binding `0.0.0.0`. Both were changed to a loopback default,
env-overridable, with no service restart performed (the agent does not restart launchd
services — see the finalization runbook).

**`04_Scripts_Tools/DCN_AI_Intelligence/app.py` (`:5858`)** — line 2787–2788:

```python
BIND_HOST = os.environ.get("INTEL_BIND_HOST", "127.0.0.1")
app.run(host=BIND_HOST, port=PORT, debug=False)
```

`debug` was already `False` and stays `False`; `PORT` is unchanged. The env-var style
(`os.environ.get`) matches this file's existing `INTEL_PORT` idiom. (The two residual
`0.0.0.0` string matches in this file are numeric bandwidth thresholds like `1_000_000_000`,
not bind addresses — verified.)

**`04_Scripts_Tools/napalm_network/dashboard.py` (`:5959`)** — line 847 + 853:

```python
bind_host = os.getenv("DASHBOARD_BIND_HOST", "127.0.0.1")
...
app.run(host=bind_host, port=port, debug=False, threaded=True)
```

This is the **top-level** `napalm_network` (launchd `com.geshlab.napalm`), not the
`DCN_Network_Tool/napalm_network` decoy (which holds only an `output/` dir). The change does
two things: (1) loopback default via `DASHBOARD_BIND_HOST`, and (2) flips `debug=True` →
`debug=False`. Flipping `debug` off is the highest-value fix here — `debug=True` on a
`0.0.0.0` bind exposed the Werkzeug debugger/PIN console (RCE). `port` and `threaded=True` are
unchanged; the env-var style (`os.getenv`) matches the file's existing `DASHBOARD_PORT` idiom.

`grep` confirms **zero residual `0.0.0.0` or `debug=True`** in `dashboard.py`, and both files
pass `python3 -m py_compile`.

### Demo UI `:8080` — intentionally `0.0.0.0`

The demo UI is a static file server (`demo/`) with no API and no secrets. It is intentionally
bound to `0.0.0.0` so the demo is reachable for walkthroughs. This is by design and was **not**
changed.

### Restart is required for `:5858` / `:5959` to take effect

The two bind edits are source-only; the running processes still bind `0.0.0.0` until their
launchd agents are restarted. Live `lsof` on 2026-05-31 confirms `:5858` and `:5959` still
listening on `*:` (0.0.0.0) — i.e. the hardening is staged but not yet active. The exact
race-guarded restart commands are in
[`/Users/georgigaydarov/02_Projects/Network_Automation/VSS_Code_Georgi/FINALIZATION_RUNBOOK.md`](../../../FINALIZATION_RUNBOOK.md),
step (a).

### NAPALM `WERKZEUG_RUN_MAIN` caveat (still applies)

Do **not** set `WERKZEUG_RUN_MAIN=true` for the NAPALM agent — historically that env var made
Werkzeug expect an inherited socket FD that isn't there (`KeyError: WERKZEUG_SERVER_FD`) →
crash-loop. With `debug=False` now in place, the reloader child no longer spawns, so a single
PID is the **expected** post-restart state (not a regression). Leave `WERKZEUG_RUN_MAIN` unset.

---

## Public-push secret-scan verdict

A read-only secret scan was run over the already-pushed Phase 6 + hardening commit range on
the public mirror (`gesh75/multivendor-ai-network-lab`). The scan used read-only git
(`git log -p` piped through a secret-pattern grep) — **no** history-mutating git was run.

> **Tool note (AEGIS vs AgentShield):** the `.claude` "security-scan" skill is **AgentShield**
> and scans `.claude` *config* (CLAUDE.md, settings, MCP servers, hooks, agents) — it does
> **not** scan git history. For the commit range, the verdict below is from a read-only
> `git log -p` + pattern grep (and can be cross-checked via the GitHub secret-scanning surface
> on the repo). No AEGIS git-history CLI is committed in the public repo.

### Verdict: no secrets committed (NEEDS_ACTION on two non-secret items)

Patterns checked (assigned literals vs. env-lookups / placeholders): `MVLAB_API_KEY=`,
`DCN_API_KEY=`, `NETBOX_TOKEN=`, `YUBIKEY_PIN=`, `ANTHROPIC_API_KEY=`, and the
`sk-` / `ghp_` / `AKIA` / `xox` / `BEGIN PRIVATE KEY` families.

* **`secrets_found: false`** — no API keys, tokens, passwords, or `.env` content in any of
  the scanned commits. All key handling reads from environment variables
  (`os.environ.get("MVLAB_API_KEY", "")`, `os.environ["DCN_API_KEY"]`, etc.); the localhost
  base URLs are env-driven. `.env` is gitignored; only `.env.example`-style placeholders are
  tracked.

Follow-up items (none are secrets):

| Severity | Where | Item |
|---|---|---|
| MEDIUM | commit `7b72bed` **message body** (git metadata, not a file blob) | Two sentences name the private project "AEGIS" ("mirrors AEGIS pattern"; "carries the pre-existing dev-only AEGIS preflight wiring"). Visible via `git log` on the public repo. **Recommended:** reword the commit message if "AEGIS" is sensitive by name. Do **not** force-push history without an explicit decision (see runbook). |
| LOW | `docs/PHASE_6_AUTO_REMEDIATE.md` (older draft) | A `grep ^DCN_API_KEY= .env` snippet discloses the secret *variable name* + storage location (no value). Cosmetic attack-surface enumeration. The new `PHASE6_AUTO_REMEDIATION.md` uses `MVLAB_API_KEY` for the app gate (the correct env var). |
| LOW | test fixtures + demo curl | Lab hostnames (`de-fra-core-01`, `leaf1`, `leaf2`) and interface names enumerate internal **lab** naming (clearly containerlab, not production). Advisory: could be genericized. |
| LOW | `src/app.py` (pre-existing, outside scan range) | An AEGIS preflight wiring block exists in `app.py` (predates Phase 6; +0 AEGIS lines added by the Phase 6 commits). Should be reviewed independently for whether `preflight_*` modules belong in the public repo. |
| INFO | new code | All key handling is `os.environ.get(...)` — never hardcoded. Confirmed clean. |
| INFO | `auto_remediate.py` | `/simulate` correctly gated behind `MVLAB_AUTO_REMEDIATE_SIMULATE=1` (off by default); `valid_field()` guards every placeholder. Security fixes sound and complete. |

**Bottom line:** the public push is secret-clean. The two MEDIUM/LOW git-history items
("AEGIS" naming in a commit message; the pre-existing `app.py` AEGIS block) are an internal
naming-disclosure question, **not** a credential leak, and are deferred to the human for a
reword/redaction decision — never force-push without that decision.

---

## YubiKey PKCS#11 PIN — fail-fast, no default (2026-06-09)

`DCN_SSH_MODE` defaults to `pkcs11`. The PIN used to login the YubiKey PIV token is read
from **`DCN_PKCS11_PIN` only**. There is no hardcoded fallback.

```python
PKCS11_PIN = os.environ.get("DCN_PKCS11_PIN")   # required in pkcs11 mode
# ...
if not PKCS11_PIN:
    raise RuntimeError("DCN_PKCS11_PIN is not set — export it to use pkcs11/YubiKey SSH mode")
```

If init fails (PIN unset, no token, library missing), boot logs
`[SSH] PKCS#11 init failed: … — falling back to key mode` and switches `SSH_MODE` to
`key` (`src/app.py`). Lab / CI boxes that never present a YubiKey should set
`DCN_SSH_MODE=key` explicitly so they do not depend on that fallback.

**Operator constraint:** removing the default from source does **not** un-expose a PIN
that already lived in git history. Rotate the physical YubiKey PIV PIN if that slot
was ever used with the old default.

See `.env.example` for the env-var names (`DCN_PKCS11_PIN`, `DCN_PKCS11_LIB`).
