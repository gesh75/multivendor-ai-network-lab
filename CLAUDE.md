# Multivendor AI Network Lab — Project Context

**Repo:** `multivendor-ai-network-lab` (github.com/gesh75/multivendor-ai-network-lab, remote `mv`)
**Purpose:** Multi-vendor data-center network labs + an AI Network Tool that collects
state across vendors via a driver abstraction layer and analyzes it.
**Stack:** containerlab + docker-compose, Nokia SRL / Arista cEOS / FRR, Python (drivers,
telemetry), InfluxDB + Grafana, static HTML ops portal.

> Naming: this is the **AI Network Tool**. "DCN Network Tool" was the earlier Acronis-era
> tool — the directory name `DCN_Network_Tool` is legacy and kept only for path stability.

---

## Two Labs

### CLOS EVPN-VXLAN Fabric (containerlab)
- **Topology:** `containerlab-multivendor/topologies/clos-evpn.clab.yml`
- 3 spines + 6 leafs + 6 hosts. Vendors: spine1/leaf2/leaf5 = Nokia SRL,
  spine2/leaf1/leaf4 = Arista cEOS, spine3/leaf3/leaf6 = FRR.
- **eBGP underlay** (per-leaf AS 65001–65006, spines AS 65100) + **eBGP EVPN overlay**
  (multihop loopback peering, spines as route-reflector-clients/transit).
- **ESI-LAG** dual-homed hosts (anycast MAC 00:00:5E:00:53:01), **symmetric IRB** anycast
  gateway (L3 VNI 50001, TENANT-A VRF), IPv6 dual-stack (fd00:dc1::/48).
- Configs: `containerlab-multivendor/configs/{spine,leaf}/`. SRL nodes need a post-deploy
  push: `containerlab-multivendor/scripts/post-deploy-srl.sh [wait-seconds]`.
- Bring-up: `containerlab-multivendor/scripts/{setup,deploy,destroy}.sh`. Linux uses
  native `containerlab` (sudo-aware). macOS Docker Desktop uses
  `ghcr.io/srl-labs/clab` with `--pid host` (`scripts/clab-common.sh`).
- cEOS eAPI is baked into `leaf1` / `leaf4` / `spine2` startup-configs for NAPALM
  (`management api http-commands`, HTTPS:443). Do not `docker restart` a node to
  enable it — redeploy with `--reconfigure`.

### DCN Multi-Region Backbone (docker-compose)
- **Compose:** `network-lab/docker-compose.yml`. 10 FRR routers (5 core + edge/dist),
  multi-region eBGP, mgmt 10.200.0.0/24. Real device names (de-fra-core-01, uk-lon-core-01,
  nl-ams-core-01, us-nyc-core-01, …) — NOT clab-prefixed.
- Configs: `network-lab/configs/<device>/frr.conf`.

---

## Operations Portal — launchd Service ★

The ops portal (`containerlab-multivendor/docs/portal.html`) is served by a **launchd agent**.

| Item | Value |
|------|-------|
| Label | `com.geshlab.portal` |
| Plist | `~/Library/LaunchAgents/com.geshlab.portal.plist` |
| Script | `containerlab-multivendor/scripts/start_portal.sh` |
| URL | http://127.0.0.1:8099/portal.html (localhost-bound) |
| Log | `/tmp/geshlab_portal.log` |
| Policy | `RunAtLoad` + `KeepAlive` — auto-starts on login, respawns if killed |

```bash
launchctl list | grep geshlab.portal                 # status
launchctl bootout  gui/$(id -u)/com.geshlab.portal    # stop
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.geshlab.portal.plist  # start
tail -f /tmp/geshlab_portal.log
```

Bound to `127.0.0.1` on purpose (lab configs/diagrams are infra detail). To expose on the
LAN, change `--bind 127.0.0.1` to `0.0.0.0` in `start_portal.sh`.

Portal sections: Overview · Topology · Diagrams (6 Mermaid: L1/L3/BGP/EVPN/Logical/DCN) ·
Live Map · Configurations · Connectivity · Driver Layer · Operations · Documentation.

### Sibling launchd agents (added 2026-05-29)

The tool's web surfaces also run under launchd now, same `RunAtLoad`+`KeepAlive` policy:
`com.geshlab.dcn-app` (API **:5757**, runs `src/app.py` with `venv_lab`) and
`com.geshlab.demo-ui` (static demo UI **:8080**, serves `demo/`). The one-command manual
launcher `network-lab/start_lab_tool.sh` does the same thing interactively (it also ensures
the lab containers + demo UI). Full cross-app agent table + gotchas live in the workspace
root `CLAUDE.md` → "launchd persistence" section.

---

## Driver Abstraction Layer (`src/drivers/`)

Single source of truth for per-vendor commands + parsers. 5 vendors: FRR, Arista EOS,
Nokia SRL, Junos, Cisco IOS-XR. `get_driver(vendor)` returns a driver; `DriverResult` carries
both `.normalized` (dict) and `.raw` (text). Wired into `src/health.py` and
`network-lab/telemetry/clab_collector.py`. Tests: `tests/drivers/` (run with
`python -m pytest tests/drivers/ -q -o testpaths=tests/drivers`).

---

## Known Gotchas (learned, non-obvious)

1. **cEOS needs 4GB memory** in the topology `kinds`/node block — 2.5GB causes OOM-thrash
   (pinned 100% mem, empty CLI, setns errors). Symptom of starvation, not config.
2. **`docker restart` destroys clab veth links** — always redeploy with
   `clab deploy --reconfigure` (needs `--pid host`).
3. **SRL ESI-LAG requires a global bgp-vpn instance** — ethernet-segments reference
   `system network-instance protocols bgp-vpn bgp-instance 1`; if it's absent the entire
   atomic candidate commit is rejected and the node ends up with zero BGP config.
4. **leaf4 (cEOS) interface offset** — topology wires spines to et2/et3/et4 (et1 unused,
   et5/et6 = host legs). cEOS MTU max is 9194 (not 9214).
5. **FRR config not loading at boot** — if `/etc/frr/frr.conf` has content but
   `show running-config` is empty, run `vtysh -b` to read it in. ntp/agentx/`mtu` lines
   emit harmless "Unknown command" warnings.
6. **Mermaid diagrams must render lazily** — `startOnLoad:false` + render-on-show; rendering
   a `.mermaid` block while its panel is `display:none` produces a "Syntax error" bomb.
7. **cEOS eAPI only starts at boot** — in-place `management api http-commands` is not
   durable (uwsgi). Startup-configs already enable it; a `docker restart` to pick up a
   live change destroys clab veths.
8. **`DCN_PKCS11_PIN` has no default** — `DCN_SSH_MODE=pkcs11` fails init and falls
   back to key mode if the PIN is unset. Lab/CI should set `DCN_SSH_MODE=key`.
9. **`setup.sh` used to hard-fail off Darwin** — it now accepts Linux (`/proc/meminfo`,
   native get.containerlab.dev install, docker-engine runtime). `.gitattributes`
   pins `*.sh` to LF so a CRLF round-trip cannot break shebangs.

---

## Conventions

- Commit style: conventional commits (`feat`/`fix`/`docs(scope): …`). Push to `mv main`.
- This repo is **public**. Do not add secrets. Keep it separate from the private
  `gesh-project-trading` repo — they are unrelated projects (network lab vs. finance).
