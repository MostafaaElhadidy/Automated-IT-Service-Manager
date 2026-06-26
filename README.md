# SynapseITSM

An AI-powered IT Service Management system where users describe IT problems in plain language and a multi-agent system triages, diagnoses, and fixes them — with human approval before any action is taken.

Built as a graduation project using **LangGraph**, **FastAPI**, **Chainlit**, and **Streamlit**.

---

## How It Works

```
User message
     │
     ▼
 Fast-path ──(high confidence)──► Deflect (KB answer)
     │
  (low confidence)
     │
     ▼
  Intake Agent         classifies: incident / request
     │
     ▼
  Routing Node
     ├── request ──► LLM answer ──► END
     └── incident
           │
           ▼
       RCA Agent          root cause analysis + CMDB query
           │
           ▼
    Remediation Agent     selects runbook
           │
           ▼
      HITL (pause)        IT team approves/rejects in dashboard
           │
     ┌─────┴─────┐
  approved     rejected
     │              │
     ▼              ▼
  Runbook       Escalate
  Execute
     │
  ┌──┴───┐
 pass   fail
  │       │
Close   Report ──► Notify IT ──► Email alert
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph |
| LLM routing | LiteLLM (Groq / Gemini / Ollama) |
| Backend API | FastAPI + Uvicorn |
| Chat UI | Chainlit |
| Operations dashboard | Streamlit |
| Database | PostgreSQL (via Docker) |
| Migrations | Alembic |
| Vector store (RAG) | ChromaDB |
| Runbook server | FastMCP |
| Email alerts | Resend |

---

## Prerequisites

- Python 3.11+
- Docker Desktop (for PostgreSQL)
- A free [Groq API key](https://console.groq.com) — used for all LLM calls

---

## Quick Start

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

Open `.env` and fill in at minimum:

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
.venv\Scripts\python -m alembic upgrade head   # Windows
# or
.venv/bin/python -m alembic upgrade head       # Mac/Linux

# Seed demo data (users, CMDB, historical tickets)
python -m synapse.db.seed

# Ingest knowledge base into ChromaDB
python -m synapse.rag.ingest
```

### 4. Run the application (3 terminals)

**Terminal 1 — Backend API**
```bash
python -m uvicorn synapse.api.main:app --reload --port 8000
```

**Terminal 2 — Chat UI**
```bash
chainlit run ui/chat_app.py --port 8001
```

**Terminal 3 — Operations Dashboard**
```bash
streamlit run ui/dashboard.py --server.port 8502
```

| Component | URL |
|---|---|
| Chat (end users) | http://localhost:8001 |
| Dashboard (IT team) | http://localhost:8502 |
| API docs | http://localhost:8000/docs |

---

## Demo Accounts

| Email | Password | Role |
|---|---|---|
| admin@synapse.io | admin123 | Admin |
| it@synapse.io | it123456 | IT Team |
| sara@synapse.io | sara123 | End User |
| omar@synapse.io | omar123 | End User |

Log into the **Chat UI** as `sara@synapse.io` to submit incidents.
Log into the **Dashboard** as `it@synapse.io` to approve/reject runbooks.

---

## Try It Out

1. Open http://localhost:8001, log in as `sara@synapse.io`
2. Type: **"The sales dashboard is down, users can't access it"**
3. The agent will triage, run root cause analysis, and propose a runbook
4. Open http://localhost:8502, log in as `it@synapse.io`
5. Approve the pending action — the runbook executes and the ticket closes

If you type something the system has seen before (e.g. "database connection errors"), it will suggest a known fix from the knowledge base instantly.

To escalate a deflected answer: reply **"that didn't help"** and it will run the full diagnostic pipeline.

---

## Project Structure

```
synapseitsm/
├── src/synapse/
│   ├── agents/          # Intake, RCA, Remediation, Monitoring agents
│   ├── api/             # FastAPI routers (auth, chat, tickets, approvals...)
│   ├── db/              # SQLAlchemy models, Alembic migrations, seed data
│   ├── nodes/           # LangGraph nodes (fast_path, deflect, hitl, verify...)
│   ├── rag/             # ChromaDB ingest + retriever
│   ├── sim/             # Anomaly simulator (generates monitoring alerts)
│   ├── tools/           # Agent tools (CMDB query, SLA, email, priority)
│   ├── mcp_servers/     # FastMCP runbook server + client
│   ├── graph.py         # LangGraph wiring — the full agent pipeline
│   ├── state.py         # AgentState (shared state across all nodes)
│   ├── llm.py           # LiteLLM wrapper with per-agent model routing
│   └── config.py        # Settings loaded from .env
├── ui/
│   ├── chat_app.py      # Chainlit chat interface
│   └── dashboard.py     # Streamlit ops dashboard
├── data/
│   ├── runbooks/        # YAML runbook definitions
│   └── chroma/          # ChromaDB vector store (generated by make ingest)
├── migrations/          # Alembic migration scripts
├── tests/               # Pytest test suite
├── docker-compose.yml   # PostgreSQL service
├── Makefile             # Convenience commands
└── .env.example         # Environment variable template
```

---

## Makefile Commands

```bash
make setup        # Create venv and install dependencies
make db-up        # Start PostgreSQL in Docker
make migrate      # Run Alembic migrations
make seed         # Seed demo data
make ingest       # Ingest knowledge base into ChromaDB
make backend      # Start FastAPI backend (port 8000)
make chat         # Start Chainlit chat UI (port 8001)
make dashboard    # Start Streamlit dashboard (port 8502)
make test         # Run pytest
make demo-setup   # Full first-time setup in one command
```

---

## LLM Configuration

By default, all agents use `groq/llama-3.3-70b-versatile`. You can override per-agent in `.env`:

```env
SUPERVISOR_MODEL=groq/llama-3.3-70b-versatile
INTAKE_MODEL=groq/llama-3.3-70b-versatile
RCA_MODEL=groq/llama-3.3-70b-versatile
REMEDIATION_MODEL=groq/llama-3.3-70b-versatile
```

Supported providers: `groq/...`, `gemini/...`, `ollama/...` (any model supported by LiteLLM).
