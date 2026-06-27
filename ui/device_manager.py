"""Device Manager — Streamlit page for linking MeshCentral devices to SynapseITSM users.

Run on port 8503 (separate from the main dashboard):
    streamlit run ui/device_manager.py --server.port 8503

IT team / admin can:
  - Search users by email, full name, or user ID
  - Set / update the MeshCentral node ID, hostname, IP, OS platform, online status
  - Unlink a device from a user
  - Trigger a full sync from MeshCentral (auto-maps nodes by device name == email)
  - View which users have enrolled devices and whether the agent is currently online
"""
from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
OS_OPTIONS = ["windows", "linux", "darwin"]
OS_LABELS  = {"windows": "🪟 Windows", "linux": "🐧 Linux", "darwin": "🍎 macOS"}

st.set_page_config(
    page_title="SynapseITSM — Device Manager",
    page_icon="💻",
    layout="wide",
)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def do_login(email: str, password: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(f"{API_BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
        if resp.status_code == 401:
            return False, "Invalid email or password"
        resp.raise_for_status()
        data = resp.json()
        st.session_state["token"] = data["access_token"]
        st.session_state["user"]  = data["user"]
        return True, ""
    except Exception as exc:
        return False, str(exc)


def logout() -> None:
    st.session_state.pop("token", None)
    st.session_state.pop("user", None)


# ── API calls ─────────────────────────────────────────────────────────────────

def api_list_devices(q: str = "") -> list[dict]:
    try:
        if q.strip():
            resp = httpx.get(f"{API_BASE}/devices/users/search", params={"q": q}, headers=_headers(), timeout=8)
        else:
            resp = httpx.get(f"{API_BASE}/devices/users", headers=_headers(), timeout=8)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        st.error(f"Failed to load users: {exc}")
        return []


def api_update_device(user_id: str, payload: dict) -> tuple[bool, str, dict]:
    try:
        resp = httpx.put(f"{API_BASE}/devices/users/{user_id}", json=payload, headers=_headers(), timeout=10)
        resp.raise_for_status()
        return True, "", resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", str(exc)) if exc.response.content else str(exc)
        return False, detail, {}
    except Exception as exc:
        return False, str(exc), {}


def api_unlink_device(user_id: str) -> tuple[bool, str]:
    try:
        resp = httpx.delete(f"{API_BASE}/devices/users/{user_id}/device", headers=_headers(), timeout=10)
        resp.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def api_sync() -> tuple[bool, dict]:
    try:
        resp = httpx.post(f"{API_BASE}/devices/sync", headers=_headers(), timeout=45)
        resp.raise_for_status()
        return True, resp.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def api_ping_meshcentral() -> tuple[bool, str]:
    """Quick connectivity check — calls list_devices and inspects the response."""
    try:
        resp = httpx.post(f"{API_BASE}/devices/sync", headers=_headers(), timeout=15)
        if resp.status_code == 200:
            d = resp.json()
            return True, f"Connected — {d.get('synced',0)} synced"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# ── Login gate ────────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.title("💻 SynapseITSM — Device Manager")
    st.caption("IT team / admin only. Log in to manage endpoint device links.")
    with st.form("login_form"):
        email    = st.text_input("Email",    placeholder="it@synapse.io")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign In", type="primary", use_container_width=True):
            ok, err = do_login(email, password)
            if ok:
                st.rerun()
            else:
                st.error(err)
    with st.expander("Demo accounts"):
        st.markdown("- **IT team:** `it@synapse.io` / `it123456`\n- **Admin:** `admin@synapse.io` / `admin123`")
    st.stop()

user = st.session_state["user"]
if user["role"] not in ("it_team", "admin"):
    st.error("Access denied — IT team or admin role required.")
    if st.button("Log out"):
        logout()
        st.rerun()
    st.stop()


# ── Authenticated ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"### 💻 Device Manager")
    st.markdown(f"**{user['full_name']}**")
    st.caption(f"{user['email']} · `{user['role']}`")
    st.divider()

    st.markdown("**MeshCentral Sync**")
    st.caption(
        "Sync auto-maps devices to users by matching the device name "
        "in MeshCentral to the user's email (or email local-part)."
    )
    if st.button("Sync from MeshCentral", use_container_width=True, type="primary"):
        with st.spinner("Connecting to MeshCentral…"):
            ok, result = api_sync()
        if ok:
            st.success(
                f"Done — {result.get('synced', 0)} linked · "
                f"{result.get('unmatched', 0)} unmatched · "
                f"{result.get('errors', 0)} errors"
            )
        else:
            st.error(f"Sync failed: {result.get('error', 'unknown')}")

    st.divider()
    if st.button("Log out", use_container_width=True):
        logout()
        st.rerun()

    st.divider()
    st.caption(
        "**How to enroll a device**\n\n"
        "1. Open MeshCentral at `https://localhost:8443`\n"
        "2. Go to **SynapseITSM-Endpoints** group → **Add Agent**\n"
        "3. Name the device the user's **email** (e.g. `sara@synapse.io`)\n"
        "4. Run the installer on the user's PC (admin once)\n"
        "5. Click **Sync from MeshCentral** above — the device appears below automatically\n\n"
        "Or use **Manual Link** below to paste the Node ID directly."
    )


st.title("💻 Endpoint Device Manager")
st.caption(
    "Link MeshCentral device nodes to SynapseITSM users so the Remediation agent "
    "can apply fixes directly on the user's PC."
)

# ── Search bar ────────────────────────────────────────────────────────────────

search_col, stat_col = st.columns([4, 1])
with search_col:
    search_q = st.text_input(
        "Search",
        placeholder="Search by email, full name, or user ID…",
        label_visibility="collapsed",
    )
with stat_col:
    st.write("")  # vertical padding

devices = api_list_devices(search_q)

# Summary strip
enrolled = sum(1 for d in devices if d.get("meshcentral_nodeid"))
online   = sum(1 for d in devices if d.get("agent_online"))
total    = len(devices)
c1, c2, c3 = st.columns(3)
c1.metric("Users shown", total)
c2.metric("Enrolled", enrolled)
c3.metric("Online now", online)

st.divider()

# ── User cards ────────────────────────────────────────────────────────────────

if not devices:
    st.info("No users found. Try a different search or enroll devices in MeshCentral.")
else:
    for dev in devices:
        uid      = dev["id"]
        nodeid   = dev.get("meshcentral_nodeid") or ""
        hostname = dev.get("device_hostname") or ""
        ip       = dev.get("last_known_ip") or ""
        os_p     = dev.get("os_platform") or "windows"
        online_b = dev.get("agent_online", False)
        last_s   = dev.get("device_last_seen") or "—"

        enrolled_badge = "🟢 Online" if online_b else ("🔴 Offline" if nodeid else "⚫ Not enrolled")

        with st.expander(
            f"{enrolled_badge}  ·  **{dev['full_name']}**  —  `{dev['email']}`  ·  `{dev['role']}`",
            expanded=(not nodeid),   # auto-expand unenrolled users
        ):
            info_col, edit_col = st.columns([2, 3])

            with info_col:
                st.markdown("**Current device info**")
                if nodeid:
                    st.markdown(f"- **Node ID:** `{nodeid}`")
                    st.markdown(f"- **Hostname:** `{hostname or '—'}`")
                    st.markdown(f"- **IP:** `{ip or '—'}`")
                    st.markdown(f"- **OS:** {OS_LABELS.get(os_p, os_p)}")
                    st.markdown(f"- **Status:** {enrolled_badge}")
                    st.markdown(f"- **Last seen:** `{last_s}`")
                else:
                    st.info("No device linked yet.")

            with edit_col:
                st.markdown("**Update / link device**")
                with st.form(key=f"form_{uid}"):
                    f_nodeid   = st.text_input(
                        "MeshCentral Node ID",
                        value=nodeid,
                        placeholder="e.g. node//abc123xyz",
                        help="Copy from MeshCentral device details page or from the sync result.",
                    )
                    f_hostname = st.text_input(
                        "Device Hostname",
                        value=hostname,
                        placeholder="e.g. SARA-LAPTOP",
                    )
                    f_ip = st.text_input(
                        "Last Known IP",
                        value=ip,
                        placeholder="e.g. 192.168.1.42",
                    )
                    f_os = st.selectbox(
                        "OS Platform",
                        OS_OPTIONS,
                        index=OS_OPTIONS.index(os_p) if os_p in OS_OPTIONS else 0,
                        format_func=lambda x: OS_LABELS[x],
                    )
                    f_online = st.checkbox("Mark agent as online", value=online_b)

                    btn_col1, btn_col2 = st.columns(2)
                    save_btn   = btn_col1.form_submit_button("Save", type="primary", use_container_width=True)
                    unlink_btn = btn_col2.form_submit_button(
                        "Unlink device",
                        use_container_width=True,
                        disabled=not nodeid,
                    )

                if save_btn:
                    payload = {
                        "meshcentral_nodeid": f_nodeid.strip() or None,
                        "device_hostname":    f_hostname.strip() or None,
                        "last_known_ip":      f_ip.strip() or None,
                        "os_platform":        f_os,
                        "agent_online":       f_online,
                    }
                    ok, err, updated = api_update_device(uid, payload)
                    if ok:
                        st.success(f"Saved — {dev['full_name']}'s device updated.")
                        time.sleep(0.3)
                        st.rerun()
                    else:
                        st.error(f"Failed: {err}")

                elif unlink_btn:
                    ok, err = api_unlink_device(uid)
                    if ok:
                        st.warning(f"Device unlinked from {dev['full_name']}.")
                        time.sleep(0.3)
                        st.rerun()
                    else:
                        st.error(f"Unlink failed: {err}")

st.divider()
st.caption(
    "**Tip — Automatic mapping rule:** When you click **Sync from MeshCentral**, "
    "the system maps each MeshCentral device to a user by matching the device name "
    "to the user's email (or the part before the `@`). "
    "Name devices after user emails at install time for zero-touch mapping."
)
