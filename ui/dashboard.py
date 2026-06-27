"""Streamlit dashboard — thin client over the SynapseITSM backend API.

Auth-aware: requires login. End users see only their own tickets;
IT team / admin see all tickets, pending approvals, and monitoring alerts.
Does NOT import agents or touch the DB directly.
"""
from __future__ import annotations
import os
import time
import httpx
import streamlit as st
import pandas as pd

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
PRIORITY_ICON = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🟢", "P5": "⚪"}

st.set_page_config(page_title="SynapseITSM Dashboard", layout="wide")


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def do_login(email: str, password: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{API_BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "Invalid email or password"
        resp.raise_for_status()
        data = resp.json()
        st.session_state["token"] = data["access_token"]
        st.session_state["user"] = data["user"]
        return True, ""
    except Exception as exc:
        return False, str(exc)


def logout() -> None:
    st.session_state.pop("token", None)
    st.session_state.pop("user", None)


# ── Data fetchers (all send the bearer token) ────────────────────────────────

def fetch_metrics() -> dict:
    try:
        resp = httpx.get(f"{API_BASE}/metrics", headers=_auth_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def fetch_tickets(status: str | None = None, priority: str | None = None) -> list[dict]:
    try:
        params = {}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        resp = httpx.get(f"{API_BASE}/tickets", params=params, headers=_auth_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def fetch_pending_approvals() -> list[dict]:
    try:
        resp = httpx.get(f"{API_BASE}/actions/pending", headers=_auth_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def post_approve(session_id: str, action_id: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{API_BASE}/actions/{action_id}/approve",
            json={"session_id": session_id},
            headers=_auth_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def post_reject(session_id: str, action_id: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{API_BASE}/actions/{action_id}/reject",
            json={"session_id": session_id},
            headers=_auth_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def fetch_user_devices(q: str = "") -> list[dict]:
    try:
        url = f"{API_BASE}/devices/users"
        params = {}
        if q:
            url = f"{API_BASE}/devices/users/search"
            params["q"] = q
        resp = httpx.get(url, params=params, headers=_auth_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def update_user_device(user_id: str, payload: dict) -> tuple[bool, str]:
    try:
        resp = httpx.put(
            f"{API_BASE}/devices/users/{user_id}",
            json=payload,
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def unlink_user_device(user_id: str) -> tuple[bool, str]:
    try:
        resp = httpx.delete(
            f"{API_BASE}/devices/users/{user_id}/device",
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def sync_devices() -> tuple[bool, dict]:
    try:
        resp = httpx.post(
            f"{API_BASE}/devices/sync",
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return True, resp.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def post_investigate(ticket_id: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{API_BASE}/tickets/{ticket_id}/investigate",
            headers=_auth_headers(),
            timeout=90,
        )
        resp.raise_for_status()
        return True, resp.json().get("status", "ok")
    except Exception as exc:
        return False, str(exc)


# ── Login gate ───────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.title("🧠 SynapseITSM — Sign In")
    st.caption("Log in to access the operations dashboard.")

    with st.form("login_form"):
        email = st.text_input("Email", placeholder="it@synapse.io")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
        if submitted:
            ok, err = do_login(email, password)
            if ok:
                st.rerun()
            else:
                st.error(err)

    with st.expander("Demo accounts"):
        st.markdown(
            "- **IT team:** `it@synapse.io` / `it123456`\n"
            "- **Admin:** `admin@synapse.io` / `admin123`\n"
            "- **End user:** `sara@synapse.io` / `sara123`"
        )
    st.stop()


# ── Authenticated ────────────────────────────────────────────────────────────

user = st.session_state["user"]
role = user["role"]
is_it = role in ("it_team", "admin")

st.title("🧠 SynapseITSM — Operations Dashboard")

with st.sidebar:
    st.markdown(f"**{user['full_name']}**")
    st.caption(f"{user['email']} · `{role}`")
    if st.button("Log out", use_container_width=True):
        logout()
        st.rerun()
    st.write("---")
    refresh_interval = st.slider("Auto-refresh (seconds)", 5, 60, 15)
    st.write("---")


# ─────────────────────────────────────────────────────────────────────────────
# END-USER VIEW — only their own tickets
# ─────────────────────────────────────────────────────────────────────────────
if not is_it:
    st.subheader("My Tickets")
    st.caption("Tickets you have opened. An IT specialist reviews and approves any fixes.")

    my_tickets = fetch_tickets()
    if my_tickets:
        df = pd.DataFrame(my_tickets)
        df["P"] = df["priority"].map(lambda p: PRIORITY_ICON.get(p, "") + " " + p)
        cols = [c for c in ["id", "P", "category", "status", "summary"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
    else:
        st.info("You have no tickets yet. Open one from the chat assistant.")

    st.caption(f"Last refreshed: {time.strftime('%H:%M:%S')}")
    time.sleep(refresh_interval)
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# IT / ADMIN VIEW — full operations dashboard
# ─────────────────────────────────────────────────────────────────────────────

# ── KPI row ──
metrics = fetch_metrics()
if "error" in metrics:
    st.error(f"Backend unreachable: {metrics['error']}")
else:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Tickets", metrics.get("total_tickets", 0))
    c2.metric("Open Tickets", metrics.get("open_tickets", 0))
    c3.metric("Deflection Rate", f"{metrics.get('deflection_rate', 0.0):.1%}")
    c4.metric("MTTR (min)", f"{metrics.get('mttr_minutes', 0.0):.1f}")
    c5.metric("Escalated", metrics.get("escalated", 0))

st.divider()

# ── Pending Approvals ──
pending = fetch_pending_approvals()
pending_ticket_ids = {p["ticket_id"] for p in pending}

st.subheader(f"Pending Approvals ({len(pending)})")
if not pending:
    st.info("No actions awaiting approval.")
else:
    for item in pending:
        priority = item.get("ticket_priority", "P3")
        icon = PRIORITY_ICON.get(priority, "")
        sid = item["session_id"]
        aid = item["action_id"]
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(
                    f"**{icon} {priority}  ·  Ticket:** `{item.get('ticket_id', 'N/A')}`  "
                    f"**·  Runbook:** `{item.get('runbook_id', '')}`"
                )
                st.markdown(f"**Summary:** {item.get('ticket_summary', '—')}")
                st.markdown(f"**Root Cause:** {item.get('root_cause', '—')}")
                # ── Remote target badge ──
                target_label = item.get("target_label", "local")
                target_online = item.get("target_online", False)
                if target_label and target_label != "local":
                    dot = "🟢" if target_online else "🔴"
                    st.markdown(f"**Target device:** {dot} `{target_label}`")
                else:
                    st.markdown("**Target:** `local server`")
                plan = item.get("plan", "").strip()
                if plan:
                    with st.expander("Action Plan / Steps"):
                        st.text(plan)
                params = item.get("parameters", {})
                if params:
                    with st.expander("Runbook Parameters"):
                        st.json(params)
            with right:
                st.write("")
                if st.button("Approve", key=f"approve_{sid}", type="primary", use_container_width=True):
                    ok, err = post_approve(sid, aid)
                    if ok:
                        st.success("Approved — runbook executing.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Failed: {err}")
                if st.button("Reject", key=f"reject_{sid}", use_container_width=True):
                    ok, err = post_reject(sid, aid)
                    if ok:
                        st.warning("Rejected — ticket escalated to IT team.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Failed: {err}")

st.divider()

# ── Monitoring Alerts ──
all_tickets = fetch_tickets()
monitoring_alerts = [
    t for t in all_tickets
    if t.get("summary", "").startswith("[AUTO]")
    and t.get("status") in ("new", "assigned", "in_progress")
]

st.subheader(f"Monitoring Alerts ({len(monitoring_alerts)})")
if not monitoring_alerts:
    st.info("No active monitoring alerts.")
else:
    for t in monitoring_alerts:
        priority = t.get("priority", "P3")
        icon = PRIORITY_ICON.get(priority, "")
        tid = t.get("id", "")
        already_pending = tid in pending_ticket_ids
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(f"**{icon} {priority}  ·  `{tid}`**  ·  CI: `{t.get('affected_ci', '—')}`")
                st.caption(t.get("summary", ""))
            with right:
                if already_pending:
                    st.info("Awaiting approval")
                elif st.button("Investigate", key=f"inv_{tid}", use_container_width=True):
                    with st.spinner("Running RCA + Remediation…"):
                        ok, status = post_investigate(tid)
                    if ok and status == "pending_approval":
                        st.success("Proposed fix ready — see Pending Approvals above.")
                        time.sleep(1)
                        st.rerun()
                    elif ok and status == "no_action_proposed":
                        st.warning("Investigation complete but no runbook could be proposed.")
                    else:
                        st.error(f"Investigation failed: {status}")

st.divider()

# ── All tickets table ──
st.subheader("All Tickets")
col_f1, col_f2 = st.columns(2)
with col_f1:
    status_filter = st.selectbox(
        "Status",
        ["All", "new", "assigned", "in_progress", "resolved", "closed", "escalated"],
    )
with col_f2:
    priority_filter = st.selectbox("Priority", ["All", "P1", "P2", "P3", "P4", "P5"])

tickets = fetch_tickets(
    status=None if status_filter == "All" else status_filter,
    priority=None if priority_filter == "All" else priority_filter,
)
if tickets:
    df = pd.DataFrame(tickets)
    df["P"] = df["priority"].map(lambda p: PRIORITY_ICON.get(p, "") + " " + p)
    cols = [c for c in ["id", "P", "category", "status", "affected_ci", "summary"] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
else:
    st.info("No tickets found.")

st.divider()

# ── Devices panel (IT/admin only) ──
st.subheader("Endpoint Devices")
st.caption("Devices enrolled in MeshCentral and linked to SynapseITSM users.")

dev_col1, dev_col2 = st.columns([3, 1])
with dev_col1:
    dev_search = st.text_input("Search by email / name / user ID", key="dev_search", label_visibility="collapsed", placeholder="Search by email / name / user ID")
with dev_col2:
    if st.button("Sync from MeshCentral", use_container_width=True):
        with st.spinner("Syncing devices from MeshCentral…"):
            ok, result = sync_devices()
        if ok:
            st.success(f"Synced: {result.get('synced',0)} linked · {result.get('unmatched',0)} unmatched · {result.get('errors',0)} errors")
        else:
            st.error(f"Sync failed: {result.get('error','unknown error')}")

devices_list = fetch_user_devices(dev_search)
if devices_list:
    for dev in devices_list:
        online = dev.get("agent_online", False)
        nodeid = dev.get("meshcentral_nodeid") or "—"
        hostname = dev.get("device_hostname") or "—"
        ip = dev.get("last_known_ip") or "—"
        os_p = dev.get("os_platform") or "—"
        last_seen = dev.get("device_last_seen") or "—"
        dot = "🟢" if online else ("🔴" if nodeid != "—" else "⚫")
        with st.container(border=True):
            dl, dr = st.columns([5, 1])
            with dl:
                st.markdown(
                    f"{dot} **{dev['full_name']}** &nbsp; `{dev['email']}` &nbsp; `{dev['role']}`"
                )
                if nodeid != "—":
                    st.caption(
                        f"nodeid: `{nodeid}` &nbsp;|&nbsp; hostname: `{hostname}` "
                        f"&nbsp;|&nbsp; IP: `{ip}` &nbsp;|&nbsp; OS: `{os_p}` "
                        f"&nbsp;|&nbsp; last seen: `{last_seen}`"
                    )
                else:
                    st.caption("No device enrolled yet.")
            with dr:
                if st.button("Edit", key=f"edit_dev_{dev['id']}", use_container_width=True):
                    st.session_state[f"editing_dev_{dev['id']}"] = True

        # Inline edit form (shown when Edit clicked)
        if st.session_state.get(f"editing_dev_{dev['id']}", False):
            with st.form(key=f"form_dev_{dev['id']}"):
                st.markdown(f"**Update device for {dev['full_name']}**")
                new_nodeid   = st.text_input("MeshCentral Node ID", value=dev.get("meshcentral_nodeid") or "")
                new_hostname = st.text_input("Hostname", value=dev.get("device_hostname") or "")
                new_ip       = st.text_input("Last Known IP", value=dev.get("last_known_ip") or "")
                new_os       = st.selectbox("OS Platform", ["windows", "linux", "darwin"],
                                            index=["windows", "linux", "darwin"].index(dev.get("os_platform") or "windows"))
                new_online   = st.checkbox("Agent Online", value=dev.get("agent_online", False))
                col_save, col_unlink, col_cancel = st.columns(3)
                save   = col_save.form_submit_button("Save", type="primary", use_container_width=True)
                unlink = col_unlink.form_submit_button("Unlink Device", use_container_width=True)
                cancel = col_cancel.form_submit_button("Cancel", use_container_width=True)

            if save:
                payload = {
                    "meshcentral_nodeid": new_nodeid or None,
                    "device_hostname": new_hostname or None,
                    "last_known_ip": new_ip or None,
                    "os_platform": new_os,
                    "agent_online": new_online,
                }
                ok, err = update_user_device(dev["id"], payload)
                if ok:
                    st.success("Device attributes saved.")
                    st.session_state[f"editing_dev_{dev['id']}"] = False
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"Save failed: {err}")
            elif unlink:
                ok, err = unlink_user_device(dev["id"])
                if ok:
                    st.warning("Device unlinked.")
                    st.session_state[f"editing_dev_{dev['id']}"] = False
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"Unlink failed: {err}")
            elif cancel:
                st.session_state[f"editing_dev_{dev['id']}"] = False
                st.rerun()
else:
    st.info("No users found. Use the search box above or enroll devices in MeshCentral and click Sync.")

st.divider()

# ── Charts ──
if all_tickets:
    df_all = pd.DataFrame(all_tickets)
    st.subheader("Ticket Distribution")
    col_a, col_b = st.columns(2)
    with col_a:
        if "priority" in df_all.columns:
            st.bar_chart(df_all["priority"].value_counts())
            st.caption("By Priority")
    with col_b:
        if "status" in df_all.columns:
            st.bar_chart(df_all["status"].value_counts())
            st.caption("By Status")

st.caption(
    f"Last refreshed: {time.strftime('%H:%M:%S')} — Auto-refreshes every {refresh_interval}s"
)
time.sleep(refresh_interval)
st.rerun()
