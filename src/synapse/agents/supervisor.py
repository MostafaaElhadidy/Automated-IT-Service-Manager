"""Supervisor — the compiled graph + entry router + alert-queue drainer.

The Supervisor does NOT call an LLM on every hop. It IS the graph.
This module re-exports the build_graph function and drain_alerts for convenience.
"""
from synapse.graph import build_graph, route_entry, route_fast_path
from synapse.agents.monitoring import drain_alerts, run_monitoring_loop

__all__ = ["build_graph", "route_entry", "route_fast_path", "drain_alerts", "run_monitoring_loop"]
