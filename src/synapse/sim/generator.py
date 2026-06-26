"""Deterministic anomaly simulator.

Reads sim/scenarios.yaml and injects metric anomalies at scheduled offsets.
Uses SIM_SEED for reproducibility.
"""
from __future__ import annotations
import asyncio
import logging
import pathlib
import random
import time
from dataclasses import dataclass
from typing import AsyncGenerator

import yaml

from synapse.config import settings

logger = logging.getLogger(__name__)
_SCENARIOS_FILE = pathlib.Path(__file__).parent / "scenarios.yaml"


@dataclass
class AnomalyEvent:
    ci_id: str
    metric: str
    value: float
    description: str
    timestamp: float


def _load_scenarios() -> list[dict]:
    with open(_SCENARIOS_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("scenarios", [])


async def stream_anomalies(start_time: float | None = None) -> AsyncGenerator[AnomalyEvent, None]:
    """Yield AnomalyEvent objects according to the seeded scenario schedule.

    Loops forever, re-playing scenarios every cycle.
    """
    rng = random.Random(settings.sim_seed)
    scenarios = _load_scenarios()
    if not start_time:
        start_time = time.monotonic()

    fired: set[str] = set()
    cycle = 0

    while True:
        now = time.monotonic()
        elapsed = now - start_time

        for scenario in scenarios:
            key = f"{cycle}_{scenario['name']}"
            offset = scenario["t_offset"]

            if elapsed >= offset and key not in fired:
                fired.add(key)
                # Add small jitter (±5s) but stay deterministic via seeded RNG
                jitter = rng.uniform(-5, 5)
                event = AnomalyEvent(
                    ci_id=scenario["ci_id"],
                    metric=scenario["metric"],
                    value=scenario["anomaly_value"],
                    description=scenario["description"],
                    timestamp=time.time(),
                )
                logger.info(
                    "[sim] Anomaly: %s ci=%s metric=%s value=%s",
                    scenario["name"], event.ci_id, event.metric, event.value,
                )

                # Inject into runbook_server's simulated metric store
                try:
                    from synapse.mcp_servers.runbook_server import set_metric
                    set_metric(event.metric, event.ci_id, event.value)
                except Exception as exc:
                    logger.warning("Could not inject metric into sim: %s", exc)

                yield event

        # Check if all scenarios fired in this cycle; start new cycle
        if len(fired) >= len(scenarios) * (cycle + 1):
            cycle += 1
            start_time = time.monotonic()  # reset for next cycle
            await asyncio.sleep(60)  # wait before re-playing

        await asyncio.sleep(5)
