# Build your own multi-vendor Docker lab

This repo ships **two runnable labs** you can stand up on your own machine — a fast
single-vendor backbone for a first win, and a full multi-vendor EVPN-VXLAN fabric for the
real thing. Everything below is copy-pasteable.

| Lab | What it is | Vendors | Bring-up | Good for |
|---|---|---|---|---|
| **A — FRR backbone** | 10-router multi-region eBGP/OSPF core (`docker-compose`) | FRR only | ~2 min | first run, SSH/API demo, BGP-failure sim |
| **B — CLOS EVPN fabric** | 15-node spine/leaf EVPN-VXLAN fabric (`containerlab`) | Nokia SRL · Arista cEOS · FRR | ~5–10 min | dual-stack EVPN, ESI-LAG, symmetric IRB |

> The public [**Fabric Portal**](portal.html) is a static snapshot of Lab B running on the
> author's machine — diagrams, per-vendor configs, connectivity matrix, and design
> decisions. This guide is how you reproduce it yourself.

---

## 0. Prerequisites

| Need | Why | Check |
|---|---|---|
| **Docker** (Desktop on macOS/Windows, Engine on Linux) | runs every node | `docker info` |
| **~16 GB RAM free** for Lab B | 3× cEOS pin **4 GB each** | `docker info \| grep Memory` |
| **git**, **python3 ≥ 3.10** | clone + the optional Flask tool | `git --version` |
| **containerlab** *(Lab B only)* | wires the fabric | native binary on Linux; on macOS it runs as the `ghcr.io/srl-labs/clab` Docker image — **no host install needed** (see §3) |

```bash
git clone https://github.com/gesh75/multivendor-ai-network-lab.git
cd multivendor-ai-network-lab
export LABPATH="$PWD/containerlab-multivendor"      # used by the Lab B commands
```

### Get the node images

```bash
# FRR  — public
docker pull frrouting/frr:latest
# Nokia SR Linux — public
docker pull ghcr.io/nokia/srlinux:24.10.3
# multitool (the dual-homed hosts in Lab B) — public
docker pull ghcr.io/hellt/network-multitool:latest
```

**Arista cEOS is not publicly pullable** — Arista gates it behind a free account. Download
`cEOS-lab-4.33.1F.tar.xz` from [arista.com](https://www.arista.com/en/support/software-download),
then import it under the exact tag the topology expects:

```bash
docker import cEOS-lab-4.33.1F.tar.xz ceosimage:4.33.1F
docker images | grep ceosimage          # expect  ceosimage  4.33.1F
```

> Lab A is **FRR-only**, so you can run it with just the first `docker pull` and skip SRL/cEOS.

---

## 1. Lab A — FRR backbone (the 2-minute win)

```bash
cd network-lab
docker-compose up -d                     # 10 FRR routers, mgmt 10.200.0.0/24, SSH ports 2201–2210
docker ps --filter "name=de-fra\|uk-lon\|nl-ams\|us-nyc" --format "table {{.Names}}\t{{.Status}}"
```

Verify BGP is up (ground truth, straight from a router):

```bash
docker exec de-fra-core-01 vtysh -c 'show bgp summary'
docker exec de-fra-core-01 vtysh -c 'show ip ospf neighbor'
```

**Optional — drive it with the AI Network Tool** (Flask API on `:5757` + web UI on `:8080`):

```bash
cd ../src && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 app.py                           # then open http://localhost:8080/
```

Simulate a failure for the demo:

```bash
./network-lab/sim_bgp_failure.sh break   # drops a core↔core session (a badge turns red ~15s)
./network-lab/sim_bgp_failure.sh fix     # restore
```

Tear down: `cd network-lab && docker-compose down`.

---

## 2. Lab B — CLOS EVPN-VXLAN fabric (containerlab)

3 spines + 6 leafs + 6 dual-homed hosts. eBGP underlay (per-leaf AS 65001–65006, spines
65100) + eBGP EVPN overlay, ESI-LAG multihoming (anycast MAC `00:00:5E:00:53:01`),
symmetric IRB (L3 VNI 50001), IPv6 dual-stack. Topology:
`containerlab-multivendor/topologies/clos-evpn.clab.yml`.

### Linux (native containerlab)

```bash
cd containerlab-multivendor
./scripts/setup.sh                       # installs containerlab if missing
./scripts/deploy.sh clos-evpn            # deploys + wires the fabric
```

### macOS / Docker Desktop — the `--pid host` recipe

Docker Desktop has no `/run/netns`, so containerlab must borrow the LinuxKit VM's PID
namespace with **`--pid host`**. Without it every node fails with
`namespace path not available …` — the containers come up but stay **unwired** (BGP 0/x).
This is the single most common trap; the full write-up is in
[**CLOS_EVPN_MACOS_DEPLOY.md**](CLOS_EVPN_MACOS_DEPLOY.md).

```bash
cd containerlab-multivendor
./scripts/setup.sh                       # checks Docker runtime + pulls free images
./scripts/deploy.sh clos-evpn            # uses ghcr.io/srl-labs/clab with --pid host
```

If Docker Desktop exposes its socket somewhere other than
`$HOME/.docker/run/docker.sock` or `/var/run/docker.sock`, set it explicitly:

```bash
DOCKER_HOST_SOCKET=/path/to/docker.sock ./scripts/deploy.sh clos-evpn
```

### Post-deploy (both platforms): push SRL EVPN config

SRL nodes boot **blank** — push their `bgp-vpn` / EVPN config, then wait for convergence:

```bash
bash "$LABPATH/scripts/post-deploy-srl.sh" 30
```

See [`containerlab-multivendor/EVPN_RUNBOOK.md`](https://github.com/gesh75/multivendor-ai-network-lab/blob/main/containerlab-multivendor/EVPN_RUNBOOK.md)
for the full service plan, VTEP addressing, and per-vendor verification.

---

## 3. Verify the fabric

```bash
# Per-vendor BGP (ground truth)
docker exec clab-clos-evpn-spine3 vtysh -c 'show bgp summary'                                   # FRR
docker exec clab-clos-evpn-spine1 sr_cli "show network-instance default protocols bgp neighbor" # SRL
docker exec clab-clos-evpn-spine2 Cli -p 15 -c "show bgp evpn summary"                           # cEOS
```

A healthy fabric reports **~54 BGP sessions up across the 9 network nodes**. A few peers
sitting non-established during convergence (or by FRR L3-VNI design) is normal.

If you also run the Flask tool, the collector endpoint gives a one-shot health view:

```bash
curl -s http://127.0.0.1:5757/api/mv/clab-status | python3 -m json.tool
```

---

## 4. Gotchas (learned the hard way — save yourself the debugging)

| Symptom | Cause | Fix |
|---|---|---|
| `namespace path not available` on macOS | clab can't reach the netns | add **`--pid host`** (§2) |
| Fabric was up, now 0 BGP after a Docker restart | `docker restart` destroys clab veths | **redeploy** with `… deploy … --reconfigure` — never just restart |
| cEOS pinned at 100% mem, empty CLI, setns errors | starved (<4 GB) | keep `memory: 4Gb` per cEOS; budget ~12 GB for 3× |
| SRL node has zero BGP config | missing global `bgp-vpn` instance | `post-deploy-srl.sh` pushes it — don't skip it |
| FRR `/etc/frr/frr.conf` has content but `show running-config` is empty | config not read at boot | run `vtysh -b` inside the node |
| `docker pull ceosimage` fails | cEOS isn't on a public registry | download + `docker import` (§0) |

---

## 5. Tear down

```bash
# Lab A
cd network-lab && docker-compose down

# Lab B (Linux or macOS)
cd containerlab-multivendor && ./scripts/destroy.sh clos-evpn
```

---

### See also
- [**Fabric Portal**](portal.html) — live snapshot: diagrams, configs, connectivity matrix, design decisions
- [**CLOS_EVPN_MACOS_DEPLOY.md**](CLOS_EVPN_MACOS_DEPLOY.md) — the `--pid host` gotcha in depth
- [Repository README](https://github.com/gesh75/multivendor-ai-network-lab#readme) — architecture, the AI Network Tool, MCP server
