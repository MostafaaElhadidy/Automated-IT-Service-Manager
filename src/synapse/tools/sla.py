"""SLA resolution targets by priority."""
from __future__ import annotations
from datetime import timedelta
from synapse.state import Priority

# Resolution target per priority
SLA_TARGETS: dict[Priority, timedelta] = {
    "P1": timedelta(hours=1),
    "P2": timedelta(hours=4),
    "P3": timedelta(hours=8),
    "P4": timedelta(hours=24),
    "P5": timedelta(hours=72),
}

# Response (first acknowledgement) targets
RESPONSE_TARGETS: dict[Priority, timedelta] = {
    "P1": timedelta(minutes=15),
    "P2": timedelta(minutes=30),
    "P3": timedelta(hours=2),
    "P4": timedelta(hours=4),
    "P5": timedelta(hours=8),
}


def resolution_target(priority: Priority) -> timedelta:
    return SLA_TARGETS[priority]


def response_target(priority: Priority) -> timedelta:
    return RESPONSE_TARGETS[priority]


def sla_label(priority: Priority) -> str:
    t = SLA_TARGETS[priority]
    hours = int(t.total_seconds() // 3600)
    minutes = int((t.total_seconds() % 3600) // 60)
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"
