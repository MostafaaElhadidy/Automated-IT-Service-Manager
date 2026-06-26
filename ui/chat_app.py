"""Chainlit chat UI — thin client over the SynapseITSM backend API.

Does NOT import agents or touch the DB directly.
"""
from __future__ import annotations
import asyncio
import asyncio.tasks as _asyncio_tasks

# ── Python 3.14 + nest_asyncio 1.6.0 compatibility fix ──────────────────────
#
# nest_asyncio replaces asyncio.Task (C extension) with _PyTask (pure Python).
# In Python 3.14, asyncio.current_task() delegates to the C function
# _asyncio._get_running_task(), which is never updated by _PyTask.__step.
# Result: current_task() always returns None inside running tasks.
#
# Fix A — patch asyncio.current_task to read from the Python dict that
#          _PyTask.__step DOES update: asyncio.tasks._current_tasks.
def _fixed_current_task(loop=None):
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return _asyncio_tasks._current_tasks.get(running_loop)

asyncio.current_task = _fixed_current_task
_asyncio_tasks.current_task = _fixed_current_task

# Fix B — patch sniffio to detect asyncio via get_running_loop() instead of
#          current_task(), so detection works even before Fix A takes effect
#          (sniffio is imported before this module in some code paths).
import sniffio as _sniffio
import sniffio._impl as _sniffio_impl

def _fixed_current_async_library() -> str:
    value = _sniffio_impl.thread_local.name
    if value is not None:
        return value
    value = _sniffio_impl.current_async_library_cvar.get()
    if value is not None:
        return value
    try:
        asyncio.get_running_loop()
        return "asyncio"
    except RuntimeError:
        pass
    raise _sniffio_impl.AsyncLibraryNotFoundError(
        "unknown async library, or not in async context"
    )

_sniffio_impl.current_async_library = _fixed_current_async_library
_sniffio.current_async_library = _fixed_current_async_library
# ─────────────────────────────────────────────────────────────────────────────

import os
import httpx
import chainlit as cl

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# Session state keys
SESSION_KEY = "synapse_session_id"
TOKEN_KEY = "backend_token"


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """Authenticate against the backend /auth/login. username = email."""
    try:
        resp = httpx.post(
            f"{API_BASE}/auth/login",
            json={"email": username, "password": password},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Stash the backend JWT in the Chainlit user metadata for later calls.
        return cl.User(
            identifier=data["user"]["email"],
            metadata={
                "token": data["access_token"],
                "role": data["user"]["role"],
                "full_name": data["user"]["full_name"],
            },
        )
    except Exception:
        return None


def _token() -> str:
    """Return the backend JWT for the logged-in Chainlit user."""
    # Chainlit 2.x stores the user on context.session.user, not user_session.
    try:
        app_user = cl.context.session.user
    except Exception:
        app_user = cl.user_session.get("user")
    if app_user and app_user.metadata:
        return app_user.metadata.get("token", "")
    return ""


def _auth_headers() -> dict:
    tok = _token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def _get_or_create_session() -> str:
    """Get existing session_id or create a new one."""
    session_id = cl.user_session.get(SESSION_KEY)
    if session_id:
        return session_id
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{API_BASE}/sessions", headers=_auth_headers())
        resp.raise_for_status()
        session_id = resp.json()["session_id"]
    cl.user_session.set(SESSION_KEY, session_id)
    return session_id


async def _poll_notifications(session_id: str) -> None:
    """Background task: poll the backend every 3 s and push any IT decision to chat."""
    while True:
        await asyncio.sleep(3)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{API_BASE}/sessions/{session_id}/notification")
                if resp.status_code == 200:
                    msg = resp.json().get("message")
                    if msg:
                        await cl.Message(content=msg).send()
        except Exception:
            pass  # backend not reachable yet — retry next tick


@cl.on_chat_start
async def on_chat_start():
    try:
        session_id = await _get_or_create_session()
    except Exception as exc:
        await cl.Message(
            content=f"⚠️ Could not connect to the backend: {exc}\n\nMake sure the backend is running (`make backend`) and try refreshing."
        ).send()
        return
    app_user = cl.user_session.get("user")
    name = app_user.metadata.get("full_name", "there") if app_user and app_user.metadata else "there"
    await cl.Message(
        content=(
            f"👋 **Welcome to SynapseITSM, {name}**\n\n"
            "Describe your IT issue in plain language and I'll triage, diagnose, "
            "and propose a fix for you.\n\n"
            f"_Session: `{session_id}`_"
        )
    ).send()
    task = asyncio.create_task(_poll_notifications(session_id))
    cl.user_session.set("_poll_task", task)


@cl.on_chat_end
async def on_chat_end():
    task = cl.user_session.get("_poll_task")
    if task:
        task.cancel()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = await _get_or_create_session()
    user_text = message.content

    # Show a thinking indicator
    thinking = cl.Message(content="⏳ Analyzing...")
    await thinking.send()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{API_BASE}/sessions/{session_id}/messages",
                json={"message": user_text},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        await thinking.update()
        await cl.Message(content=f"❌ Backend error: {exc.response.status_code} — {exc.response.text}").send()
        return
    except Exception as exc:
        await thinking.update()
        await cl.Message(content=f"❌ Connection error: {exc}").send()
        return

    reply = data.get("reply", "No response from backend.")
    tickets = data.get("tickets", [])
    pending = data.get("pending_action")
    escalated = data.get("escalated", False)

    # Build response message
    parts = [reply]

    if tickets:
        ticket_lines = []
        for t in tickets:
            ticket_lines.append(
                f"  - **{t['id']}** | {t['category']} | {t['priority']} | {t['status']}"
            )
        parts.append("\n**Tickets:**\n" + "\n".join(ticket_lines))

    if escalated:
        parts.append("\n⚠️ _Issue escalated to IT team._")

    await thinking.remove()
    await cl.Message(content="\n\n".join(parts)).send()

    # If HITL pending — notify user; approval happens in the dashboard
    if pending:
        await cl.Message(
            content=(
                f"**Approval Required**\n\n"
                f"Runbook `{pending['runbook_id']}` is waiting for IT approval.\n\n"
                f"An IT member must **approve or reject** this action from the "
                f"**Operations Dashboard** before execution continues."
            ),
        ).send()
