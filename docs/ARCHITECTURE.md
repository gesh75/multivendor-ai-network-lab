<p align="center"><img src="assets/hero.svg" alt="multivendor-ai-network-lab — architecture" width="100%"></p>

# 🏛️ multivendor-ai-network-lab — Architecture

A closed-loop, multi-vendor network operations lab. Two real labs — a
containerlab CLOS EVPN-VXLAN fabric (Nokia SR Linux / Arista cEOS / FRR) and a
docker-compose FRR multi-region backbone — are driven by a Flask monolith on
`:5757` whose core is a **vendor-neutral driver abstraction layer** that collects
live state over docker-exec/SSH and normalizes it. On top sit an AI multi-agent
orchestrator, a governed closed-loop change pipeline
(**Predict → Blast Radius → Health Gate confirmed-commit → Watch → Verify** with
auto-rollback), event-initiated auto-remediation, auto-postmortems, an immutable
**GAIT** audit trail, and InfluxDB/Grafana telemetry. The whole surface is exposed
to AI agents through a **64-tool MCP server** and to humans through a Telegram bot
and a static demo UI.

## Table of Contents

1. [System Context](#1-system-context)
2. [Container & Component Map](#2-container--component-map)
3. [Closed-Loop Change Pipeline (sequence)](#3-closed-loop-change-pipeline-sequence)
4. [Telemetry Data Flow](#4-telemetry-data-flow)
5. [Driver Abstraction (class map)](#5-driver-abstraction-class-map)
6. [Health Gate State Machine](#6-health-gate-state-machine)
7. [Tech Stack](#tech-stack)

---

## 1. System Context

The lab sits between humans (NOC operators on the web UI / Telegram) and AI
agents (Claude Code over MCP), driving two physical labs and emitting telemetry
to observability backends while calling the Anthropic API for diagnosis.

```mermaid
flowchart TB
    operator(["👤 NOC Operator<br/>web UI · Telegram"]):::actor
    agents(["🤖 Claude Code<br/>via MCP · 64 tools"]):::actor

    system{{"🛰️ multivendor-ai-network-lab<br/>Flask :5757 · closed-loop ops"}}:::core

    labs["🧪 Two Labs<br/>CLOS EVPN-VXLAN + FRR backbone<br/>SRL · cEOS · FRR · Junos"]:::infra
    anthropic["🧠 Anthropic API<br/>claude-haiku-4-5"]:::ai
    tsdb["📊 InfluxDB 2.7<br/>+ Grafana 10.4"]:::data
    sot["🗂️ NetBox / Batfish<br/>SoT · verification"]:::data

    operator -->|"symptoms · changes"| system
    agents -->|"tool calls"| system
    system -->|"docker-exec · SSH"| labs
    system -->|"diagnose · judge"| anthropic
    system -->|"line protocol"| tsdb
    system -->|"drift · what-if"| sot
    labs -.->|"live state"| system

    classDef actor fill:#475569,stroke:#94a3b8,color:#fff
    classDef core fill:#3b82f6,stroke:#60a5fa,color:#fff
    classDef infra fill:#0ea5e9,stroke:#38bdf8,color:#fff
    classDef ai fill:#7c3aed,stroke:#a78bfa,color:#fff
    classDef data fill:#059669,stroke:#34d399,color:#fff
```

---

## 2. Container & Component Map

Inside the Flask monolith, every request resolves a device, picks a vendor
driver, and runs commands through a transport; the closed-loop, AI, and audit
modules layer on top of that single driver core.

```mermaid
flowchart TB
    subgraph FE["🖥️ Front-ends"]
        mcp["MCP Server<br/>FastMCP · 64 tools"]:::edge
        tg["Telegram Bot<br/>async · httpx"]:::edge
        ui["Static Demo UI<br/>:8080"]:::edge
    end

    subgraph API["⚙️ Flask Monolith :5757"]
        app["app.py<br/>~34 device-ops routes"]:::svc
        mvbp["mv_bp Blueprint<br/>55 /api/mv/* routes"]:::svc
    end

    subgraph LOOP["🔁 Closed-Loop Modules"]
        predict["Predict + Blast Radius"]:::accent
        gate["Health Gate<br/>confirmed-commit"]:::accent
        remed["Auto-Remediate<br/>+ Postmortem"]:::accent
    end

    subgraph CORE["🧩 Driver Core"]
        driver["Driver Abstraction<br/>factory · BaseDriver"]:::core
        transport["Transport Layer<br/>docker-exec · SSH"]:::core
    end

    orch["AI Orchestrator<br/>Pydantic agents"]:::ai
    gait["GAIT Audit<br/>append-only JSONL"]:::data
    tele["Telemetry Collector<br/>→ InfluxDB"]:::data

    mcp --> mvbp
    tg --> mvbp
    ui --> app
    app --> mvbp
    mvbp --> predict --> gate
    mvbp --> orch
    gate --> driver
    remed --> gate
    driver --> transport
    orch --> gait
    gate --> gait
    tele --> driver

    classDef edge fill:#475569,stroke:#94a3b8,color:#fff
    classDef svc fill:#3b82f6,stroke:#60a5fa,color:#fff
    classDef accent fill:#d97706,stroke:#fbbf24,color:#fff
    classDef core fill:#0ea5e9,stroke:#38bdf8,color:#fff
    classDef ai fill:#7c3aed,stroke:#a78bfa,color:#fff
    classDef data fill:#059669,stroke:#34d399,color:#fff
```

---

## 3. Closed-Loop Change Pipeline (sequence)

A governed change is gated three ways before it touches a device, then watched
during a confirmed-commit window — clean signals confirm, degraded signals
trigger automatic rollback, and every step is appended to the GAIT ledger.

```mermaid
sequenceDiagram
    actor Op as Operator / Agent
    participant API as Flask /api/change/closed-loop
    participant Pred as Predict + Blast Radius
    participant Gate as Health Gate
    participant Dev as Device (driver)
    participant Gait as GAIT Audit

    Op->>API: submit change
    API->>Pred: simulate diff + cascade depth
    Pred-->>API: verdict (APPROVE / WARN / REJECT)
    alt REJECT
        API-->>Op: blocked (blast radius)
    else proceed
        API->>Gate: apply with confirmed-commit
        Gate->>Dev: edit (PyEZ on Junos / simulated FRR)
        Gate->>Dev: watch BGP · iface · alerts
        alt signals clean
            Gate->>Dev: confirm commit
            Gate-->>Op: CONFIRMED
        else signals degrade
            Gate->>Dev: auto-rollback
            Gate-->>Op: ROLLED_BACK
        end
    end
    API->>Gait: append record (+ token cost)
```

---

## 4. Telemetry Data Flow

Raw CLI from every node is normalized by the shared driver package into a
vendor-neutral schema, fanned out in parallel into a health snapshot, and
written as InfluxDB line protocol for Grafana — with a gnmic streaming sidecar
feeding the same bucket.

```mermaid
flowchart LR
    nodes["🧪 Fabric Nodes<br/>SRL · cEOS · FRR · Junos"]:::infra
    coll["clab_collector<br/>docker exec poll"]:::svc
    parse["parsers.py<br/>vendor-neutral schema"]:::core
    snap["Health Snapshot<br/>parallel fan-out"]:::core
    influx["InfluxDB 2.7<br/>line protocol"]:::data
    graf["Grafana 10.4<br/>dashboards"]:::data
    gnmic["gnmic sidecar<br/>streaming"]:::accent

    nodes --> coll --> parse --> snap --> influx --> graf
    gnmic -->|"source-tag freshness"| influx

    classDef infra fill:#0ea5e9,stroke:#38bdf8,color:#fff
    classDef svc fill:#3b82f6,stroke:#60a5fa,color:#fff
    classDef core fill:#06b6d4,stroke:#67e8f9,color:#03121f
    classDef data fill:#059669,stroke:#34d399,color:#fff
    classDef accent fill:#d97706,stroke:#fbbf24,color:#fff
```

---

## 5. Driver Abstraction (class map)

`BaseNetworkDriver` is a template method that runs per-section commands with
fallback and a parallel health fan-out; `get_driver()` maps a canonical vendor
to a concrete subclass and auto-selects a transport that implements a common
Protocol. Every call returns a soft-failing `DriverResult`.

```mermaid
flowchart TB
    factory["get_driver(vendor)<br/>registry + factory"]:::accent
    base["BaseNetworkDriver<br/>template method · ThreadPoolExecutor"]:::core
    result["DriverResult<br/>.normalized + .raw · never raises"]:::data

    subgraph Drivers["Concrete Drivers"]
        frr["FRRDriver"]:::svc
        eos["EOSDriver"]:::svc
        srl["SRLDriver"]:::svc
        junos["JunosDriver"]:::svc
        xr["IOSXRDriver"]:::svc
    end

    subgraph Transports["Transport Protocol"]
        dock["DockerExecTransport<br/>persistent session pool"]:::edge
        ssh["SSHRunnerTransport"]:::edge
        scrapli["ScrapliTransport<br/>lazy stub"]:::edge
    end

    factory --> base
    base --> frr & eos & srl & junos & xr
    base --> result
    frr -.-> dock
    junos -.-> ssh
    eos -.-> scrapli

    classDef accent fill:#d97706,stroke:#fbbf24,color:#fff
    classDef core fill:#0ea5e9,stroke:#38bdf8,color:#fff
    classDef svc fill:#3b82f6,stroke:#60a5fa,color:#fff
    classDef edge fill:#475569,stroke:#94a3b8,color:#fff
    classDef data fill:#059669,stroke:#34d399,color:#fff
```

---

## 6. Health Gate State Machine

The Health Gate models a change as a confirmed-commit lifecycle: snapshot,
apply, watch, then either confirm or roll back — the same machine that
auto-remediation runs its fixes through.

```mermaid
stateDiagram-v2
    [*] --> PreSnapshot
    PreSnapshot --> Applied: edit committed
    Applied --> Watching: start watch window
    Watching --> Confirmed: signals clean
    Watching --> RolledBack: signals degrade
    Confirmed --> [*]
    RolledBack --> [*]

    note right of Watching
        re-poll BGP · iface · alerts
        over the watch window
    end note

    classDef good fill:#059669,stroke:#34d399,color:#fff
    classDef bad fill:#e11d48,stroke:#fb7185,color:#fff
    classDef work fill:#d97706,stroke:#fbbf24,color:#fff

    class Confirmed good
    class RolledBack bad
    class Watching work
```

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Network labs** | containerlab · docker-compose · Nokia SR Linux · Arista cEOS · FRR · Junos (cRPD/vJunos) |
| **Driver core** | Python ABC · dataclasses · `concurrent.futures` · registry/factory · `typing.Protocol` |
| **Transport** | subprocess (arg-list, no `shell=True`) · persistent docker-exec session pool · SSH |
| **API** | Flask · Flask Blueprints · gunicorn |
| **Closed loop** | junos-eznc (PyEZ confirmed-commit) · optional Batfish digital twin |
| **AI** | Anthropic SDK (`claude-haiku-4-5`) · Pydantic · JSON-mode prompting · LLM-as-judge eval |
| **Audit** | append-only JSONL · threading lock · date-rotated GAIT ledger |
| **Telemetry** | InfluxDB 2.7 line protocol · Grafana 10.4 · gnmic streaming sidecar |
| **Agent / human surfaces** | FastMCP (64 tools) · python-telegram-bot v20+ · httpx · launchd |

---

<p align="center"><sub>Generated architecture documentation · diagrams render natively on GitHub (Mermaid + animated SVG).</sub></p>
