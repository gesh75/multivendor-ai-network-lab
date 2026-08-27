# Multi-Vendor Network Lab — Containerlab (Linux + macOS)

**15-node multi-vendor data center fabric** (3 spines + 6 leafs + 6 hosts)
with EVPN-VXLAN, eBGP underlay + eBGP EVPN overlay, ESI-LAG, and dual-stack.
`./scripts/setup.sh` and `./scripts/deploy.sh` work on **Ubuntu/Linux** (native
containerlab) and **macOS Docker Desktop** (clab image + `--pid host`).

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         MANAGEMENT + TELEMETRY           │
                    │  Grafana :3000 · InfluxDB :8086          │
                    │  Prometheus :9090 · gNMI collector       │
                    └────────────────┬────────────────────────┘
                                     │ mgmt network
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
   ┌──────┴──────┐          ┌───────┴───────┐          ┌───────┴──────┐
   │  SPINE-1    │          │   SPINE-2     │          │   SPINE-3    │
   │ Nokia SRL   │          │  Arista cEOS  │          │   FRR        │
   │ AS 65100    │          │  AS 65100     │          │  AS 65100    │
   │ RR / EVPN   │          │  RR / EVPN    │          │  RR / EVPN   │
   └──┬───┬───┬──┘          └──┬───┬───┬────┘          └──┬───┬───┬──┘
      │   │   │                │   │   │                  │   │   │
      │   │   └────────────────┼───┼───┼──────────────────┘   │   │
      │   └────────────────────┼───┘   │                      │   │
      │                        │       └──────────────────────┘   │
   ┌──┴──────┐          ┌─────┴────┐          ┌──────────┐       │
   │ LEAF-1  │          │ LEAF-2   │          │ LEAF-3   │       │
   │ Arista  │          │ Nokia    │          │ FRR      │       │
   │ cEOS    │          │ SRL      │          │ (Cisco)  │       │
   │ VTEP    │          │ VTEP     │          │ VTEP     │       │
   │ AS65001 │          │ AS65002  │          │ AS65003  │       │
   └──┬───┬──┘          └──┬───┬───┘          └──┬───┬───┘      │
      │   │                │   │                  │   │          │
   ┌──┴──┐ ┌──┴──┐     ┌──┴──┐ ┌──┴──┐     ┌──┴──┐ ┌──┴──┐    │
   │ L4  │ │ L5  │     │ L6  │ │ L7  │     │ L8  │ │ L9  │    │
   │cEOS │ │ SRL │     │cEOS │ │ SRL │     │ FRR │ │ FRR │    │
   │65004│ │65005│     │65006│ │65007│     │65008│ │65009│    │
   └──┬──┘ └──┬──┘     └──┬──┘ └──┬──┘     └──┬──┘ └──┬──┘    │
      │       │            │       │            │       │       │
   ┌──┴──┐ ┌──┴──┐     ┌──┴──┐ ┌──┴──┐     ┌──┴──┐ ┌──┴──┐   │
   │ H1  │ │ H2  │     │ H3  │ │ H4  │     │ H5  │ │ H6  │   │
   │Linux│ │Linux│     │Linux│ │Linux│     │Linux│ │Linux│   │
   └─────┘ └─────┘     └─────┘ └─────┘     └─────┘ └─────┘   │

   VLAN 10 ─────────── VLAN 20 ─────────── VLAN 30 ──────────┘
   VNI 10010            VNI 10020            VNI 10030
```

> The sketch above is schematic. The **live** `clos-evpn` topology is 3 spines +
> **6** leafs + 6 dual-homed hosts (not 9 leafs). Leaf roles and ESIs are in
> [`EVPN_RUNBOOK.md`](EVPN_RUNBOOK.md). Overlay peering is **eBGP** (per-leaf
> AS 65001–65006 → spines 65100), not iBGP.

## Vendors Used

| Vendor | Image | RAM/node | Role | License |
|--------|-------|----------|------|---------|
| **Nokia SR Linux** | `ghcr.io/nokia/srlinux:24.10.3` | ~1.5GB | Spine + Leaf | Free (public registry) |
| **Arista cEOS** | `ceosimage:4.33.1F` | **4 GB** (pinned — 2.5 GB OOM-thrashes) | Spine + Leaf | Free (arista.com guest portal; `docker import`) |
| **FRR** | `frrouting/frr:latest` | ~0.2GB | Spine + Leaf | Free (open source) |
| **Linux hosts** | `ghcr.io/hellt/network-multitool` | ~0.05GB | Dual-homed end hosts | Free |

**Budget ~16 GB free RAM** for Lab B (3× cEOS × 4 GB). `setup.sh` warns below 32 GB and fails below 16 GB.

## Available Topologies

| Profile | File | Nodes | Protocols | Use Case |
|---------|------|-------|-----------|----------|
| `clos-evpn` | `topologies/clos-evpn.clab.yml` | 15 | BGP EVPN-VXLAN, eBGP underlay | DC fabric |
| `3tier-enterprise` | `topologies/3tier-enterprise.clab.yml` | 12 | OSPF, STP, HSRP/VRRP | Campus |
| `sp-mpls` | `topologies/sp-mpls.clab.yml` | 10 | IS-IS, LDP, MPLS L3VPN | Service Provider |
| `minimal` | `topologies/minimal.clab.yml` | 6 | BGP, OSPF basics | Quick testing |

## Quick Start

```bash
# 1. Install prerequisites
./scripts/setup.sh

# 2. Deploy the Clos EVPN fabric (default)
./scripts/deploy.sh clos-evpn
bash ./scripts/post-deploy-srl.sh 30   # SRL nodes boot blank

# 3. Verify the fabric
./scripts/verify.sh

# 4. Connect to devices
ssh admin@clab-clos-evpn-spine1     # Nokia SR Linux
ssh admin@clab-clos-evpn-leaf1      # Arista cEOS
ssh root@clab-clos-evpn-leaf3       # FRR (Cisco-style)

# 5. Destroy when done
./scripts/destroy.sh clos-evpn
```

## Integration with AI Network Tools

This lab integrates with the existing DCN Network Tool ecosystem:

| Tool | Integration | Port |
|------|-------------|------|
| **AI Network Tool** (`src/app.py`) | Health Gate, Remediation, SoT drift, NAPALM | `:5757` (loopback) |
| **Demo UI** | static v4 dashboard | `:8080` |
| **Fabric ops portal** | topology / Mermaid / configs | `:8099` (`portal.html`) |
| **Grafana** | gNMI telemetry dashboards | `:3000` |
| **InfluxDB** | Time-series metrics store | `:8086` |

## Protocols Demonstrated

### Layer 2
- **STP/RSTP/MSTP** — Loop prevention across access layer
- **LACP/MLAG** — Multi-chassis link aggregation (cEOS pairs)
- **VLAN trunking** — 802.1Q across all vendors
- **ARP/MAC learning** — Dynamic MAC tables, ARP suppression in EVPN

### Layer 3
- **eBGP underlay** — RFC 7938 Clos fabric with per-leaf ASN (65001–65006, spines 65100)
- **eBGP EVPN overlay** — multihop loopback peering; spines as RR-clients / transit (not iBGP)
- **OSPF** — Underlay alternative (3-tier topology)
- **BFD** — Sub-second failure detection on all BGP sessions
- **ECMP** — Equal-cost multipath across spine layer

### Overlay
- **VXLAN** — Data plane encapsulation (VNI per VLAN)
- **EVPN Type-2** — MAC/IP advertisement
- **EVPN Type-3** — Inclusive multicast (BUM handling)
- **EVPN Type-5** — IP prefix routes (inter-VRF)
- **Symmetric IRB** — Distributed anycast gateway
- **ARP suppression** — Reduce BUM flooding

### Operations
- **gNMI streaming telemetry** — SR Linux + cEOS
- **NETCONF/YANG** — Configuration management
- **SSH/CLI** — Direct device access
- **REST API** — SR Linux JSON-RPC; cEOS eAPI on spine2/leaf1/leaf4 (`management api http-commands`, HTTPS:443 — baked into startup-config for NAPALM)
