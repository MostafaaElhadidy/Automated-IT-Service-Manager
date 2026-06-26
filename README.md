# 🧠 SynapseITSM

An AI-powered IT Service Management (ITSM) system where users describe IT problems in plain language, and a multi-agent system triages, diagnoses, and remediates them. It integrates a Human-in-the-Loop (HITL) workflow, ensuring all remediation actions require explicit operator approval before execution.

Built as a graduation project demonstration utilizing **LangGraph**, **FastAPI**, **Chainlit**, and **Streamlit**.

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
4. **Remediation Agent (Llama 3.3 70B)**: Reviews the RCA findings and matches them against the available runbooks. It prepares a step-by-step execution plan and constructs the exact parameters needed for the runbook tool.
5. **Human-in-the-Loop (HITL) Node**: Pauses the LangGraph execution state when a runbook action is proposed. The state remains suspended until an operator approves or rejects the action via the Streamlit dashboard.
6. **Monitoring / Alerting Agent**: A background task that polls system metrics. If an anomaly is detected, it automatically generates a P1 incident ticket and triggers the graph workflow.

---

## 📊 Database Architecture

The project splits its data requirements between a relational database for operational consistency and a vector database for semantic retrieval.

### 1. PostgreSQL (Relational & Operational DB)
PostgreSQL handles the structured relational data. The schema is managed via SQLAlchemy in `src/synapse/db/models.py`:
* **Configuration Items (`configuration_items`)**: The CMDB containing 34 seeded infrastructure assets (e.g., `POS-01` terminal, `DB-01` PostgreSQL primary database, `REDIS-03` cache).
* **CI Relationships (`ci_relationships`)**: The topology dependency graph mapping links (e.g., `POS-01` depends on `LB-02`, which depends on `APP-03`).
* **Tickets (`tickets`)**: Active and historical tickets containing category, priority, status, and summary.
* **Action Logs (`action_log`)**: Sequential records of runbook proposals, approvals, executions, or failures.
* **Users (`users`)**: Relational records for identity, roles (`admin`, `it_team`, `end_user`), and password hashes.

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

---

## ✅ Prerequisites

- Python 3.11+
- Docker Desktop (for PostgreSQL)
- A free [Groq API key](https://console.groq.com)

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
python -m uvicorn synapse.api.main:app --reload --port 8000
```

**Terminal 2 — Chat UI (Chainlit Client)**
```bash
chainlit run ui/chat_app.py --port 8001
```

**Terminal 3 — Operations Dashboard (Streamlit UI)**
```bash
streamlit run ui/dashboard.py --server.port 8502
```

| Component | URL |
|---|---|
| 💬 Chat UI (end users) | http://localhost:8001 |
| 📊 Ops Dashboard (IT team) | http://localhost:8502 |
| 📄 API Swagger Docs | http://localhost:8000/docs |

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
│   ├── api/             # 🚀 FastAPI routers (auth, chat, tickets, approvals...)
│   ├── db/              # 🗄️ SQLAlchemy models, Alembic migrations, seed data
│   ├── nodes/           # 🔗 LangGraph nodes (fast_path, deflect, hitl, verify...)
│   ├── rag/             # 🔍 ChromaDB ingest + retriever
│   ├── sim/             # 🎲 Anomaly simulator (generates monitoring alerts)
│   ├── tools/           # 🛠️ Agent tools (CMDB query, SLA, email, priority)
│   ├── mcp_servers/     # 📖 FastMCP runbook server + client
│   ├── graph.py         # 🕸️ LangGraph wiring — the full agent pipeline
│   ├── state.py         # 📦 AgentState (shared state across all nodes)
│   ├── llm.py           # 🔀 LiteLLM wrapper with per-agent model routing
│   └── config.py        # ⚙️ Settings loaded from .env
├── ui/
│   ├── chat_app.py      # 💬 Chainlit chat interface
│   └── dashboard.py     # 📊 Streamlit ops dashboard
├── data/
│   ├── runbooks/        # 📋 YAML runbook definitions
│   └── chroma/          # 🗃️ ChromaDB vector store (generated by make ingest)
├── migrations/          # 🔄 Alembic migration scripts
├── scripts/             # 🛠️ Helper scripts (test scenarios, monitoring reset)
│   ├── test_scenarios.py
│   └── reset_monitoring_tickets.py
├── tests/               # 🧪 Pytest test suite
├── docker-compose.yml   # 🐳 PostgreSQL service
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
