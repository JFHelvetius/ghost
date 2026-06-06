"""Tests del schema `Event` + `EventSeverity` + `EventType` (T5.a)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any

import pytest

from project_ghost.events import Event, EventSeverity, EventType


def _make_event(**overrides: Any) -> Event:
    defaults: dict[str, Any] = {
        "type": EventType.MISSION_START,
        "severity": EventSeverity.INFO,
        "source": "mission.fsm",
        "stamp_sim_ns": 1_000,
        "stamp_wall_ns": 2_000,
        "sequence": 0,
        "payload": MappingProxyType({"idx": 0}),
        "correlation_id": None,
    }
    defaults.update(overrides)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# EventSeverity
# ---------------------------------------------------------------------------


def test_severity_total_ordering() -> None:
    assert EventSeverity.DEBUG < EventSeverity.INFO
    assert EventSeverity.INFO < EventSeverity.WARN
    assert EventSeverity.WARN < EventSeverity.ERROR
    assert EventSeverity.ERROR < EventSeverity.CRITICAL


def test_severity_values_match_spec() -> None:
    """Valores 10/20/30/40/50 per events.md §3."""
    assert EventSeverity.DEBUG.value == 10
    assert EventSeverity.INFO.value == 20
    assert EventSeverity.WARN.value == 30
    assert EventSeverity.ERROR.value == 40
    assert EventSeverity.CRITICAL.value == 50


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


def test_event_type_values_unique() -> None:
    values = [t.value for t in EventType]
    assert len(values) == len(set(values))


def test_event_type_catalog_size_matches_spec() -> None:
    """events.md §3 enumera 19 tipos canónicos (5 lifecycle + 4 mission +
    5 safety + 3 sensors + 2 infra)."""
    assert len(list(EventType)) == 19


def test_event_type_str_value_is_lowercase() -> None:
    for t in EventType:
        assert t.value == t.value.lower()


# ---------------------------------------------------------------------------
# Event — construcción y frozen
# ---------------------------------------------------------------------------


def test_event_valid_construction() -> None:
    ev = _make_event()
    assert ev.type == EventType.MISSION_START
    assert ev.severity == EventSeverity.INFO
    assert ev.source == "mission.fsm"
    assert ev.stamp_sim_ns == 1_000
    assert ev.stamp_wall_ns == 2_000
    assert ev.sequence == 0
    assert ev.payload == {"idx": 0}
    assert ev.correlation_id is None
    assert ev.schema_version == 1


def test_event_is_frozen() -> None:
    ev = _make_event()
    with pytest.raises(FrozenInstanceError):
        ev.source = "mutated"  # type: ignore[misc]


def test_event_equality_by_value() -> None:
    a = _make_event(stamp_sim_ns=5)
    b = _make_event(stamp_sim_ns=5)
    assert a == b


# ---------------------------------------------------------------------------
# Event — validación de invariantes (uncertainty.md style)
# ---------------------------------------------------------------------------


def test_event_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source"):
        _make_event(source="")


def test_event_rejects_negative_stamp_sim_ns() -> None:
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        _make_event(stamp_sim_ns=-1)


def test_event_rejects_negative_stamp_wall_ns() -> None:
    with pytest.raises(ValueError, match="stamp_wall_ns"):
        _make_event(stamp_wall_ns=-1)


def test_event_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError, match="sequence"):
        _make_event(sequence=-1)


def test_event_rejects_zero_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _make_event(schema_version=0)


def test_event_zero_stamps_are_allowed() -> None:
    ev = _make_event(stamp_sim_ns=0, stamp_wall_ns=0)
    assert ev.stamp_sim_ns == 0
    assert ev.stamp_wall_ns == 0


def test_event_correlation_id_can_be_string() -> None:
    ev = _make_event(correlation_id="mission-abc123")
    assert ev.correlation_id == "mission-abc123"
