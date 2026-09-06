# Gap analysis — multivendor-ai-network-lab

**Date:** 2026-09-05
**Scope:** static scan + local pytest on `pip install -e ".[dev]"` (no live lab, no Docker fabric).
**Companion (do not confuse):** [`GAPS_REPORT.md`](GAPS_REPORT.md) is a 2026-05-25 *live-lab functional audit*. This file is a repo/CI/correctness scan.

## Method (what was proved)

| Check | Result |
| --- | --- |
| `bash -n` on every `*.sh` | All bash scripts parse. `src/ssh_askpass.sh` is Expect (`#!/usr/bin/expect -f`); `bash -n` errors — naming issue, not a bash bug. |
| `pip install -e ".[dev]"` then `import app` | **Failed** before this PR (`ModuleNotFoundError: flask_cors`). **Passes** after declaring `flask-cors` / `netmiko` / `python-dotenv`. |
| pytest collect-only (same flags as CI) | 585 tests collected. |
| CI allowlist (pre-change) | 214 passed. |
| Offline unit files CI did not run | 286 passed; 15 failed; 10 errored (`flask_cors` + missing `aegis`). |
| Flask POST suites after dep fix | 503 — `MVLAB_API_KEY` fail-closed; tests send no `X-API-Key`. |
| Secret scan | No committed `.env` or private keys. Lab FRR neighbor passwords are in `network-lab/configs/*/frr.conf` (expected for a public lab). `DCN_PKCS11_PIN` has no default. |

## Fixes in this PR (3, small, safe)

1. Declare the runtime deps `src/app.py` already imports (`flask-cors`, `netmiko`, `python-dotenv`) in `pyproject.toml` + `src/requirements.txt`.
2. Stop hard-coding stale inventory sizes in `test_netbox_sot.py` and `src/tests/test_nornir.py` (26→file length; 6/3/2→`LAB_DEVICES`).
3. Expand `.github/workflows/ci.yml` to the offline files that are actually green.

---

## P0 — fix next (file + evidence)

### P0-1. CI extra could not import the Flask app

- **Files:** [`pyproject.toml`](pyproject.toml), [`src/app.py`](src/app.py) L64 / L67, [`src/requirements.txt`](src/requirements.txt)
- **Evidence:** `pip install -e ".[dev]"` (the CI install) then `python -c "import app"` → `ModuleNotFoundError: No module named 'flask_cors'`. `netmiko` is also an unconditional import and lived only under the unused `real` extra. `python-dotenv` is imported at L42 but was missing from `src/requirements.txt` (the README quickstart path).
- **Status:** **fixed here** (declaration only; no version upgrades of already-pinned stacks).

### P0-2. CI ran 214 / 585 collected tests

- **File:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
- **Evidence:** pre-change job listed only `tests/drivers` + telegram + two MCP files + `test_mcp_server.py`. Locally the skipped offline files produced **286 passes that CI never saw**, plus **15 real failures**.
- **Status:** **partially fixed here** — allowlist now includes the green Phase 4/5/6 unit files. Flask POST suites stay out (P0-3).

### P0-3. Flask POST tests are stale vs the API-key gate

- **Files:** [`src/tests/conftest.py`](src/tests/conftest.py), [`src/app.py`](src/app.py) L136–147 (`_require_api_key`), [`src/tests/test_ai_command.py`](src/tests/test_ai_command.py), [`src/tests/test_batfish.py`](src/tests/test_batfish.py), [`src/tests/test_cli_transport.py`](src/tests/test_cli_transport.py), [`src/tests/test_nornir.py`](src/tests/test_nornir.py) `TestNornirEndpoint`
- **Evidence:** after the app imports, `POST /api/nornir/run` and `/api/ai-command` return **503** (`MVLAB_API_KEY` unset). `test_auto_remediate_run_audit.py` already sends `X-API-Key` and is the pattern to copy. Not fixed here — wiring the key + header across those files is more than a one-line change.

### P0-4. AEGIS preflight imports a package that is not in this repo

- **Files:** [`src/preflight_run.py`](src/preflight_run.py) L17–29 (`_REPO_ROOT` walks *three* parents, leftover `VSS_Code_Georgi` layout; `from aegis.core.orchestrator.pipeline import …`), [`src/tests/test_preflight_flask.py`](src/tests/test_preflight_flask.py)
- **Evidence:** `ModuleNotFoundError: No module named 'aegis'` on every test in that file. `src/app.py` L15552 swallows it (`[AEGIS] Preflight not available`). No `aegis/` tree in this repository.

---

## P1 — correctness / DX / docs

| ID | Area | Evidence | Suggested smallest fix |
| --- | --- | --- | --- |
| P1-1 | Stale inventory assertions | `test_netbox_sot.py` expected 26 devices; `network-lab/demo-devices/inventory.json` has 41. `test_nornir.py` expected 6/3/2; `LAB_DEVICES` in conftest is 10/4/3. | **fixed here** — assert against the fixture/file. |
| P1-2 | Hardcoded laptop CSV paths | [`src/app.py`](src/app.py) L377–382 default `~/Downloads/03_Documents/Text/securecrt_sessions 2.csv` and `../../05_Raw_Data/CSV_Reports/dcn_tool_full_inventory.csv`. Boot log: `No such file or directory`. | Default to empty / repo `network-lab/lab_securecrt.csv`. |
| P1-3 | Broken conftest inventory path | [`src/tests/conftest.py`](src/tests/conftest.py) L27–28 joins repo root with `../../network-lab/lab_securecrt.csv` → `/workspace/../../network-lab/…`. | `os.path.join(dirname(TOOL_DIR), "network-lab/lab_securecrt.csv")`. |
| P1-4 | Stale setup docs | [`src/README.md`](src/README.md) L41 `cd gesh-ai-network-tool`, L56 `cd 04_Scripts_Tools/DCN_Network_Tool`. Root tests still say that path. [`network-lab/start_lab_tool.sh`](network-lab/start_lab_tool.sh) expects `venv_lab`, not `venv`. | Delete leftover monorepo paths; document `venv_lab`. |
| P1-5 | `src/mcp_server.py` is shadowed | Package dir [`src/mcp_server/`](src/mcp_server/) wins `import mcp_server`. The 370-line legacy JSON-RPC file is unreachable as a module. | Delete the file or rename to `mcp_server_legacy.py` if the script entry is still wanted. |
| P1-6 | Three MCP surfaces | `src/mcp_server/` (FastMCP, packaged), `src/mcp_dcn_server.py` (69 tools), `src/mcp_server.py` (dead). Docs disagree on tool counts (68 / 69 / 49). | Pick one entry point; point `MCP.md` at it. |

---

## P2 — hygiene / dead code / security defaults

| ID | Area | Evidence | Suggested smallest fix |
| --- | --- | --- | --- |
| P2-1 | Dead Expect helper | [`src/ssh_askpass.sh`](src/ssh_askpass.sh) — unused (`rg ssh_askpass` = this file only). PKCS#11 now lives in `app.py` `_pkcs11_init()`. | Delete. |
| P2-2 | Deprecated collector | [`containerlab-multivendor/scripts/telemetry-collector.py.deprecated-2026-05-25`](containerlab-multivendor/scripts/telemetry-collector.py.deprecated-2026-05-25) | Delete; the audit already recorded the rename. |
| P2-3 | Packaging only ships MCP | [`pyproject.toml`](pyproject.toml) `include = ["mcp_server*"]` — Flask/drivers are PYTHONPATH-only. | Either document `PYTHONPATH=src` as required or package `src` properly. Later. |
| P2-4 | Unknown pytest marks | `src/tests/test_health.py` `@pytest.mark.unit` / `integration` → `PytestUnknownMarkWarning`. | Register marks in `[tool.pytest.ini_options]`. |
| P2-5 | Version / KPI drift | `pyproject.toml` `0.9.0` vs README/portal **v0.6.0**; CHANGELOG claims **137/137 tests**; collect-only is **585**. | One version source; stop claiming a test count in marketing copy. |
| P2-6 | Lab-permissive TLS/SSH defaults | [`.env.example`](.env.example) L62–63 `DCN_SSH_STRICT_HOST_KEY=false`, `DCN_VERIFY_SSL=false`. Documented and warned at boot. | Leave for lab; do not copy into any non-laptop deploy. |
| P2-7 | Public lab BGP passwords | `network-lab/configs/*/frr.conf` `neighbor … password Gesh!Bgp…` | Fine for a disposable lab; never reuse those strings. |
| P2-8 | `src/app.py` is 15.6k lines | Single module owns SSH, inventory, NAPALM, chaos, closed-loop, AEGIS register. | Out of scope (rewrite). |
| P2-9 | `GAPS_REPORT.md` is a snapshot | Live BGP/KPI numbers from 2026-05-25. | Keep as historical; do not treat as current status. |

---

## Skipped (out of scope)

- Live containerlab / docker-compose bring-up, Grafana, Influx, gnmic.
- Dependency upgrades, mypy/ruff, splitting `app.py`.
- Wiring `X-API-Key` through every Flask POST test (P0-3).
- Restoring the missing `aegis` package (P0-4).
- Deleting dead files (P1-5, P2-1, P2-2) — listed, not done, to stay at 3 fixes.

## Next recommended agent job

Add a shared pytest fixture that sets `MVLAB_API_KEY` and sends `X-API-Key` on Flask POSTs, then fold `test_ai_command.py` / `test_batfish.py` / `test_cli_transport.py` / `TestNornirEndpoint` / `test_auto_remediate_run_audit.py` into CI (skip or xfail `test_preflight_flask.py` until `aegis` exists).
