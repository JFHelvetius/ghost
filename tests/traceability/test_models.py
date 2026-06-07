"""Tests del `BehaviorTrace` + `TracedMessage` dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from project_ghost.traceability import (
    TRACE_SCHEMA_VERSION,
    BehaviorTrace,
    EventNotFoundError,
    TracedMessage,
)


def _trace(**overrides: object) -> BehaviorTrace:
    defaults: dict[str, object] = {
        "event_id": 0,
        "event_type": "armed",
        "preceding_events": (),
        "preceding_sensor_samples": (),
        "preceding_actuator_commands": (),
        "preceding_state_changes": (),
        "window_start_ns": 0,
        "window_end_ns": 100,
    }
    defaults.update(overrides)
    return BehaviorTrace(**defaults)  # type: ignore[arg-type]


def test_traced_message_construction() -> None:
    m = TracedMessage(
        channel="/events",
        log_time_sim_ns=100,
        schema_name="project_ghost.events.types.Event",
        summary={"type": "armed", "sequence": 5},
    )
    assert m.channel == "/events"
    assert m.summary["type"] == "armed"


def test_traced_message_is_frozen() -> None:
    m = TracedMessage(
        channel="/events",
        log_time_sim_ns=100,
        schema_name="x",
        summary={},
    )
    with pytest.raises(FrozenInstanceError):
        m.channel = "/other"  # type: ignore[misc]


def test_behavior_trace_construction() -> None:
    t = _trace()
    assert t.event_id == 0
    assert t.event_type == "armed"
    assert t.preceding_events == ()
    assert t.schema_version == TRACE_SCHEMA_VERSION


def test_behavior_trace_is_frozen() -> None:
    t = _trace()
    with pytest.raises(FrozenInstanceError):
        t.event_id = 99  # type: ignore[misc]


def test_behavior_trace_schema_version_is_string() -> None:
    assert isinstance(TRACE_SCHEMA_VERSION, str)
    assert TRACE_SCHEMA_VERSION == "1"


def test_behavior_trace_carries_default_schema_version() -> None:
    t = _trace()
    assert t.schema_version == "1"


def test_behavior_trace_supports_explicit_schema_version_override() -> None:
    t = _trace(schema_version="2")
    assert t.schema_version == "2"


def test_behavior_trace_equality_by_value() -> None:
    a = _trace(event_id=5)
    b = _trace(event_id=5)
    assert a == b


def test_event_not_found_error_is_lookup_error() -> None:
    """Allows `except LookupError:` for callers that don't import our
    specific exception type."""
    err = EventNotFoundError("event_id=42 not found in MCAP")
    assert isinstance(err, LookupError)
    assert "42" in str(err)
