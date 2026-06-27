# 🧠 SynapseITSM

An AI-powered IT Service Management (ITSM) system where users describe IT problems in plain language, and a multi-agent system triages, diagnoses, and remediates them. It integrates a Human-in-the-Loop (HITL) workflow, ensuring all remediation actions require explicit operator approval before execution.

A key capability is **remote remediation**: once an operator approves a fix, the Remediation agent can apply it **directly on the affected user's PC or laptop** — even off-site — via a self-hosted [MeshCentral](https://meshcentral.com) endpoint-management layer. The user does nothing technical; the verified fix is pushed to their machine and the result is reported back automatically.

Built as a graduation project demonstration utilizing **LangGraph**, **FastAPI**, **Chainlit**, **Streamlit**, and **MeshCentral**.

---

## 🗺️ Agent Pipeline

The diagram below outlines the full flow — from a user message through triage, Root Cause Analysis (RCA), remediation planning, and human approval, as well as the background monitoring loop.

![SynapseITSM Agent Pipeline](./diagram_final_intake_cmdb.svg)

---

## ⚙️ Core Architecture & Workflow

The orchestration is built as a state machine using **LangGraph**. The state is passed sequentially from node to node, accumulating findings and logs.

```
User message
     │
     ▼
 Fast-path ──(high confidence)──► 💡 Deflect (KB answer)
     │
  (low confidence)
     │
     ▼
 🗂️  Intake Agent         classifies: incident / request
     │
     ▼
  Routing Node
     ├── request ──► LLM answer ──► END
     └── incident
           │
           ▼
 🔍  RCA Agent            root cause analysis + CMDB query
           │
           ▼
 🛠️  Remediation Agent    selects runbook
           │
           ▼
 👤  HITL (pause)         IT team approves/rejects in dashboard
           │
     ┌─────┴─────┐
  approved     rejected
     │              │
     ▼              ▼
 ▶️  Runbook       🚨 Escalate
    Execute
     │
  ┌──┴───┐
 pass   fail
  │       │
 ✅ Close  📋 Report ──► Notify IT ──► 📧 Email alert
```

### 🤖 Multi-Agent System Roles

1. **Fast-Path / Deflection (ChromaDB Vector Search)**: Intercepts incoming requests immediately. It queries a ChromaDB vector database to find semantically similar past incidents. If a high-confidence match is found, it directly proposes the known resolution (deflection).
2. **Triage / Intake Agent (Llama 3.1 8B)**: If deflection fails or the user states the solution was not helpful, the Intake Agent classifies the ticket category (`incident` or `request`), extracts the affected Configuration Item (CI) name, and computes the initial priority (P1–P4) based on system impact.
3. **Root Cause Analysis (RCA) Agent (Llama 3.3 70B)**: Active only for incidents. It connects directly to real-time system metrics (CPU, memory, database connection counts, network latency) and queries the Configuration Management Database (CMDB) to trace upstream and downstream dependencies. It synthesizes this data to identify the true root cause.
4. **Remediation Agent (Llama 3.3 70B)**: Reviews the RCA findings and matches them against the available runbooks. It prepares a step-by-step execution plan and constructs the exact parameters needed for the runbook tool. For endpoint-class issues, it resolves an **execution target** — local server vs. the affected user's enrolled device — and dispatches the runbook accordingly.
5. **Human-in-the-Loop (HITL) Node**: Pauses the LangGraph execution state when a runbook action is proposed. The state remains suspended until an operator approves or rejects the action via the Streamlit dashboard.
6. **Monitoring / Alerting Agent**: A background task that polls system metrics. If an anomaly is detected, it automatically generates a P1 incident ticket and triggers the graph workflow.

---

## 🖥️ Remote Remediation (MeshCentral)

SynapseITSM can apply fixes **on the end user's own machine**, not just on the server. This closes the loop on endpoint problems (DNS, network adapter, VPN, network stack) that previously required a technician to physically touch the device.

### How it works

```
Approved runbook
      │
      ▼
 Resolve execution target ──► local server  ──► subprocess (existing behavior)
      │
      └────────────────────► remote device (user's PC)
                                   │
                                   ▼
                      meshctrl runcommand (base64 PowerShell)
                                   │
                                   ▼
                       MeshAgent runs the script on the PC
                                   │
                       Report-Step POSTs each step's result
                                   ▼
                       POST /agent/result  (HMAC-verified)
                                   │
                                   ▼
                  Backend awaits callback, verifies, closes ticket
```

* **MeshCentral** is a self-hosted remote-management server. A lightweight **MeshAgent** installed on each user device dials home over an outbound WebSocket — **no inbound ports or public IP required** on the user side.
* The backend drives MeshCentral through the **`meshctrl` CLI** (via subprocess), avoiding a re-implementation of MeshCentral's WebSocket auth protocol.
* Because `meshctrl runcommand` does not reliably return script output, each remote runbook uses a **self-report pattern**: the PowerShell script POSTs structured per-step results to `POST /agent/result`, secured with a **per-job HMAC token** (`X-Job-Token`). The backend blocks on an `asyncio.Event` until the callback arrives.
* **The HITL gate is preserved end-to-end** — nothing runs on a user's PC until IT approves it in the dashboard.

### Linking a user to a device

Devices are mapped to users by a per-user `meshcentral_nodeid` (plus hostname / IP / OS / online status) stored on the `users` table. A dedicated **Device Manager** Streamlit page lets IT:

* Search users by email, name, or ID
* Auto-map devices via **Sync from MeshCentral** (matches the MeshCentral device name to a user's email)
* Manually link / unlink a device's Node ID

> Remote-capable runbooks: `diagnose_internet`, `flush_dns`, `reset_network_adapter`, `reconnect_vpn`, `reset_network_stack`. Server-side runbooks (DB pool, web/app service, cache, workers) continue to run locally. If a device is offline or unlinked, execution **falls back to the local server** automatically.

See [`docs/MESHCENTRAL_PLAN.md`](docs/MESHCENTRAL_PLAN.md) for the full design and build order.

---

## 📊 Database Architecture

The project splits its data requirements between a relational database for operational consistency and a vector database for semantic retrieval.

### 1. PostgreSQL (Relational & Operational DB)
PostgreSQL handles the structured relational data. The schema is managed via SQLAlchemy in `src/synapse/db/models.py`:
* **Configuration Items (`configuration_items`)**: The CMDB containing 34 seeded infrastructure assets (e.g., `POS-01` terminal, `DB-01` PostgreSQL primary database, `REDIS-03` cache).
* **CI Relationships (`ci_relationships`)**: The topology dependency graph mapping links (e.g., `POS-01` depends on `LB-02`, which depends on `APP-03`).
* **Tickets (`tickets`)**: Active and historical tickets containing category, priority, status, and summary.
* **Action Logs (`action_log`)**: Sequential records of runbook proposals, approvals, executions, or failures.
* **Users (`users`)**: Relational records for identity, roles (`admin`, `it_team`, `end_user`), and password hashes. Also holds the **device-link columns** (`meshcentral_nodeid`, `device_hostname`, `last_known_ip`, `os_platform`, `agent_online`, `device_last_seen`) that bind a user to their enrolled remote-remediation endpoint.

### 2. ChromaDB (Vector Store & RAG)
ChromaDB handles semantic retrieval and the agentic "learning loop" in `src/synapse/rag/`:
* **Knowledge Base Collection (`incident_kb`)**: Stores 95 seeded IT incident records, pairing unstructured symptoms and root causes with structured remediation metadata.
* **Learning Loop**: When a ticket is resolved, its final symptom, verified root cause, and successful remediation ID are auto-embedded back into ChromaDB so the system becomes smarter over time.

---

## 🎲 Anomaly Simulator & Expanded Scenarios

The simulator (`src/synapse/sim/generator.py`) reads `src/synapse/sim/scenarios.yaml` to simulate real-time IT failures:
* **Expanded Dataset**: Contains 63 distinct monitoring scenarios (50 expanded retail/POS scenarios running first, followed by 13 core infrastructure scenarios).
* **Execution Interval**: Spaced exactly **1 minute** apart.
* **Immediate Firing**: The first scenario fires **30 seconds** after starting the application, providing immediate data for demonstration.
* **Covered Domains**: Spans network outages, POS terminal crashes, web application chunk failures, database connection pool exhaustion, authentication bottlenecks, and memory leak/CPU thrashing events.

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| 🤖 Agent orchestration | LangGraph |
| 🔀 LLM routing | LiteLLM (Groq / Gemini / Ollama) |
| 🚀 Backend API | FastAPI + Uvicorn + SQLAlchemy |
| 💬 Chat UI | Chainlit |
| 📊 Operations dashboard | Streamlit |
| 🗄️ Database | PostgreSQL (via Docker) |
| 🔄 Migrations | Alembic |
| 🔍 Vector store (RAG) | ChromaDB |
| 📖 Runbook server | FastMCP |
| 📧 Email alerts | Resend API |
| 🖥️ Remote endpoints | MeshCentral + `meshctrl` CLI |

---

## ✅ Prerequisites

- Python 3.11+
- Docker Desktop (for PostgreSQL — and optionally MeshCentral)
- A free [Groq API key](https://console.groq.com)
- *(Optional, for remote remediation)* Node.js 18+ and the `meshctrl` CLI (`npm install -g meshcentral`)

---

## 🚀 Quick Start

### 1. Clone and set up environment

```bash
git clone https://github.com/YOUR_USERNAME/synapseitsm.git
cd synapseitsm

python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and configure at minimum:

```env
GROQ_API_KEY=your_groq_key_here        # from console.groq.com (free)
JWT_SECRET=any-long-random-string
CHAINLIT_AUTH_SECRET=any-long-random-string
```

### 3. Start the database

```bash
docker compose up -d db
```

Wait ~5 seconds for PostgreSQL to initialize, then:

```bash
# Run migrations
python -m alembic upgrade head

# Seed CMDB, users, and historical tickets
python -m synapse.db.seed

# Ingest RAG knowledge base into ChromaDB
python -m synapse.rag.ingest
```

### 4. Run the application (3 terminals)

**Terminal 1 — Backend API (Core Engine + Monitoring Loop)**
```bash
python -m uvicorn synapse.api.main:app --host 0.0.0.0 --port 8000 --reload

```

**Terminal 2 — Chat UI (Chainlit Client)**
```bash
chainlit run ui/chat_app.py --port 8001
```

**Terminal 3 — Operations Dashboard (Streamlit UI)**
```bash
streamlit run ui/dashboard.py --server.port 8502
```

**Terminal 4 — Device Manager (link users to remote devices)** *(optional)*
```bash
streamlit run ui/device_manager.py --server.port 8503
```

| Component | URL |
|---|---|
| 💬 Chat UI (end users) | http://localhost:8001 |
| 📊 Ops Dashboard (IT team) | http://localhost:8502 |
| 🖥️ Device Manager (IT team) | http://localhost:8503 |
| 📄 API Swagger Docs | http://localhost:8000/docs |

---

## 🖥️ Enabling Remote Remediation *(optional)*

Remote remediation is **off by default** — the system runs fully without it. To enable applying fixes on users' machines:

### 1. Start MeshCentral

```bash
docker compose --profile meshcentral up -d
```

Then open `https://<host>:8443`, create an admin account, and create a device group named **`SynapseITSM-Endpoints`**. (`meshcentral-config.json` ships a ready config — set `cert` to your host's LAN IP so other machines can connect.)

### 2. Install the `meshctrl` CLI

```bash
npm install -g meshcentral
```

### 3. Configure `.env`

```env
MESHCENTRAL_ENABLED=true
MESHCENTRAL_URL=wss://<host>:8443/control.ashx
MESHCENTRAL_USER=<your-meshcentral-admin-email>
MESHCENTRAL_PASSWORD=<your-meshcentral-admin-password>
MESHCENTRAL_DEVICE_GROUP=SynapseITSM-Endpoints
MESHCENTRAL_VERIFY_TLS=false                       # true in prod with real certs
# npm installs meshctrl as a .js file — invoke it via node directly:
MESHCENTRAL_MESHCTRL=node /path/to/node_modules/meshcentral/meshctrl.js
API_BASE_URL=http://<host>:8000                    # the address user devices call back to
```

> The backend must be reachable from user devices at `API_BASE_URL` for the result callback. Bind it with `--host 0.0.0.0` and allow inbound TCP on port `8000` in your firewall.

### 4. Enroll a device & link it

1. In MeshCentral, open the **SynapseITSM-Endpoints** group → **Add Agent** → run the installer on the user's PC (it installs a background service).
2. Rename the device in MeshCentral to the user's **email** (e.g. `sara@synapse.io`).
3. In the **Device Manager** (port 8503), click **Sync from MeshCentral** — the device auto-links to the matching user.

> The device-link columns are added by migration `0003` (already included in `alembic upgrade head`). If you set up the DB on an older schema, run `python -m alembic upgrade head` again.

---

## 👥 Demo Accounts

| Email | Password | Role | Description |
|---|---|---|---|
| `admin@synapse.io` | `admin123` | 🔑 Admin | Full access to backend and configuration |
| `it@synapse.io` | `it123456` | 🛠️ IT Team | Can approve/reject proposed runbooks on dashboard |
| `sara@synapse.io` | `sara123` | 👤 End User | Submit and track own tickets on Chat UI |
| `omar@synapse.io` | `omar123` | 👤 End User | Submit and track own tickets on Chat UI |

---

## 🎮 Try It Out

1. **Submit an Incident**: Open the Chat UI (http://localhost:8001) and log in as `sara@synapse.io`.
2. **Describe the Problem**: Type: *"The sales dashboard is down, users can't access it"*. The agent will classify the alert, check the database dependency graph, perform an RCA, and propose a runbook.
3. **Operator Approval**: Open the Ops Dashboard (http://localhost:8502) and log in as `it@synapse.io`. You will see a pending P1 ticket.
4. **Execute Runbook**: Click **Approve**. The backend executes the runbook, verifies the service recovery, and automatically marks the ticket as closed.

---

## 📂 Project Structure

```
synapseitsm/
├── src/synapse/
│   ├── agents/          # 🤖 Intake, RCA, Remediation, Monitoring agents
│   ├── api/             # 🚀 FastAPI routers (auth, chat, tickets, approvals, devices...)
│   │   ├── routers/devices.py     # 🖥️ Device CRUD, sync, /agent/result callback
│   │   └── job_result_store.py    # ⏳ Per-job asyncio.Event + HMAC job tokens
│   ├── db/             # 🗄️ SQLAlchemy models, Alembic migrations, seed data
│   ├── nodes/           # 🔗 LangGraph nodes (fast_path, deflect, hitl, verify...)
│   ├── rag/             # 🔍 ChromaDB ingest + retriever
│   ├── sim/             # 🎲 Anomaly simulator (generates monitoring alerts)
│   ├── tools/           # 🛠️ Agent tools (CMDB query, SLA, email, priority)
│   ├── mcp_servers/     # 📖 FastMCP runbook server + client
│   │   └── meshcentral_client.py  # 🖥️ Drives the meshctrl CLI (remote exec)
│   ├── exec_target.py   # 🎯 Resolves local vs. remote execution target
│   ├── graph.py         # 🕸️ LangGraph wiring — the full agent pipeline
│   ├── state.py         # 📦 AgentState (shared state across all nodes)
│   ├── llm.py           # 🔀 LiteLLM wrapper with per-agent model routing
│   └── config.py        # ⚙️ Settings loaded from .env
├── ui/
│   ├── chat_app.py      # 💬 Chainlit chat interface
│   ├── dashboard.py     # 📊 Streamlit ops dashboard
│   └── device_manager.py # 🖥️ Streamlit page: link users to remote devices
├── data/
│   ├── runbooks/        # 📋 YAML runbook definitions
│   └── chroma/          # 🗃️ ChromaDB vector store (generated by make ingest)
├── migrations/          # 🔄 Alembic migration scripts (0003 = device columns)
├── scripts/             # 🛠️ Helper scripts (test scenarios, monitoring reset)
│   ├── test_scenarios.py
│   └── reset_monitoring_tickets.py
├── docs/                # 📄 MeshCentral plan + executive brief
├── tests/               # 🧪 Pytest test suite
├── docker-compose.yml   # 🐳 PostgreSQL + (optional) MeshCentral service
├── meshcentral-config.json # 🖥️ MeshCentral server config
├── Makefile             # ⚡ Convenience commands
└── .env.example         # 🔐 Environment variable template
```

### Running Helper Scripts

* **Simulate All Trace Scenarios**: Executes the full agent pipeline offline to trace Fast Path, Full RCA, and Monitoring paths.
  ```bash
  python scripts/test_scenarios.py
  ```
* **Reset Active Simulator Tickets**: Closes all active auto-generated monitoring tickets to clear the dashboard for a clean demo.
  ```bash
  python scripts/reset_monitoring_tickets.py
  ```

---

## 🔧 LLM Configuration

By default, all agents route to `groq/llama-3.3-70b-versatile`. You can configure different models per-agent in your `.env` file:

```env
SUPERVISOR_MODEL=groq/llama-3.3-70b-versatile
INTAKE_MODEL=groq/llama-3.3-70b-versatile
RCA_MODEL=groq/llama-3.3-70b-versatile
REMEDIATION_MODEL=groq/llama-3.3-70b-versatile
```

Any provider supported by [LiteLLM](https://docs.litellm.ai/docs/providers) (e.g., `gemini/...`, `ollama/...`, `groq/...`) is fully supported.
