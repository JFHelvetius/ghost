"""Tests del `RunSummary` dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from project_ghost.analysis import SUMMARY_SCHEMA_VERSION, RunSummary


def _summary(**overrides: object) -> RunSummary:
    defaults: dict[str, object] = {
        "run_id": "test-run",
        "event_count": 0,
        "sensor_sample_count": 0,
        "actuator_command_count": 0,
        "state_transition_count": 0,
        "healthy_sensor_count": 0,
        "unhealthy_sensor_count": 0,
        "first_timestamp_ns": None,
        "last_timestamp_ns": None,
        "duration_ns": None,
        "event_type_counts": {},
        "sensor_type_counts": {},
        "actuator_type_counts": {},
        "final_state_hash": "deadbeef",
    }
    defaults.update(overrides)
    return RunSummary(**defaults)  # type: ignore[arg-type]


def test_run_summary_construction() -> None:
    s = _summary()
    assert s.run_id == "test-run"
    assert s.schema_version == SUMMARY_SCHEMA_VERSION


def test_run_summary_is_frozen() -> None:
    s = _summary()
    with pytest.raises(FrozenInstanceError):
        s.event_count = 100  # type: ignore[misc]


def test_run_summary_schema_version_is_string() -> None:
    assert isinstance(SUMMARY_SCHEMA_VERSION, str)
    assert SUMMARY_SCHEMA_VERSION == "1"


def test_run_summary_carries_default_schema_version() -> None:
    s = _summary()
    assert s.schema_version == "1"


def test_run_summary_supports_explicit_schema_version_override() -> None:
    """Future versions can bump the schema; the dataclass accepts it."""
    s = _summary(schema_version="2")
    assert s.schema_version == "2"


def test_run_summary_equality_by_value() -> None:
    a = _summary(run_id="x", event_count=5)
    b = _summary(run_id="x", event_count=5)
    assert a == b


def test_run_summary_with_populated_histograms() -> None:
    s = _summary(
        event_count=3,
        event_type_counts={"mission_start": 1, "takeoff": 2},
        sensor_type_counts={"IMUPayload": 100},
    )
    assert s.event_type_counts == {"mission_start": 1, "takeoff": 2}
    assert s.sensor_type_counts == {"IMUPayload": 100}


def test_run_summary_timestamps_optional() -> None:
    s = _summary()
    assert s.first_timestamp_ns is None
    assert s.last_timestamp_ns is None
    assert s.duration_ns is None
