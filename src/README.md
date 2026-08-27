# GESH AI Network Tool

**Enterprise-grade AI-native network operations platform — zero greenfield, full intelligence layer.**

An all-in-one network operations dashboard that wraps existing SSH, NAPALM, Batfish, and NetBox capabilities in an AI translation layer. Runs as a Flask API with a self-contained HTML/JS UI. Supports both **production Juniper/Arista environments** (440+ devices, 50+ sites) and a **local Docker FRR lab** (10-node multi-site BGP+OSPF topology) for development and demos.

---

## The Invention Pattern

Every feature in this tool follows the same 3-column pattern:

```
Existing capability  +  AI translation layer  +  UI tab  =  New tool
─────────────────────────────────────────────────────────────────────
SSH + Qwen3              NL→CLI prompt              AI Command
Batfish scripts          analyze endpoint            Pre-Deploy Check
Netmiko loops            Nornir parallel engine      Nornir Engine
LibreNMS + Kibana        Keep correlation            Alert Correlation
SNMP polling             gNMI + Telegraf             Streaming Telemetry
SSH neighbor data        D3.js topology              OSPF Discover
```

No rip-and-replace. No greenfield. Every tab surfaces what was already there.

---

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Python 3.10+
- (Optional) Docker Model Runner with `qwen3:latest` for on-prem LLM

### Lab Mode (no production access needed)

```bash
# Clone the repo
git clone https://github.com/gesh75/multivendor-ai-network-lab.git
cd gesh-ai-network-tool

# Start FRR lab containers + Flask API
./network-lab/start_lab_tool.sh

# Open the demo UI
open http://localhost:8080/

# Or use the Flask API directly
open http://localhost:5757/api/devices
```

### Production Mode

```bash
cd 04_Scripts_Tools/DCN_Network_Tool
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env: NETBOX_URL, NETBOX_TOKEN, DCN_PKCS11_PIN, DCN_SSH_USER, LLM_*
# DCN_PKCS11_PIN is required when DCN_SSH_MODE=pkcs11 (no default PIN).

python3 app.py
# Open http://localhost:5757
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Demo UI (index.html)                      │
│   18 tabs: AI Command, OSPF, Nornir, Batfish, Telemetry...  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API (port 5757)
┌──────────────────────────▼──────────────────────────────────┐
│                   Flask API (app.py)                         │
│  /api/ai-command  /api/nornir/run  /api/batfish/analyze     │
│  /api/ospf/discover  /api/keep/correlate  /api/telemetry    │
└────┬──────────────┬──────────────┬──────────────┬───────────┘
     │              │              │              │
┌────▼────┐   ┌─────▼────┐  ┌─────▼────┐  ┌─────▼────────┐
│  FRR    │   │  Qwen3   │  │ Batfish  │  │  NetBox      │
│  Lab    │   │ (Docker  │  │ (Static  │  │  LibreNMS    │
│  (SSH)  │   │  Model   │  │  Config  │  │  Grafana     │
│ 10 ctrs │   │  Runner) │  │  Anlys.) │  │  Kibana      │
└─────────┘   └──────────┘  └──────────┘  └──────────────┘
```

### LLM Chain (AI Command + Agent Chat)

```
Request → (1) Qwen3 via Docker Model Runner TCP
        → (2) Qwen3 via Docker Unix socket (fallback)
        → (3) claude-haiku-4-5 via Anthropic API (fallback)
```

On-prem first, cloud only if needed. No data leaves the network by default.

---

## Lab Topology — 10 FRR Containers

| Hostname        | IP          | SSH Port | AS    | Role                       | Site   |
| --------------- | ----------- | -------- | ----- | -------------------------- | ------ |
| de-fra-core-01  | 10.200.0.11 | 2201     | 65001 | Core Router DE-FRA         | DE-FRA |
| de-fra-core-02  | 10.200.0.12 | 2202     | 65002 | Core Router DE-FRA         | DE-FRA |
| uk-lon-core-01  | 10.200.0.13 | 2203     | 65003 | Core Router UK-LON         | UK-LON |
| nl-ams-core-01  | 10.200.0.14 | 2204     | 65004 | Core Router NL-AMS         | NL-AMS |
| us-nyc-core-01  | 10.200.0.15 | 2207     | 65005 | Core Router US-NYC         | US-NYC |
| de-fra-edge-01  | 10.200.0.21 | 2205     | 65006 | Edge Router DE-FRA         | DE-FRA |
| uk-lon-edge-01  | 10.200.0.22 | 2208     | 65007 | Edge Router UK-LON         | UK-LON |
| nl-ams-edge-01  | 10.200.0.23 | 2209     | 65008 | Edge Router NL-AMS         | NL-AMS |
| uk-lon-dist-01  | 10.200.0.31 | 2206     | 65010 | Distribution Switch UK-LON | UK-LON |
| de-fra-dist-01  | 10.200.0.33 | 2210     | 65009 | Distribution Switch DE-FRA | DE-FRA |

**Protocols:** OSPF area 0 on all 10 devices (interface-mode, hello=5s, dead=20s). BGP sessions between cores, edges, and distribution switches across 4 sites.

**BGP Sessions:**
- de-fra-core-01 ↔ de-fra-core-02
- de-fra-core-01 ↔ uk-lon-core-01
- de-fra-core-02 ↔ nl-ams-core-01
- de-fra-core-01 ↔ us-nyc-core-01
- de-fra-core-01 ↔ de-fra-edge-01 (dual-homed via core-02)
- uk-lon-core-01 ↔ uk-lon-edge-01
- nl-ams-core-01 ↔ nl-ams-edge-01
- uk-lon-core-01 ↔ uk-lon-dist-01
- de-fra-core-01 ↔ de-fra-dist-01

---

## BGP Failure Simulation

```bash
./network-lab/sim_bgp_failure.sh status   # show all BGP summaries
./network-lab/sim_bgp_failure.sh break    # drop de-fra-core-01 <-> uk-lon-core-01 (red in ~15s)
./network-lab/sim_bgp_failure.sh fix      # restore all sessions
./network-lab/sim_bgp_failure.sh chaos    # random 30s failure on random peer
```

---

## Dashboard Tabs — All 18

### P1 — Core AI Features

#### 💬 AI Command
Natural language → CLI → live output → AI explanation.

> "Show BGP neighbors on de-fra-core-01"
> → `vtysh -c 'show bgp summary'` → parsed table + Qwen3 analysis

Translates English to device-appropriate CLI (FRR/JunOS/EOS), executes live via SSH, returns raw output + plain-English explanation.

#### 🤖 Agent Chat
Multi-agent coordinator with 9 specialized agents. Unlike AI Command (single device, single query), Agent Chat handles cross-device, multi-hop investigations and returns structured findings + follow-up suggestions.

| Agent | Responsibility |
| ----- | -------------- |
| NetworkTopologyAgent | Maps live neighbor relationships |
| BGPAnalysisAgent | Cross-device BGP health correlation |
| OSPFAnalysisAgent | OSPF state and timer analysis |
| InterfaceMonitorAgent | Interface errors, flaps, utilization |
| SecurityAuditAgent | Auth, ACLs, SNMP, BGP MD5 checks |
| ConfigComplianceAgent | Drift vs. known-good baseline |
| TrafficAnalysisAgent | Bandwidth and utilization patterns |
| IncidentResponseAgent | Root cause + remediation for alerts |
| CapacityPlanningAgent | Port utilization and growth forecasting |

#### 🔍 Pre-Deploy (Batfish)
Paste a config snippet → static analysis before pushing to production.

Catches: plaintext BGP auth keys, missing export policies, undefined route references. Returns ERROR / WARNING / PASSED counts with line-level detail. Example: `2 ERRORS / 3 WARNINGS / 9 PASSED`.

#### ⚡ Nornir Engine
Parallel device audits using Nornir with 50 concurrent workers.

```
BGP Health Check across DE-FRA (8 devices)
Completed in 3.2s (vs ~40s sequential Netmiko)
Per-device: OK / WARN / ERROR with detail
```

Available tasks: `bgp_health`, `version`, `interface_check`, `alarm_check`, `routing_table`

#### 🔔 Alert Correlation
Runs raw alerts through the Keep correlation engine. Input: LibreNMS + Kibana + Grafana alerts. Output: incidents vs. suppressed, noise reduction ratio. Example: 8 alerts → 2 incidents, 6 suppressed (4× noise reduction).

#### 📡 Streaming Telemetry
Live sparkline charts updating every 1s from gNMI/Telegraf. Metrics: CPU %, Memory %, Interface RX/TX Gbps, BGP prefix counts. Stream latency ~2.4ms vs 5-minute SNMP polling intervals.

### P2 — Device Operations

#### 🖥️ Run Command
Execute any CLI command on any device with quick-access buttons for common operations (interfaces, BGP, ARP, routes, logs).

#### 🌐 Probing
Ping, traceroute, and MTR from the device itself — not from the management host.

#### 📸 Device Snapshot
One-click parallel collection: version, interfaces, BGP, ARP, routes, alarms, logs.

#### 💻 CLI Transport (Fleet Collect)
Run a command across an entire site simultaneously and collect output from all devices. Fleet mode: site-wide collection in seconds. Bench mode: side-by-side device comparison.

#### 🗺️ OSPF Discover
Auto-discovers the live OSPF topology across the entire lab or site. Reads `show ip ospf neighbor` from every device in parallel. Builds a D3.js force-directed graph with real neighbor relationships (state, interface IPs, uptime, area). Lab result: 10 nodes, 69 links discovered automatically.

#### 📊 Health Cards
Per-device health metrics: CPU, memory, uptime, interface error rates. Color-coded health scores (GREEN/YELLOW/RED) from live SSH queries.

#### 📋 Compliance Scanner
18 compliance checks against known-good baselines: BGP auth, prefix limits, OSPF timers, NTP, DNS, SNMP community strings. Pass/fail per device per check.

#### 🔒 Security Audit
CVE awareness, crypto strength, ACL review, SNMP security, BGP authentication. LLM provides compound risk assessment (e.g., weak auth + no ACL = high risk).

#### 📈 Deep Analysis
20+ commands cross-correlated into a scored health report. LLM generates executive narrative.

#### 📝 Log Intelligence
Classifies ~250 syslog message patterns by severity and category. LLM generates root cause hypotheses.

#### ⚙️ Config Drift
Detects unauthorized changes vs. NetBox-sourced baselines. 18 compliance checks.

#### 🔬 PyEZ Collector
Structured NETCONF collection: FPC/linecard health, optic diagnostics (RX/TX power, temperature, voltage), real-time port statistics, error counters. Junos devices only.

---

## API Reference

| Endpoint | Method | Body | Description |
| -------- | ------ | ---- | ----------- |
| `/api/devices` | GET | — | List all lab devices |
| `/api/run` | POST | `{hostname, raw}` | SSH exec on a device |
| `/api/ai-command` | POST | `{query, hostname}` | NL→CLI→SSH→explain |
| `/api/agent-chat` | POST | `{message, session_id}` | Multi-agent coordinator |
| `/api/nornir/run` | POST | `{task, site, workers}` | Parallel Nornir audit |
| `/api/batfish/analyze` | POST | `{config}` | Static config analysis |
| `/api/ospf/discover` | POST | `{site}` | OSPF topology discovery |
| `/api/pyats/snapshot` | POST | `{hostname}` | Pre/post state capture |
| `/api/pyats/diff` | POST | `{hostname}` | State diff |
| `/api/keep/correlate` | GET | — | Alert correlation |
| `/api/telemetry/status` | GET | — | Telegraf/InfluxDB status |
| `/api/compliance/scan` | POST | `{hostname}` | Run compliance checks |
| `/api/health-cards` | POST | `{site}` | Device health metrics |
| `/api/cli-transport/fleet` | POST | `{command, site}` | Site-wide command collect |
| `/api/topology/site` | POST | `{site}` | Live LLDP/BGP topology |

---

## Production Scope

When pointed at a real network (via `.env`):

- **411 devices / 53 sites** managed via NetBox
- **7,300+ NetBox records**: 60 sites, 7,303 devices, 11,645 VMs, 37,526 IPs, 428 circuits
- **Juniper**: SRX (firewall), MX (core router), EX/QFX (access/distribution)
- **Arista**: EOS switches
- **SSH auth**: YubiKey PIV (`DCN_SSH_MODE=pkcs11` + `DCN_PKCS11_PIN`) or key file (`DCN_SSH_MODE=key`). PKCS#11 has no baked-in PIN; unset PIN fails init and falls back to key mode.
- **LLM**: Qwen3 via Docker Model Runner — on-prem, no data leaves the network

---

## Key Files

```
04_Scripts_Tools/DCN_Network_Tool/
├── app.py                  # Flask API — all endpoints
├── app.js                  # Frontend JS
├── index.html              # Main UI
├── nornir_engine.py        # Parallel audit engine
├── session_audit.py        # SSH session audit trail
├── requirements.txt

demo/
├── index.html              # Full-featured demo UI (self-contained)
├── architecture.html       # Architecture diagram

network-lab/
├── docker-compose.yml      # 10 FRR container topology
├── start_lab_tool.sh       # One-command lab startup
├── sim_bgp_failure.sh      # BGP failure simulation
├── cli_proxy.py            # CLI transport proxy
├── configs/                # Per-device FRR configs (BGP + OSPF)
│   ├── r1/ r2/ r3/ r4/ r5/ r6/ r7/ r8/
│   └── sw1/ sw2/
└── ssh-keys/
    └── lab_key             # SSH key for FRR container access
```

---

## FRR SSH Notes

- SSH connects as `root` using `network-lab/ssh-keys/lab_key`
- Shell drops to **bash**, not vtysh — use `exec_command("vtysh -c 'cmd'")`
- BGP summary: `parts[9]` = State/PfxRcd (numeric = Established)
- OSPF: interface-mode only (`ip ospf area 0` per interface)
- Commands: `show interface` (singular) not `show interfaces`

---

## Roadmap

1. **Auto-remediation runbooks** — Fix button on red topology links
2. **MCP server** — expose topology/devices/nornir as MCP tools for Claude Code
3. **LLDP/OSPF auto-discovery** — replace static CSV with live neighbor walk (OSPF Discover tab is the prototype)
4. **RAG over vendor docs** — ChromaDB + FRR/Junos/EOS docs for error explanation
5. **Config change approval workflow** — AI proposes → human approves → pyATS diffs before/after
6. **Compliance scanner expansion** — coverage for all DCN policy controls

---

*Built on: Flask, Nornir, NAPALM, Netmiko, Batfish, PyEZ, pynetbox, FRRouting, Docker, Qwen3, D3.js, Chart.js*
