# `/api/health/<hostname>` — Single-device operational snapshot

A single endpoint that returns one normalized JSON document containing **everything an
engineer wants to see for a device on a dashboard** — version, BGP, OSPF, interfaces,
routes, memory, CPU — collected in parallel over SSH (or `docker exec` for clab fabrics).

## Inspired by

[scottpeterman/what_a_NOS_could_be](https://github.com/scottpeterman/what_a_NOS_could_be)
— the model is: skip SNMP entirely, just run `show` commands and parse the output.

## Quick start

```bash
# Lab device (FRR vtysh)
curl -s http://localhost:5757/api/health/de-fra-core-01 | jq

# clab Nokia SR Linux spine
curl -s http://localhost:5757/api/health/clab-clos-evpn-spine1 | jq

# clab Arista cEOS spine
curl -s http://localhost:5757/api/health/clab-clos-evpn-spine2 | jq

# 404 if hostname unknown
curl -s http://localhost:5757/api/health/no-such-device
# → {"success": false, "error": "Unknown hostname: no-such-device"}
```

Typical latency on the lab: **<2s** for the full 8-command fan-out.

## Response schema

```jsonc
{
  "meta": {
    "hostname": "de-fra-core-01",
    "ip": "127.0.0.1",
    "dtype": "frr",
    "collected_at": 1716800000.123,
    "collect_time": 1.42,
    "via": "ssh",                    // or "docker-exec" for clab
    "errors": []                     // non-fatal per-command errors
  },
  "version": {
    "raw": "FRRouting 9.1.0 ...",
    "version": "9.1.0",
    "uptime": null
  },
  "bgp": {
    "peers": [
      {"neighbor": "10.200.0.12", "asn": 65002,
       "state": "Established", "uptime": "01:23:45", "prefixes": 5}
    ],
    "established": 1,
    "down": 0
  },
  "ospf": {
    "neighbors": [
      {"neighbor": "10.200.0.12", "state": "Full",
       "interface": "eth0", "dead_time": 4567}
    ],
    "full": 1
  },
  "interfaces": {
    "list": [
      {"name": "eth0", "status": "up", "addresses": ["10.200.0.11/24"]}
    ],
    "up": 2,
    "down": 0
  },
  "routes": {
    "total": 42,
    "by_protocol": {"connected": 4, "bgp": 30, "ospf": 8}
  },
  "memory": {
    "used_mb": 124.3,
    "total_mb": 16384.0,
    "pct": 0.8
  },
  "cpu": {
    "pct_1min": 2.1
  }
}
```

**Every key is always present.** Missing data → `null`, `[]`, or `{}` — never absent.
The dashboard can render partial data without null-checking every field.

## Command fan-out

Per-vendor command tables live in `src/drivers/commands.py` (single source of
truth, also used by the telemetry collector). `src/health.py` imports those
tables and keeps local `FRR_COMMANDS` / `EOS_COMMANDS` / `JUNOS_COMMANDS` /
`SRL_COMMANDS` as a fallback if the drivers package is not importable. Each
section runs **one** command and tries the next as a fallback only if the first
failed or produced empty output.

| Section      | FRR                                  | Arista EOS                         | Junos                              | Nokia SR Linux |
|--------------|--------------------------------------|------------------------------------|------------------------------------|----------------|
| version      | `show version`                       | `show version \| json`             | `show version \| display json`     | `info from state /system information version` |
| bgp          | `show ip bgp summary json`           | `show ip bgp summary \| json`      | `show bgp summary \| display json` | `show network-instance default protocols bgp neighbor` |
| ospf         | `show ip ospf neighbor json`         | `show ip ospf neighbor \| json`    | `show ospf neighbor \| display json` | `show network-instance default protocols ospf neighbor` |
| interfaces   | `show interface brief json`          | `show interfaces status \| json`   | `show interfaces terse \| display json` | `show interface` |
| routes       | `show ip route summary json`         | `show ip route summary \| json`    | `show route summary \| display json` | `show network-instance default route-table ipv4-unicast summary` |
| memory       | `show memory summary`                | `show processes top once \| json`  | `show system memory \| display json` | `info from state /platform memory` |
| cpu          | `show thread cpu`                    | `show processes top once \| json`  | `show system processes extensive`  | `info from state /platform control cpu` |

SRL uses `sr_cli` (no reliable `| json` across commands). Inventory aliases
`nokia-srl` / `srl` / `nokia` all map to `SRL_COMMANDS`. `dtype` in `meta` can
be `frr` · `eos` · `junos` · `arista-eos` · `nokia-srl`.

All commands run **in parallel** via `ThreadPoolExecutor` — one section's slow command
never blocks the others. Per-command timeout: 15 s. Total snapshot deadline: 30 s.

## Parser strategy

Each section tries **JSON first**, then falls back to **regex on text**:

1. Try `_try_json(output)` — most modern NOS versions can emit JSON.
2. If JSON parsing succeeds, normalize the vendor-specific keys to our schema.
3. If JSON fails (legacy device, no `| json` support), regex-parse the columnar text.

This means the endpoint works against both modern (vtysh JSON, Arista `| json`,
Junos `| display json`) and legacy devices — same shape, same dashboard.

## Adding a new vendor

1. Add a `<VENDOR>_COMMANDS` dict to `src/drivers/commands.py` (and the matching
   fallback literals in `src/health.py`) mapping each schema section to a list
   of commands (most-preferred first, fallbacks after).
2. Register it in `COMMAND_MAP` / the driver alias map under whatever `dtype`
   value the inventory uses.
3. Where vendor JSON output uses different keys, extend the parsers (e.g. `_parse_bgp`)
   with an `elif` branch for the new shape.
4. Add a unit test in `src/tests/test_health.py` with a canned output fixture.

The schema itself stays vendor-neutral — that's the whole point. Only the *input*
commands and *JSON key paths* change per vendor.

## Why this design

* **One endpoint, one snapshot.** Most dashboards stitch together 5–10 SNMP polls + 2–3
  REST calls. This is one HTTP GET per device → one JSON document.
* **Parallelism baked in.** ThreadPoolExecutor with one worker per section. The slowest
  command sets the wall-clock time, not the sum of all commands.
* **Stateless.** Re-run on every request. Caller (Flask, MCP tool, the UI) owns caching.
  This makes the module easy to test (no DB, no global state).
* **Soft failures.** A failed command goes into `meta.errors` as a string — never raises.
  Partial data is better than no data.
* **No SNMP.** All data comes from the same `run_command_on_device` helper that the
  manual SSH UI uses. One auth path, one transport, one set of credentials.

## When NOT to use this

* **High-frequency polling.** Each call opens a new SSH session per command. For sub-second
  telemetry, run a long-lived collector that maintains a session pool (or use the existing
  `/api/telemetry/status` path that already pipes through Telegraf/InfluxDB).
* **Historical data.** This endpoint is point-in-time only. Pair with `/api/pyats/snapshot`
  + `/api/pyats/diff` if you need before/after state for change windows.

## See also

* Source: [`src/health.py`](../src/health.py)
* Tests: [`src/tests/test_health.py`](../src/tests/test_health.py)
* Route handler: see `get_device_health` in [`src/app.py`](../src/app.py)
* Inspiration: https://github.com/scottpeterman/what_a_NOS_could_be
