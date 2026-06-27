"""In-process store for remote remediation job results.

When a runbook runs on a user's PC via MeshCentral, the remote script POSTs
its result back to POST /agent/result. This store holds asyncio.Events so
execute_and_verify() can await the callback with a timeout.

Keyed by job_id (UUID generated per execution attempt).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from synapse.config import settings


@dataclass
class JobResult:
    job_id: str
    nodeid: str
    runbook_id: str
    steps: list[dict] = field(default_factory=list)
    ok: bool = False
    # Set by report_step("complete", ...) so await_result() can unblock
    _done: asyncio.Event = field(default_factory=asyncio.Event)
    completed_at: datetime | None = None


# job_id → JobResult
_jobs: dict[str, JobResult] = {}


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def create_job(nodeid: str, runbook_id: str) -> JobResult:
    job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
    job = JobResult(job_id=job_id, nodeid=nodeid, runbook_id=runbook_id)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> JobResult | None:
    return _jobs.get(job_id)


def clear_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


# ── Result reporting (called by POST /agent/result) ───────────────────────────

def report_step(job_id: str, step: str, ok: bool, output: str) -> bool:
    """Record one step result. Returns False if job_id is unknown."""
    job = _jobs.get(job_id)
    if job is None:
        return False
    job.steps.append({"step": step, "ok": ok, "output": output})
    # "complete" is the terminal step that unblocks await_result()
    if step == "complete":
        job.ok = ok
        job.completed_at = datetime.now(timezone.utc)
        job._done.set()
    return True


async def await_result(job_id: str, timeout: float = 120.0) -> JobResult | None:
    """Await the terminal 'complete' step, up to timeout seconds.

    Returns the JobResult (possibly with ok=False) on timeout so callers can
    still surface partial step logs rather than crashing.
    """
    job = _jobs.get(job_id)
    if job is None:
        return None
    try:
        await asyncio.wait_for(job._done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        # Mark timed-out so callers know
        job.steps.append({"step": "timeout", "ok": False, "output": f"No callback received within {timeout}s"})
        job.ok = False
        job.completed_at = datetime.now(timezone.utc)
    return job


# ── HMAC token (prevents random hosts from spoofing results) ─────────────────

def make_job_token(job_id: str) -> str:
    """Generate a per-job HMAC token embedded in the remote script."""
    secret = settings.jwt_secret.encode()
    return hmac.new(secret, job_id.encode(), hashlib.sha256).hexdigest()[:32]


def verify_job_token(job_id: str, token: str) -> bool:
    expected = make_job_token(job_id)
    return hmac.compare_digest(expected, token)
