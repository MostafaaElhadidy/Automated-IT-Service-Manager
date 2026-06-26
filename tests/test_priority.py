"""Priority tool tests."""
from __future__ import annotations
import pytest
from synapse.tools.priority import urgency_from_text, _impact_score, _MATRIX
from synapse.tools.sla import resolution_target, sla_label


def test_urgency_extraction():
    assert urgency_from_text("This is URGENT, system is down!") == 1
    assert urgency_from_text("Sales dashboard is slow") == 2
    assert urgency_from_text("Please add me to the VPN group") == 4


def test_impact_score():
    # High criticality (1) + many dependents → impact 1
    assert _impact_score(5, 1) == 1
    # Low criticality (5) + few dependents → impact 5
    assert _impact_score(0, 5) == 5


def test_priority_matrix():
    # P1: critical impact + urgent
    assert _MATRIX[(1, 1)] == "P1"
    # P5: low impact + low urgency
    assert _MATRIX[(5, 5)] == "P5"
    # P3 in the middle
    assert _MATRIX[(3, 3)] == "P3"


def test_sla_label():
    assert sla_label("P1") == "1h"
    assert sla_label("P2") == "4h"
    assert "24h" in sla_label("P4")


def test_resolution_target():
    from datetime import timedelta
    assert resolution_target("P1") == timedelta(hours=1)
    assert resolution_target("P5") == timedelta(hours=72)
