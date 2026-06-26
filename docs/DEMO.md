# SynapseITSM — Demo Walkthrough

## Prerequisites
- Docker Desktop running
- Python 3.11+
- Node.js (for Sequential Thinking MCP via npx)
- Optional: Ollama running locally (`ollama serve`)

---

## 1. One-command setup

```bash
# From synapseitsm/ directory
make demo-setup
```

Or manually:

```bash
# 1. Create virtualenv
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt
pip install -e .

# 3. Start Postgres
docker compose up -d db

# 4. Wait for DB to be ready (healthcheck)
docker compose ps

# 5. Copy env file and fill in keys
cp .env.example .env
# Edit .env: add GEMINI_API_KEY or GROQ_API_KEY, or leave blank for Ollama

# 6. Run Alembic migrations
alembic upgrade head

# 7. Seed the CMDB (25 CIs + relationships + historical tickets)
python -m synapse.db.seed

# 8. Ingest knowledge base into Chroma
python -m synapse.rag.ingest
```

---

## 2. Start the services

Open **4 terminals**:

**Terminal 1 — Backend (required)**
```bash
uvicorn synapse.api.main:app --reload --port 8000
```

**Terminal 2 — Chat UI (required)**
```bash
chainlit run ui/chat_app.py --port 8001
```

**Terminal 3 — Dashboard (optional)**
```bash
streamlit run ui/dashboard.py --server.port 8502
```

**Terminal 4 — Runbook MCP server (optional — starts automatically in-process)**
```bash
python -m synapse.mcp_servers.runbook_server
```

---

## 3. Demo Scenario 1 — Full Incident Flow

Open the Chainlit UI at http://localhost:8001

**Step 1: Report the incident**
> "Can't reach the sales dashboard, it's urgent"

Expected:
- Ticket created (P1, incident)
- Fast-path miss (new issue) → Intake → Routing → RCA
- RCA produces: "WEB-02 worker pool exhausted" hypothesis
- Remediation proposes: `restart_web_service` on WEB-02

**Step 2: Approve the action**
- Click **✅ Approve** button in the chat

Expected:
- Runbook executes against simulator
- Error rate on WEB-02 drops from 0.72 → 0.001
- `verify_recovery` confirms recovered
- Ticket closed, resolution written to Chroma

**Verify in dashboard** (http://localhost:8502):
- Ticket shows `closed` status
- MTTR metric updates

---

## 4. Demo Scenario 2 — Deflection (known repeat)

> "WEB-02 error rate is spiking, service is down"

Expected:
- Fast-path finds match in KB (score ≥ 0.82)
- Immediate answer returned
- Ticket created with `status=closed`, `category=deflected`

If the answer didn't help:
> "That didn't help, still broken"

Expected:
- `route_entry` detects negative feedback on closed ticket
- Escalates to Intake → full incident path

---

## 5. Demo Scenario 3 — Proactive Monitoring

With the backend running, at t+120s from startup:
- Simulator injects WEB-02 error_rate=0.72
- Monitoring loop detects anomaly
- Alert queue receives event
- `drain_alerts` auto-creates ticket (no chat open)
- Graph runs intake→rca→remediation→hitl (paused)

**Check the dashboard** — a new P1 ticket appears automatically.

**Approve via API** (since no chat session):
```bash
# Get the pending session_id from the dashboard or logs
curl -X POST http://localhost:8000/actions/restart_web_service/approve \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<mon_session_id>"}'
```

---

## 6. Demo Scenario 4 — Failure Path

```bash
# Force a verify failure by setting error rate high after "execution"
python -c "
from synapse.mcp_servers.runbook_server import set_metric
set_metric('error_rate', 'WEB-02', 0.95)
print('Metric injected')
"
```

Then report the incident and approve — the runbook will "execute" but verify will fail.

Expected:
- `report` node creates a `reports` row
- `notify_it` marks ticket `escalated`
- Dashboard shows escalated count += 1

---

## 7. Run Tests

```bash
pytest -v
```

All tests use in-memory SQLite + deterministic routing (no LLM calls).

---

## 8. Run Evaluation Harness

```bash
python -m synapse.eval.harness
```

Output example:
```
======================================================================
SynapseITSM Evaluation Harness — 10 cases
======================================================================
Running eval_001: Can't reach the sales dashboard, it's urgent...
  ✓ priority=True category=True rca=True rem=True latency=2.3s
...
RESULTS (10 cases)
======================================================================
  Priority accuracy : 85.0%
  Category accuracy : 90.0%
  RCA top-1 accuracy: 75.0%
  Remediation match : 80.0%
  Avg latency       : 3.1s
  Errors            : 0/10
======================================================================
```

---

## 9. API Reference

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions` | Create chat session |
| `POST` | `/sessions/{id}/messages` | Send message, get response |
| `GET`  | `/sessions/{id}/stream` | SSE stream of steps |
| `GET`  | `/tickets` | List tickets |
| `GET`  | `/tickets/{id}` | Get ticket |
| `POST` | `/cmdb/query` | Natural-language CMDB query |
| `GET`  | `/metrics` | KPI snapshot |
| `GET`  | `/alerts/stream` | SSE monitoring alerts |
| `POST` | `/actions/{id}/approve` | HITL approve → resume |
| `POST` | `/actions/{id}/reject` | HITL reject → escalate |
| `GET`  | `/healthz` | Health check |
