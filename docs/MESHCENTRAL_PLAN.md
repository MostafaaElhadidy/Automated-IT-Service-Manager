# Remote Remediation via MeshCentral — Implementation Plan

> **Goal:** Let the Remediation agent apply runbook fixes on the **end user's own
> PC/laptop**, not just on the backend server. We use **MeshCentral** (self-hosted
> RMM) as the transport: a small **MeshAgent** on each user device dials home over an
> outbound WebSocket, and SynapseITSM issues `runcommand` to a specific device by its
> `nodeid`.
>
> **Audience:** This file is written so it can be executed step-by-step by Claude
> Sonnet (or a teammate). Each phase lists concrete files to create/edit.

---

## Key decisions (locked)

1. **Result channel = script self-reports.** MeshCentral's `runcommand` does not
   reliably return stdout (upstream issues #2200, #5203, #6260). So every remediation
   command we send is wrapped to **POST structured JSON back to a new backend endpoint
   `POST /agent/result`**. We do NOT scrape runcommand output. Verify metrics are
   collected by a *second* remote command that also reports back.
2. **Per-user connection attributes live on the `users` table** (already added — see
   migration `0003_user_device_connection.py`). A user's primary device is reached via
   `users.meshcentral_nodeid`. (If multi-device support is needed later, promote these
   columns into a separate `devices` table — noted in "Future" below.)
3. **HITL stays.** IT still approves in the Streamlit dashboard before anything runs on
   a user PC. The runbook **whitelist in `runbook_server.py` is the main guardrail** now
   that commands hit real user machines — do not weaken it.
4. **Local execution still works.** Monitoring/server-side runbooks keep running locally.
   Remote execution only kicks in when the resolved target has a `meshcentral_nodeid`.

---

## Architecture: where this plugs in

Today the execution layer runs commands on the **backend host**:

- `nodes/verify.py` → `execute_and_verify()` in `mcp_servers/runbook_client.py`
  → executors in `mcp_servers/runbook_server.py`, all of which call local
  `subprocess.run(...)` (`_run_cmd`, `_execute_flush_dns`, `_execute_reset_network_adapter`, …).

We introduce an **execution target** abstraction so the *same* runbook command string
is either run locally (today) or shipped to a `nodeid` via MeshCentral.

```
ticket.owner_id ──► users.meshcentral_nodeid ──► RemoteMeshExecutor.run(nodeid, cmd)
                                                       │ (wraps cmd to POST results)
                                                       ▼
                                          MeshCentral server  ── wss ──►  MeshAgent on user PC
                                                       ▲                        │ runs cmd
                                                       └──── POST /agent/result ◄┘ self-report
```

---

## Phase A — Stand up MeshCentral (infra)

**A1.** Add a `meshcentral` service to `docker-compose.yml`:
- Image: `ghcr.io/ylianst/meshcentral:latest` (or pin a version).
- Volumes: `meshcentral-data:/opt/meshcentral/meshcentral-data` (+ its bundled DB, or
  point at the existing Postgres/Mongo).
- Ports: expose `443`/`8086` on a host reachable by user devices (LAN IP or domain).
- Set `--cert <hostname>` so the agent installer embeds the right server URL.

**A2.** First-run config: create an automation user `synapse-bot` and a **login token key**:
```bash
node meshcentral --logintokenkey      # prints a key; store it
```
Add to `.env` (and `config.py` Settings):
```
MESHCENTRAL_URL=wss://<host>:443/control.ashx
MESHCENTRAL_USER=synapse-bot
MESHCENTRAL_LOGINKEY=<login token key>
MESHCENTRAL_DEVICE_GROUP=SynapseITSM-Endpoints
MESHCENTRAL_VERIFY_TLS=true        # false only for self-signed dev certs
```

**A3.** In the MeshCentral web UI create device group **`SynapseITSM-Endpoints`** and
note its agent-install link.

**Files:** `docker-compose.yml`, `.env.example`, `src/synapse/config.py`.

---

## Phase B — User device connection attributes (DONE)

Already implemented:
- `src/synapse/db/models.py` → `User` now has `meshcentral_nodeid`, `device_hostname`,
  `last_known_ip`, `os_platform`, `agent_online`, `device_last_seen`.
- `migrations/versions/0003_user_device_connection.py`.

**Remaining B-step:** run `alembic upgrade head` after Postgres is up.

Add repo helpers in `src/synapse/db/repositories.py`:
- `get_user(session, user_id)` (if not present).
- `get_user_by_nodeid(session, nodeid)`.
- `update_user_device(session, user_id, *, nodeid, hostname, ip, os_platform, online, last_seen)`.
- `find_user_by_hostname_or_email(session, name)` — used by sync to map a node to a user.

---

## Phase C — MeshCentral client

Create `src/synapse/mcp_servers/meshcentral_client.py`:

- **Auth:** open a WebSocket to `MESHCENTRAL_URL` using the login token key
  (`x-meshauth` / login key header). Reuse one connection where practical.
- `async def list_nodes() -> list[dict]` — send `{"action":"nodes"}`, return nodes in
  `MESHCENTRAL_DEVICE_GROUP` with `nodeid, name, host, osdesc, conn (online bitmask)`.
- `async def run_remote(nodeid, command, shell="powershell", timeout=120) -> str` —
  send `{"action":"runcommands","nodeids":[nodeid],"type":<2=ps,1=cmd,0=bash>,"cmds":command}`.
  Returns the MeshCentral ack (NOT the command output — output comes via `/agent/result`).
- `async def sync_devices()` — call `list_nodes()`, map each node to a SynapseITSM user
  (by device name == user email, or hostname), and `update_user_device(...)`. Run this
  on a timer and on demand from the dashboard.

**Mapping rule (default):** name each device the user's **email** at enrollment time so
`sync_devices()` can map `node.name → users.email`. Fallback: hostname match.

---

## Phase D — Route runbooks to the right machine

**D1. Target resolver** — new helper (e.g. in `runbook_client.py` or a small
`mcp_servers/exec_target.py`):
```python
async def resolve_target(ticket_id) -> ExecTarget:
    # ticket.owner_id -> user -> meshcentral_nodeid
    # returns RemoteTarget(nodeid, os) if online, else LocalTarget()
```
`monitoring_system` tickets and unowned `[AUTO]` tickets always resolve to LocalTarget.

**D2. Execution-target abstraction** in `runbook_server.py`:
- Refactor executors so the command string is produced separately from *where* it runs.
- `LocalExecutor.run(cmd)` = current `_run_cmd`.
- `RemoteMeshExecutor.run(cmd)` = `meshcentral_client.run_remote(nodeid, wrapped_cmd)`.
- The network runbooks (`flush_dns`, `reset_network_adapter`, `reconnect_vpn`,
  `reset_network_stack`, `diagnose_internet`) are the ones that make sense to run on the
  user PC — make sure their command strings are portable to remote PowerShell.

**D3. Thread the target through:**
- `nodes/verify.py` resolves the target from `state.active_ticket_id` and passes it to
  `execute_and_verify(runbook_id, parameters, target=...)`.
- `runbook_client.execute_and_verify(...)` forwards `target` to execute + verify.

---

## Phase E — Reliable results & remote verify (the output caveat)

**E1. Callback endpoint** — new `src/synapse/api/routers/agent.py`:
- `POST /agent/result` body: `{job_id, nodeid, runbook_id, step, ok, output, ts}`.
- Auth with a per-job shared secret (HMAC token embedded in the wrapped command) so a
  random host can't spoof results.
- Store results in an in-process `job_result_store` (mirror `pending_store.py`) keyed by
  `job_id`; also append to `action_log`.
- Register the router in `src/synapse/api/main.py`.

**E2. Command wrapper** — when `RemoteMeshExecutor` sends a command, wrap it so the
remote script runs the real command, captures `$LASTEXITCODE`/stdout, then
`Invoke-RestMethod -Method Post -Uri <BACKEND>/agent/result -Body (json…)`. Provide a
small PowerShell template and a bash template.

**E3. Remote verify** — instead of `_collect_metric` running on the server, ship the
metric probe (e.g. DNS resolve / TCP latency) as a second wrapped command to the same
`nodeid`. `verify_recovery` then reads the reported value from `job_result_store`.
Keep a server-side fallback when the device is a server/CI (LocalTarget).

**E4. Await pattern** — `execute_and_verify` issues the remote command, then awaits the
`/agent/result` callback for `job_id` (with timeout) before returning `recovered`.
A simple `asyncio.Event` per job in `job_result_store` works.

---

## Phase F — Safety, UI, docs

**F1.** Keep HITL interrupt before `hitl` node (no change to `graph.py`). The approval
card should now also show **which device** the fix will run on (hostname + user).

**F2.** `ui/dashboard.py` — add a **Devices** panel: list users with
`meshcentral_nodeid`, online/offline (`agent_online`), `device_last_seen`, OS; a
"Sync devices" button (calls a new `POST /devices/sync`) and a manual
"Run runbook on this device" action (IT-only).

**F3.** Logging/audit: every remote run records `nodeid`, wrapped command, and the
reported output into `action_log`. Never log the per-job HMAC secret.

**F4.** Docs: flip Feature `#40` in `PROJECT_STATUS.md` to ✅ and add a session-log
entry; update `README.md` architecture section; add a short "Enroll a device" section
(below) to onboarding docs.

---

## How to enroll a user device and link it to SynapseITSM

**Enroll (per PC/laptop, one-time):**
1. MeshCentral UI → device group **SynapseITSM-Endpoints** → **Add Agent**.
2. Pick OS, copy the installer / one-line install command.
3. Run it on the user's PC (admin once). MeshAgent installs as a service, dials out, and
   appears in the group with a unique **`nodeid`**.
4. **Name the device the user's email** (e.g. `sara@synapse.io`) so mapping is automatic.
   For fleets, push via GPO/Intune.

**Link to SynapseITSM:**
5. Run `meshcentral_client.sync_devices()` (timer or dashboard "Sync devices").
6. It maps each node (by name==email, fallback hostname) and writes
   `meshcentral_nodeid`, `device_hostname`, `last_known_ip`, `os_platform`,
   `agent_online`, `device_last_seen` onto the matching `users` row.
7. Chain is complete: ticket `owner_id` → `users.meshcentral_nodeid` → remote `runcommand`.

**End-to-end:** Sara reports "internet slow" → RCA+Remediation pick `flush_dns` → IT
approves (card shows it targets Sara's laptop) → backend resolves her `nodeid` → MeshCentral
runs `ipconfig /flushdns` **on her laptop** → wrapped script POSTs success to `/agent/result`
→ remote verify re-checks DNS on her laptop → ticket closes.

---

## Build order checklist (for execution)

- [ ] **B** (finish): `alembic upgrade head`; add `repositories.py` user-device helpers.
- [ ] **A**: docker-compose meshcentral service; `config.py` settings; `.env.example`.
- [ ] **C**: `meshcentral_client.py` (login, list_nodes, run_remote, sync_devices).
- [ ] **E1**: `routers/agent.py` + `job_result_store.py`; register in `main.py`.
- [ ] **D**: target resolver + LocalExecutor/RemoteMeshExecutor in `runbook_server.py`;
      thread `target` through `runbook_client.py` and `nodes/verify.py`.
- [ ] **E2/E3/E4**: command wrappers, remote verify, await-callback.
- [ ] **F**: dashboard Devices panel + `POST /devices/sync`; approval card shows target;
      audit logging; docs.
- [ ] Test: enroll one Windows laptop, run `flush_dns` end-to-end through the dashboard.

---

## Future (not in this pass)

- Multi-device per user → promote the `users.meshcentral_*` columns into a `devices`
  table (1 user → N devices), pick target by ticket/affected_ci.
- Reuse MeshCentral remote desktop / file transfer for the escalate-to-IT path.
- Persist `job_result_store` / `pending_store` to DB (today they're in-process dicts and
  reset on backend restart — see Known Limitations in PROJECT_STATUS.md).
