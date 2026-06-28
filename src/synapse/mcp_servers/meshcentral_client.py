"""MeshCentral async client.

Drives the `meshctrl` CLI (Node.js) via subprocess so we don't have to
re-implement MeshCentral's WebSocket challenge-response auth protocol.

Prerequisites:
  npm install -g meshcentral          # installs meshctrl on PATH
  -or-
  node /path/to/meshcentral meshctrl  # if installed locally

All public functions return empty / False and log a warning when
MESHCENTRAL_ENABLED=false or the meshctrl binary is not found, so the rest
of the system continues to work without MeshCentral configured.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from synapse.config import settings
from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _base_cmd() -> list[str]:
    """Return the base meshctrl command with server URL + auth flags.

    meshctrl appends /control.ashx to the URL itself, so we pass the base URL only.
    """
    return [
        *settings.meshcentral_meshctrl_cmd,       # e.g. ["node", "/path/meshctrl.js"]
        "--url", settings.meshcentral_base_url,   # e.g. wss://192.168.1.14:8443
        *settings.meshcentral_auth_args,
    ]


def _subprocess_env() -> dict[str, str]:
    """Build subprocess env with TLS verification disabled when configured."""
    env = os.environ.copy()
    if not settings.meshcentral_verify_tls:
        env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
    return env


def _run_meshctrl_sync(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """Synchronous helper — runs in a thread so it's safe under any event loop."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_subprocess_env(),
            timeout=timeout,
        )
        return (
            result.returncode,
            result.stdout.decode(errors="replace"),
            result.stderr.decode(errors="replace"),
        )
    except FileNotFoundError:
        return -1, "", f"executable not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


async def _run_meshctrl(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a meshctrl sub-command. Returns (returncode, stdout, stderr).

    Uses run_in_executor so asyncio.create_subprocess_exec is never called —
    that API raises NotImplementedError under Windows SelectorEventLoop which
    FastAPI / uvicorn can use in some configurations.
    """
    cmd = _base_cmd() + list(args)
    logger.info("meshctrl cmd: %s", " ".join(cmd))
    rc, out, err = await asyncio.get_event_loop().run_in_executor(
        None, _run_meshctrl_sync, cmd, timeout
    )
    if rc != 0 or err:
        logger.debug("meshctrl stderr: %s", err.strip())
    return rc, out, err


def _guard() -> bool:
    """Return True (and log) when MeshCentral integration is disabled."""
    if not settings.meshcentral_enabled:
        logger.debug("MeshCentral integration is disabled (MESHCENTRAL_ENABLED=false)")
        return True
    return False


# ── Connectivity check ────────────────────────────────────────────────────────

async def ping() -> bool:
    """Return True if we can reach MeshCentral and authenticate."""
    if _guard():
        return False
    rc, out, err = await _run_meshctrl("serverinfo", "--json", timeout=15)
    if rc != 0:
        logger.warning("MeshCentral ping failed: %s", err or out)
        return False
    return True


# ── Node listing ──────────────────────────────────────────────────────────────

async def list_nodes() -> list[dict[str, Any]]:
    """Return all devices in the configured device group as dicts.

    Each dict has at minimum: nodeid, name, host, conn (online bitmask), osdesc.
    Returns [] on any error.
    """
    if _guard():
        return []

    rc, out, err = await _run_meshctrl(
        "listdevices",
        "--json",
        "--all",
        timeout=30,
    )
    if rc != 0:
        logger.warning("listdevices failed: %s", err)
        return []

    try:
        data = json.loads(out)
        # meshctrl returns either a list or {"result": [...]}
        if isinstance(data, list):
            nodes = data
        elif isinstance(data, dict):
            nodes = data.get("result", data.get("devices", [data]))
        else:
            nodes = []
        return nodes
    except json.JSONDecodeError:
        logger.warning("listdevices returned non-JSON: %s", out[:200])
        return []


async def get_node(nodeid: str) -> dict[str, Any] | None:
    """Return info for a single node by its nodeid, or None."""
    if _guard():
        return None

    rc, out, _ = await _run_meshctrl(
        "listdevices", "--id", nodeid, "--json", timeout=15
    )
    if rc != 0:
        return None
    try:
        data = json.loads(out)
        nodes = data if isinstance(data, list) else data.get("result", [])
        return nodes[0] if nodes else None
    except Exception:
        return None


# ── Remote command execution ──────────────────────────────────────────────────

SHELL_TYPE = {"powershell": 2, "cmd": 1, "bash": 0}


async def run_remote(
    nodeid: str,
    command: str,
    shell: str = "powershell",
    timeout: int = 30,
) -> bool:
    """Send a command to a remote device via MeshCentral.

    NOTE: meshctrl runcommand sends the command but does NOT reliably return
    its output. Use the script self-report pattern — wrap the command so it
    POSTs its result to POST /agent/result — and await the callback there.

    Returns True if the command was dispatched successfully (not that it ran).
    """
    if _guard():
        return False

    if shell == "powershell":
        # Multiline scripts can't survive Windows CreateProcess → Node.js arg
        # parsing because embedded newlines corrupt the argument boundary.
        # PowerShell -EncodedCommand accepts a base64 UTF-16LE blob on one line.
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        run_cmd = f"powershell -ExecutionPolicy Bypass -NonInteractive -EncodedCommand {encoded}"
        shell_type = "1"  # send via CMD shell; CMD launches powershell
    else:
        run_cmd = command
        shell_type = str(SHELL_TYPE.get(shell, 2))

    rc, _out, err = await _run_meshctrl(
        "runcommand",
        "--id", nodeid,
        "--run", run_cmd,
        "--type", shell_type,
        timeout=timeout,
    )
    if rc != 0:
        logger.warning("runcommand to %s failed: %s", nodeid, err)
        return False

    logger.info("runcommand dispatched to nodeid=%s (shell=%s)", nodeid, shell)
    return True


# ── Device sync (populate users.meshcentral_* from MeshCentral) ───────────────

def _is_online(conn: Any) -> bool:
    """MeshCentral 'conn' bitmask: bit 1 = agent connected."""
    try:
        return bool(int(conn) & 1)
    except (TypeError, ValueError):
        return False


def _parse_os(osdesc: str) -> str:
    """Map MeshCentral OS description to 'windows' | 'darwin' | 'linux'."""
    low = (osdesc or "").lower()
    if "win" in low:
        return "windows"
    if "mac" in low or "darwin" in low:
        return "darwin"
    return "linux"


def _extract_ip(node: dict) -> str:
    """Pull the best available IP from a node dict."""
    # meshctrl may return ip, host, or publicip
    for key in ("ip", "host", "publicip"):
        val = node.get(key, "")
        if val and val not in ("", "0.0.0.0"):
            return str(val)
    return ""


async def sync_devices() -> dict[str, int]:
    """Pull nodes from MeshCentral and update users.meshcentral_* columns.

    Mapping rule: node["name"] is matched to users.email (exact, lowercase).
    Fallback: match node["name"] against users.device_hostname.

    Returns {"synced": N, "unmatched": M, "errors": E}.
    """
    if _guard():
        return {"synced": 0, "unmatched": 0, "errors": 0}

    nodes = await list_nodes()
    if not nodes:
        return {"synced": 0, "unmatched": 0, "errors": 0}

    synced = unmatched = errors = 0

    async with AsyncSessionLocal() as session:
        # Build lookup maps once
        all_users = await repo.list_users(session)
        by_email = {u.email.lower(): u for u in all_users}
        by_hostname = {(u.device_hostname or "").lower(): u for u in all_users if u.device_hostname}

        for node in nodes:
            nodeid: str = node.get("_id") or node.get("nodeid") or node.get("id", "")
            name: str = (node.get("name") or "").strip()
            osdesc: str = node.get("osdesc") or node.get("os") or ""
            conn: Any = node.get("conn", 0)

            if not nodeid:
                continue

            # Match by name == email first, then hostname
            user = by_email.get(name.lower()) or by_hostname.get(name.lower())

            if user is None:
                # Try partial email match (device named "sara" → "sara@synapse.io")
                for email, u in by_email.items():
                    local_part = email.split("@")[0]
                    if local_part == name.lower():
                        user = u
                        break

            if user is None:
                logger.debug("No SynapseITSM user found for MeshCentral node '%s' (%s)", name, nodeid)
                unmatched += 1
                continue

            try:
                await repo.update_user_device(
                    session,
                    user.id,
                    nodeid=nodeid,
                    hostname=name,
                    ip=_extract_ip(node),
                    os_platform=_parse_os(osdesc),
                    online=_is_online(conn),
                    last_seen=datetime.now(timezone.utc),
                )
                synced += 1
                logger.info(
                    "Synced MeshCentral node '%s' → user %s (online=%s)",
                    name, user.email, _is_online(conn),
                )
            except Exception as exc:
                logger.error("Failed to update user %s: %s", user.id, exc)
                errors += 1

    return {"synced": synced, "unmatched": unmatched, "errors": errors}


# ── Online-status refresh (lightweight) ──────────────────────────────────────

async def refresh_online_status() -> None:
    """Update only the agent_online flag for all linked users."""
    if _guard():
        return

    nodes = await list_nodes()
    if not nodes:
        return

    node_map = {
        node.get("_id") or node.get("nodeid") or node.get("id", ""): _is_online(node.get("conn", 0))
        for node in nodes
    }

    async with AsyncSessionLocal() as session:
        all_users = await repo.list_users(session)
        for user in all_users:
            if user.meshcentral_nodeid and user.meshcentral_nodeid in node_map:
                online = node_map[user.meshcentral_nodeid]
                if online != user.agent_online:
                    await repo.update_user_device(
                        session, user.id, online=online,
                        last_seen=datetime.now(timezone.utc),
                    )
