# SynapseITSM — Project Status & Team Log

> **How to use this file**
> Each team member has their own section under [Team Contributions](#team-contributions).
> When you finish a feature, fix a bug, or make any meaningful change — add a dated entry there.
> The [Feature Status](#feature-status) table is the shared source of truth for what is done.
> Update it whenever a feature changes state.

---

## Project Overview

**SynapseITSM** is a multi-agent IT Service Management system built as a graduation project (team of 5).
Users describe IT problems in plain language. A Supervisor orchestrates specialist agents that triage,
diagnose, remediate (with human approval), and learn from resolutions.

| Item | Value |
|------|-------|
| Stack | Python 3.11 · FastAPI · LangGraph · PostgreSQL · ChromaDB · LiteLLM |
| LLM providers | Groq (primary) · Ollama phi3:latest (fallback) |
| Chat UI | Chainlit — `http://localhost:8001` |
| Dashboard | Streamlit — `http://localhost:8501` |
| Backend API | FastAPI — `http://localhost:8000` |
| Runbook MCP | fastmcp stdio — `http://localhost:9001` |

---

## Feature Status

| # | Feature | Status | Owner | Notes |
|---|---------|--------|-------|-------|
| 1 | FastAPI backend skeleton | ✅ Done | | `src/synapse/api/` |
| 2 | PostgreSQL DB + Alembic migrations | ✅ Done | | `src/synapse/db/` |
| 3 | CMDB seed (25 CIs, relationships) | ✅ Done | | `src/synapse/db/seed.py` |
| 4 | LangGraph StateGraph + MemorySaver | ✅ Done | | `src/synapse/graph.py` |
| 5 | Supervisor agent | ✅ Done | | `src/synapse/agents/supervisor.py` |
| 6 | Intake agent | ✅ Done | | classify + priority + create ticket |
| 7 | RCA agent | ✅ Done | | CMDB + ChromaDB + SeqThinking MCP |
| 8 | Remediation agent | ✅ Done | | runbook selection + HITL |
| 9 | Monitoring agent | ✅ Done | | async loop, IsolationForest |
| 10 | Runbook MCP server (fastmcp) | ✅ Done | | 10 whitelisted runbooks |
| 11 | Sequential Thinking MCP | ✅ Done | | external `npx` process |
| 12 | ChromaDB RAG (fast-path + RCA) | ✅ Done | | `all-MiniLM-L6-v2`, threshold 0.75 |
| 13 | HITL gate (LangGraph interrupt) | ✅ Done | | pauses before hitl_node |
| 14 | HITL approval in **dashboard** (not chat) | ✅ Done | | Streamlit Approve/Reject buttons |
| 15 | Root cause + runbook visible in dashboard | ✅ Done | | pending_store.py + PendingApprovalOut |
| 16 | Chainlit notified after IT approves/rejects | ✅ Done | | notification_store + background poller |
| 17 | Monitoring deduplication | ✅ Done | | one open ticket per CI at a time |
| 18 | Monitoring auto-registers pending approvals | ✅ Done | | _register_pending() in monitoring.py |
| 19 | Monitoring Alerts section in dashboard | ✅ Done | | with Investigate button fallback |
| 20 | Email alerts via Resend API | ✅ Done | | free tier, config in .env |
| 21 | 13 monitoring scenarios | ✅ Done | | `sim/scenarios.yaml`, fires every ~60 s |
| 22 | Groq → phi3:latest fallback | ✅ Done | | llm.py + config.py |
| 23 | Network adapter UAC elevation fix | ✅ Done | | ctypes + temp .ps1 + RunAs |
| 24 | Domain routing fix (slow = diagnose_internet) | ✅ Done | | rca.py + remediation.py prompts |
| 25 | Intake follow-up classification fix | ✅ Done | | "apply this solution" → request |
| 26 | Chainlit chat UI | ✅ Done | | `ui/chat_app.py` |
| 27 | Streamlit dashboard | ✅ Done | | `ui/dashboard.py` |
| 28 | PowerPoint presentation (14 slides) | ✅ Done | | `make_pptx.py` → Desktop |
| 29 | PDF reference document (29 pages) | ✅ Done | | `make_pdf.py` → Desktop |
| 30 | Test scenarios script (3 traces) | ✅ Done | | `scripts/test_scenarios.py` |
| 31 | Reset monitoring tickets script | ✅ Done | | `scripts/reset_monitoring_tickets.py` |
| 32 | Langfuse tracing | ⬜ Optional | | keys in .env, leave blank to disable |
| 33 | Evaluation harness | ⬜ Optional | | `src/synapse/eval/harness.py` |
| 34 | **Auth (JWT login/register)** | ✅ Done | | `api/security.py`, `api/routers/auth.py` |
| 35 | **RBAC roles (end_user/it_team/admin)** | ✅ Done | | `require_role` in `api/deps.py` |
| 36 | **End users see only own tickets** | ✅ Done | | `owner_id` on tickets, role-aware `list_tickets` |
| 37 | **IT-only approve/reject/investigate** | ✅ Done | | guarded with `require_role("it_team","admin")` |
| 38 | **Dashboard login + role views** | ✅ Done | | `ui/dashboard.py` |
| 39 | **Chainlit password auth** | ✅ Done | | `ui/chat_app.py`, needs `CHAINLIT_AUTH_SECRET` |
| 40 | Remote PC remediation agent (polling) | ⬜ Phase 2 | | planned — agent on each PC pulls jobs |

---

## Architecture Quick-Reference

```
User
 │
 ▼
Chainlit (port 8001)
 │  POST /sessions/{id}/messages
 ▼
FastAPI Backend (port 8000)
 │
 ├── LangGraph StateGraph ──────────────────────────────────────────────┐
 │    │                                                                  │
 │    ├─ fast_path_node  (ChromaDB cosine ≥ 0.75 → deflect)            │
 │    ├─ intake_node     (classify + priority + ticket)                 │
 │    ├─ routing_node    (incident → RCA, request → answer)             │
 │    ├─ rca_node        (CMDB + ChromaDB + SeqThinking MCP)            │
 │    ├─ remediation_node (runbook selection)                           │
 │    ├─ hitl_node       (interrupt_before — pauses here)               │
 │    ├─ verify_node     (execute runbook via Runbook MCP)              │
 │    └─ close_ticket / escalate / report                               │
 │                                                                       │
 ├── Monitoring loop (background lifespan task) ────────────────────────┘
 │    anomaly → dedup check → ticket → email → graph → pending_store
 │
 ├── PostgreSQL  (tickets, action_logs, CMDB, reports)
 ├── ChromaDB    (incident KB, ./data/chroma)
 └── pending_store / notification_store  (in-process dicts)

Streamlit Dashboard (port 8501)
 ├── KPI metrics
 ├── Pending Approvals  ← IT approves/rejects here
 ├── Monitoring Alerts  ← with Investigate button
 └── All Tickets table
```

### Key Files

| File | Purpose |
|------|---------|
| `src/synapse/config.py` | All settings, reads from `.env` |
| `src/synapse/state.py` | AgentState Pydantic model (runtime contract) |
| `src/synapse/llm.py` | LiteLLM wrapper, Groq→phi3 fallback |
| `src/synapse/graph.py` | LangGraph StateGraph wiring |
| `src/synapse/api/pending_store.py` | In-process HITL approval store |
| `src/synapse/api/notification_store.py` | In-process chat notification store |
| `src/synapse/tools/email_alert.py` | Resend API email sender |
| `src/synapse/sim/scenarios.yaml` | 13 monitoring anomaly scenarios |
| `ui/chat_app.py` | Chainlit chat client |
| `ui/dashboard.py` | Streamlit ops dashboard |
| `scripts/reset_monitoring_tickets.py` | Utility: close all open [AUTO] tickets |

---

## How to Run

```bash
# 1 — Start PostgreSQL
docker compose up -d db

# 2 — Activate venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux

# 3 — Apply migrations + seed
alembic upgrade head
python -m synapse.db.seed

# 4 — Build ChromaDB knowledge base (run once)
python -m synapse.rag.ingest

# 5 — Start backend (graph + monitoring loop)
uvicorn synapse.api.main:app --reload --port 8000

# 6 — Start Chainlit chat (separate terminal)
chainlit run ui/chat_app.py --port 8001

# 7 — Start Streamlit dashboard (separate terminal)
streamlit run ui/dashboard.py --server.port 8501

# Reset monitoring tickets for a clean demo
python scripts/reset_monitoring_tickets.py
```

### Environment Variables (`.env`)

```
GROQ_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
SUPERVISOR_MODEL=groq/llama-3.3-70b-versatile
INTAKE_MODEL=groq/llama-3.3-70b-versatile
RCA_MODEL=groq/llama-3.3-70b-versatile
REMEDIATION_MODEL=groq/llama-3.3-70b-versatile

RESEND_API_KEY=...              # free at resend.com
ALERT_EMAIL_TO=...              # must match Resend account email (free tier)
ALERT_EMAIL_FROM=SynapseITSM <onboarding@resend.dev>
DASHBOARD_URL=http://localhost:8501

JWT_SECRET=...                  # long random string
JWT_EXPIRY_MINUTES=480
CHAINLIT_AUTH_SECRET=...        # any random string — required by Chainlit login
```

### Auth & RBAC

- **Login first.** Both the dashboard and the Chainlit chat now require login.
  After `python -m synapse.db.seed` you get four demo accounts:

  | Email | Password | Role | Sees |
  |-------|----------|------|------|
  | `admin@synapse.io` | `admin123` | admin | everything + user mgmt |
  | `it@synapse.io` | `it123456` | it_team | all tickets, approvals, monitoring |
  | `sara@synapse.io` | `sara123` | end_user | only their own tickets |
  | `omar@synapse.io` | `omar123` | end_user | only their own tickets |

- **How it works:** `POST /auth/login` returns a JWT. The UIs send it as
  `Authorization: Bearer <token>`. `get_current_user` decodes it; `require_role()`
  guards IT-only endpoints (`/actions/*`, `/tickets/*/investigate`).
- **Ticket ownership:** every chat-created ticket gets `owner_id = the logged-in user`.
  Monitoring `[AUTO]` tickets stay unowned so only IT sees them. End users get a
  `WHERE owner_id = me` filter on `GET /tickets`.
- **Migration:** run `alembic upgrade head` to create the `users` table and add
  `tickets.owner_id` (migration `0002_users_and_rbac`).

### Phase 2 (planned, not built) — Remediation on the user's own PC

Approach chosen: **polling agent** (simplest, works behind any firewall).
A small `synapse-agent` installed on each user PC polls the backend for jobs,
runs the existing runbook executors locally, and posts results back. Requires
two new tables (`devices`, `remediation_jobs`) and an `/agent/*` endpoint group.
See the in-repo plan / chat history for the full design.

---

## Known Limitations

- **pending_store / notification_store are in-process dicts** — they reset on backend restart.
  Pending approvals are lost if the server crashes. For production: persist to DB.
- **MemorySaver** (LangGraph checkpoint) is also in-memory — same issue.
- **Resend free tier** can only send to the email you registered with (no custom domain).
- **phi3:latest fallback** must be pulled first: `ollama pull phi3:latest`
- **Monitoring 15 s delay** between alerts (intentional — prevents Groq rate limiting).
  If you need faster, reduce `asyncio.sleep(15)` in `monitoring.py → drain_alerts`.

---

## Team Contributions

> **Instructions for team members:**
> Add your name as a heading below. Under it, log each piece of work with a date.
> Format: `- YYYY-MM-DD: [what you did]`
> Be specific — mention file names and what changed. This helps teammates understand the codebase.

---

### Member 1 — _(add your name)_

<!-- Example:
- 2026-06-20: Built the FastAPI backend skeleton (src/synapse/api/main.py, routers/)
- 2026-06-21: Implemented Intake agent and PostgreSQL ticket creation
-->

---

### Member 2 — _(add your name)_

---

### Member 3 — _(add your name)_

---

### Member 4 — _(add your name)_

---

### Member 5 — _(add your name)_

---

## Session Log (AI-assisted work)

Tracked work completed with Claude Code assistance — listed newest first.

- **2026-06-24**: Expanded monitoring scenarios from 4 → 13 (`sim/scenarios.yaml`). Added 15 s drain delay to prevent Groq rate limiting.
- **2026-06-24**: Switched email provider from SMTP to Resend API (`tools/email_alert.py`, `config.py`). Free tier, uses `httpx`.
- **2026-06-24**: Implemented 3-layer monitoring improvement:
  - Layer 1 — Deduplication: `find_open_monitoring_ticket` in `repositories.py`; skips creating duplicate tickets for the same CI.
  - Layer 2 — Auto-register: `_register_pending()` in `monitoring.py`; monitoring proposed solutions now appear in dashboard Pending Approvals automatically. Added `POST /tickets/{id}/investigate` endpoint and Investigate button in dashboard for fallback.
  - Layer 3 — Email alert: sends one email per new monitoring ticket via Resend.
- **2026-06-24**: Added Chainlit real-time notification when IT approves/rejects from dashboard (`notification_store.py`, `GET /sessions/{sid}/notification`, background polling task in `chat_app.py`).
- **2026-06-24**: Moved HITL Approve/Reject from Chainlit to Streamlit dashboard. Added `pending_store.py`, `PendingApprovalOut` schema, `GET /actions/pending` endpoint. Dashboard now shows Root Cause, Action Plan, and Runbook Parameters for each pending action.
- **2026-06-24**: Fixed 422 on approval endpoint — FastAPI path parameter renamed from `_action_id` back to `action_id`.
- **2026-06-24**: Changed Groq fallback model from `ollama/llama3.2` → `ollama/phi3:latest` in `config.py` and `llm.py`.
- **2026-06-23**: Fixed domain routing — "slow network" now correctly maps to `diagnose_internet` (not `reset_network_adapter`) in `rca.py` and `remediation.py`.
- **2026-06-23**: Fixed intake agent classification — follow-up confirmations ("apply this solution", "do it") now classified as `request` not `incident`.
- **2026-06-23**: Fixed `Disable-NetAdapter: Access is denied` — added UAC elevation via `ctypes.windll.shell32.IsUserAnAdmin()` + temp `.ps1` + `Start-Process -Verb RunAs` in `runbook_server.py`.
- **2026-06-23**: Created `make_pptx.py` (14-slide PowerPoint) and `make_pdf.py` (29-page reference PDF).
- **2026-06-23**: Created `test_scenarios.py` — 3 full trace scenarios (Fast Path, RCA, Monitoring).
