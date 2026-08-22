# Deploying the CLOS-EVPN fabric on macOS (the `--pid host` gotcha)

> **Scope:** how to bring the 15-node `clos-evpn` containerlab fabric up **cleanly** on a
> macOS (Apple-Silicon) workstation with Docker Desktop. For the EVPN service plan, VTEP
> addressing, and per-vendor verification see
> [`../containerlab-multivendor/EVPN_RUNBOOK.md`](../containerlab-multivendor/EVPN_RUNBOOK.md);
> the ops portal documents the same recipe under **Operations → Fabric Lifecycle** and
> **Documentation → Known Limitations** (`containerlab-multivendor/docs/portal.html`).

---

## TL;DR

- Dockerized containerlab **does** work on macOS Docker Desktop — **but only with `--pid host`.**
  That flag gives the clab container access to the LinuxKit VM's PID namespace so it can
  reach each node's `/proc/<pid>/ns/net` and wire the inter-node veth links.
- **Without `--pid host`** every node fails with `namespace path not available for
  container …` — the containers come up but stay **unwired** (BGP/OSPF 0/x). (This is the
  trap: a deploy invocation copied from a code path that omits `--pid host` looks like a
  hard "macOS can't do clab" limit, but it's just the missing flag.)
- After **any macOS Docker Desktop restart**, the clab veths are destroyed even though the
  containers auto-restart → **redeploy** with the command below. The `docker-compose` FRR
  backbone (`de-fra-*`, `uk-lon-*`, …) is unaffected — its links live in the compose network.

---

## 1. Deploy / redeploy (verified working on macOS Docker Desktop)

```bash
cd containerlab-multivendor
./scripts/setup.sh
./scripts/deploy.sh clos-evpn

# SRL nodes boot blank — push their EVPN / bgp-vpn config (runs via docker exec
# from the macOS host; no clab container needed):
bash ./scripts/post-deploy-srl.sh 30

# Resume telemetry scraping into InfluxDB:
launchctl kickstart -k gui/$(id -u)/com.geshlab.clab-collector
```

Notes:
- `--reconfigure` destroys + recreates the nodes and **rewires links** — required after a
  Docker restart (a plain `docker restart` of the containers does NOT rebuild veths).
- On macOS, `deploy.sh` runs `ghcr.io/srl-labs/clab:latest` with `--pid host`.
- The Docker Desktop socket is detected at `~/.docker/run/docker.sock` or
  `/var/run/docker.sock`. If yours is elsewhere, set `DOCKER_HOST_SOCKET=/path/to/docker.sock`.

## 2. Verify (expect non-zero BGP across all 9 network nodes)

```bash
# Collector view — healthy_nodes should be 9/9, stale=false:
curl -s http://127.0.0.1:5757/api/mv/clab-status | python3 -c \
 "import sys,json;d=json.load(sys.stdin);n=d['nodes'];print('healthy',sum(v.get('healthy') for v in n.values()),'/',len(n),'bgp_up',sum(v.get('bgp_up',0) for v in n.values()),'stale',d['stale'])"

# Per-vendor BGP (the portal documents these under Operations → BGP Verification):
docker exec clab-clos-evpn-spine3 vtysh -c 'show bgp summary'                                   # FRR
docker exec clab-clos-evpn-spine1 sr_cli "show network-instance default protocols bgp neighbor" # SRL
docker exec clab-clos-evpn-spine2 Cli -p 15 -c "show bgp evpn summary"                           # cEOS

# Or the repo verifier:
./scripts/verify.sh
```

A healthy fabric reports ~**54 BGP sessions up across 9 nodes** (3 spines × IPv4+IPv6
underlay + EVPN overlay); a few peers may sit in non-established states during convergence
or by design (FRR L3-VNI limits) — that is normal, not a failure.

## 3. Alternatives

- **VS Code devcontainer** (config in repo: `containerlab-multivendor/.devcontainer/`,
  image `ghcr.io/srl-labs/containerlab/devcontainer-dood-slim`, already `--pid=host`).
  "Reopen in Container", then `./scripts/setup.sh && ./scripts/deploy.sh clos-evpn`.
- **OrbStack** Linux machine (`orb` is not installed on this host by default): install it,
  create a machine, install containerlab, then run `./scripts/*` from the mounted repo path.

Both are optional conveniences — the §1 wrapper scripts work directly on macOS.

## 4. Gotchas (carried from the workspace `CLAUDE.md` + the portal)

- **`--pid host` is mandatory on Docker Desktop** (see TL;DR) — the #1 cause of an
  "up but unwired" fabric.
- **cEOS needs 4 GB** (`memory: 4Gb` is pinned in `clos-evpn.clab.yml`) — 2.5 GB OOM-thrashes
  (100% mem, empty CLI, setns errors). 3× cEOS ⇒ budget ~12 GB.
- **SRL EVPN needs the global `bgp-vpn` instance** — `post-deploy-srl.sh` pushes it; skip it
  and the SRL candidate commit is rejected, leaving the node with zero BGP config.
- **`docker restart` ≠ redeploy** — it destroys veth links. Always re-run the §1
  `… deploy … --reconfigure` command, never just restart the containers.
- **FRR config not loading at boot** — if `/etc/frr/frr.conf` has content but
  `show running-config` is empty, run `vtysh -b` in the node to read it in.
- **FRR has no kernel VRF in-container** — L3 VNI 50001 can't decap on FRR leafs; host6 bond
  primary is pinned to SRL leaf5 (by design, documented in the portal).
- **cEOS eAPI is startup-config only** — `leaf1` / `leaf4` / `spine2` ship
  `management api http-commands` + `no shutdown` so NAPALM can reach HTTPS:443 on
  a clean deploy. Enabling eAPI in-place is not durable (uwsgi starts at boot).
  Do **not** `docker restart` a node to pick it up — that destroys veths; redeploy
  with `./scripts/deploy.sh clos-evpn`.

## 5. What does NOT depend on this fabric

These stay green with just Docker Desktop up (no clos-evpn needed): the `docker-compose`
FRR backbone (`de-fra-*`/`uk-lon-*`/`nl-ams-*`/`us-nyc-*`, real BGP), the LLM engine,
NetBox-SoT drift, compliance, auto-remediation, AEGIS preflight, the `:5757` API, and the
`:8080` demo UI. Only BGP/EVPN/gNMIC telemetry **for the clos-evpn nodes** needs the fabric
wired per §1.
