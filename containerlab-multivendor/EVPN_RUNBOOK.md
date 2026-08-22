# CLOS EVPN VXLAN Multi-Vendor Fabric — Runbook

## Topology
3 spines × 6 leaves × 6 hosts. Three vendors mixed across spine and leaf tiers:

| Tier | Nokia SR Linux | Arista cEOS | FRR (Linux) |
|---|---|---|---|
| Spine | spine1 (65100) | spine2 (65100) | spine3 (65100) |
| Leaf | leaf2 (65002), leaf5 (65005) | leaf1 (65001), leaf4 (65004) | leaf3 (65003), leaf6 (65006) |

Underlay = eBGP IPv4 over /31 P2P (per-leaf ASN).
Overlay = eBGP L2VPN-EVPN over loopbacks, multihop, per-neighbor peer-AS.

## Service plan

| Rack | VLAN | L2 VNI | RT | Hosts | Subnet |
|---|---|---|---|---|---|
| 1 | 10 | 10010 | `1:10010` | host1, host2 | 10.10.10.0/24 |
| 2 | 20 | 10020 | `1:10020` | host3, host4 | 10.10.20.0/24 |
| 3 | 30 | 10030 | `1:10030` | host5, host6 | 10.10.30.0/24 |

L3 VRF `TENANT-A` (cEOS only currently): L3 VNI 50001, RT `1:50001`.

## VTEP addressing

| Leaf | system loopback (router-id) | VTEP source (lo1) |
|---|---|---|
| leaf1 cEOS | 10.255.1.1 | 10.255.100.1 |
| leaf2 SRL  | 10.255.1.2 | 10.255.100.2 |
| leaf3 FRR  | 10.255.1.3 | 10.255.100.3 |
| leaf4 cEOS | 10.255.1.4 | 10.255.100.4 |
| leaf5 SRL  | 10.255.1.5 | 10.255.100.5 |
| leaf6 FRR  | 10.255.1.6 | 10.255.100.6 |

> SRL leaves source VXLAN from system0 (10.255.1.X) per default; cEOS and FRR source from lo1 (10.255.100.X). Both reachable via underlay BGP.

## Deploy / Redeploy

Use the wrapper scripts — they pick **native `containerlab`** on Linux (sudo-aware)
and the **`ghcr.io/srl-labs/clab` image with `--pid host`** on macOS Docker Desktop.
Do not copy a raw `containerlab deploy` from a Linux box onto macOS without that flag.

```bash
cd containerlab-multivendor
./scripts/setup.sh
./scripts/deploy.sh clos-evpn
bash ./scripts/post-deploy-srl.sh 30    # SRL nodes boot blank — required
./scripts/verify.sh                     # or ./scripts/check_fabric.sh
```

The FRR leaf Linux netdev setup (lo1, bridge, VXLAN, host-port attach) is baked into the topology YAML `exec:` blocks for leaf3 and leaf6 — no extra FRR bootstrap script needed.

Expected outcome: a healthy fabric reports ~54 BGP sessions up across the 9 network nodes (`verify.sh` / collector). Older `check_fabric.sh` output still says `37 checks passed` on the underlay/overlay subset.

**cEOS eAPI (NAPALM):** `leaf1`, `leaf4`, and `spine2` startup-configs enable
`management api http-commands` (HTTPS:443, default VRF) plus a local `admin`
user. That is the durable path — cEOS's eAPI uwsgi backend only spawns at boot.
Never `docker restart` a clab node to "turn eAPI on"; redeploy with
`./scripts/deploy.sh clos-evpn` (`--reconfigure`).

## Multi-vendor design decisions

1. **Overlay AS scheme: per-neighbor eBGP, not iBGP.** Each leaf has a unique underlay ASN (65001-65006). The spine OVERLAY peer-groups don't set group-level `remote-as`; each neighbor gets a per-neighbor `peer-as` matching the leaf's actual ASN. Works on all three vendors uniformly.
2. **Explicit RTs everywhere.** FRR auto-RT is `<asn>:<vni>` (e.g., `65003:10020`); cEOS/SRL default differently. To interop, every leaf has explicit `route-target import/export 1:<vni>` configured.
3. **SRL needs explicit BGP overlay policy.** SRL's default-deny policy filters generated EVPN routes. Each SRL leaf has `evpn-rr export-policy [accept-all]` and `import-policy [accept-all]` set.
4. **cEOS L2 EVPN config required.** cEOS doesn't auto-generate EVPN type-2/3 routes from vlan→vni mapping; explicit `vlan X / rd ... / route-target both ... / redistribute learned` blocks under `router bgp` are required.

## Common failure modes (from the bring-up)

| Symptom | Cause | Fix |
|---|---|---|
| Overlay BGP stuck `Active` | AS mismatch between spine and leaf | Use per-neighbor peer-as on spine matching leaf's underlay AS |
| `Idle` overlay session in FRR | Peer-group missing `remote-as` binding | `neighbor X remote-as Y` before `peer-group OVERLAY` |
| EVPN session up but no routes received | RT mismatch between vendors | Set explicit `1:<vni>` RT on all leaves |
| SRL mac-vrf up but 0 IMET routes | SRL default-deny export policy | `set ... group evpn-rr export-policy [accept-all]` |
| FRR host can't ping remote host | No remote MAC import | Add `vni <vni> / route-target import/export 1:<vni>` under `address-family l2vpn evpn` |

## Files changed during bring-up

```
configs/spine/spine1-srl.cfg       — overlay AS 65199 → per-neighbor peer-as
configs/spine/spine2-ceos.cfg      — overlay AS 65199 → per-neighbor remote-as + next-hop-unchanged
configs/spine/spine3-frr.conf      — per-leaf remote-as in OVERLAY group (eBGP)
configs/leaf/leaf1-ceos.cfg        — vlan 10/20/30 RT blocks
configs/leaf/leaf4-ceos.cfg        — vlan 10/20/30 RT blocks
configs/leaf/leaf2-srl.cfg         — lo1, vxlan1, mac-vrf-10, evpn-rr accept-all policies
configs/leaf/leaf5-srl.cfg         — lo1, vxlan1, mac-vrf-30, evpn-rr accept-all policies
configs/leaf/leaf3-frr.conf        — per-VNI L2 RT, advertise-all-vni, advertise-svi-ip
configs/leaf/leaf6-frr.conf        — per-VNI L2 RT, advertise-all-vni, advertise-svi-ip
topologies/clos-evpn.clab.yml      — exec: netdev bootstrap for leaf3, leaf6
scripts/check_fabric.sh            — 37-check fabric health (NEW)
scripts/setup_frr_vtep.sh          — manual FRR netdev bootstrap if needed (NEW, redundant after YAML bake-in)
```

## Verification commands

```bash
# Full fabric health
./scripts/check_fabric.sh

# Same-VLAN data plane (cross-vendor L2)
docker exec clab-clos-evpn-host1 ping -c 3 10.10.10.2   # cEOS ↔ SRL
docker exec clab-clos-evpn-host3 ping -c 3 10.10.20.2   # FRR  ↔ cEOS
docker exec clab-clos-evpn-host5 ping -c 3 10.10.30.2   # SRL  ↔ FRR

# EVPN route table on RR
docker exec clab-clos-evpn-spine2 Cli -p 15 -c 'show bgp evpn'
```

## Shipped since the original bring-up (do not re-open as greenfield)

- **ESI-LAG dual-homing** — hosts are dual-homed (anycast MAC `00:00:5E:00:53:01`). Pairing: rack-1 leaf1(cEOS)+leaf2(SRL), rack-2 leaf3(FRR)+leaf4(cEOS), rack-3 leaf5(SRL)+leaf6(FRR). Ethernet-segment IDs must match across the pair (Type-0 10-byte ESI).
- **IPv6 dual-stack underlay** — `fd00:dc1::/48` on P2P links and loopbacks; spines/leafs peer IPv6 eBGP alongside IPv4.
- **cEOS eAPI for NAPALM** — baked into spine2 / leaf1 / leaf4 startup-configs (see Deploy).

## Remaining gaps

- **Symmetric IRB is incomplete across vendors.** FRR leaf3/leaf6 carry `vrf TENANT-A` and anycast SVIs (`10.10.20.254` / `10.10.30.254`). FRR in-container has no kernel VRF, so L3 VNI 50001 cannot decap on those leafs (host6 bond primary stays on SRL leaf5). SRL IRB / Type-5 inter-VLAN routing is still the unfinished L3 piece.
- **BFD on the underlay.** FRR `bfdd` is enabled in daemons files; per-session BFD on cEOS/SRL underlay neighbors is not a completed fabric-wide feature.
- **Grafana EVPN panels.** gnmic→InfluxDB→Grafana collects underlay metrics; EVPN peer count, per-VNI route count, and VTEP tunnel state panels are still backlog.
