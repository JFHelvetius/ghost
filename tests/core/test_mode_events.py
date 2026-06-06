"""Tests de `core.uncertainty.mode_events` (U1.b).

Cubre el dataclass `PerceptionModeChanged` y sus sinks
(`NullModeEventSink`, `RecordingModeEventSink`) más el `ModeEventSink` Protocol.

Schema canónico en `docs/specs/uncertainty.md` §9.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from project_ghost.core.uncertainty import (
    ModeEventSink,
    NullModeEventSink,
    PerceptionMode,
    PerceptionModeChanged,
    RecordingModeEventSink,
)


def _make_event(**overrides: Any) -> PerceptionModeChanged:
    defaults: dict[str, Any] = {
        "from_mode": PerceptionMode.NOMINAL,
        "to_mode": PerceptionMode.MOTION_AGGRESSIVE,
        "reason": "test_reason",
        "producer_ids": ("imu.0",),
        "stamp_sim_ns": 1_000,
    }
    defaults.update(overrides)
    return PerceptionModeChanged(**defaults)


# ---------------------------------------------------------------------------
# PerceptionModeChanged — construcción e invariantes
# ---------------------------------------------------------------------------


def test_event_valid_construction() -> None:
    ev = _make_event()
    assert ev.from_mode == PerceptionMode.NOMINAL
    assert ev.to_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert ev.reason == "test_reason"
    assert ev.producer_ids == ("imu.0",)
    assert ev.stamp_sim_ns == 1_000
    assert ev.schema_version == 1


def test_event_is_frozen() -> None:
    ev = _make_event()
    with pytest.raises(FrozenInstanceError):
        ev.reason = "mutated"  # type: ignore[misc]


def test_event_rejects_list_producer_ids() -> None:
    with pytest.raises(TypeError, match="producer_ids"):
        _make_event(producer_ids=["imu.0"])


def test_event_rejects_set_producer_ids() -> None:
    with pytest.raises(TypeError, match="producer_ids"):
        _make_event(producer_ids={"imu.0"})


def test_event_rejects_empty_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        _make_event(reason="")


def test_event_rejects_negative_stamp() -> None:
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        _make_event(stamp_sim_ns=-1)


def test_event_rejects_zero_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _make_event(schema_version=0)


def test_event_zero_stamp_is_allowed() -> None:
    ev = _make_event(stamp_sim_ns=0)
    assert ev.stamp_sim_ns == 0


def test_event_empty_producer_tuple_is_allowed() -> None:
    """Tupla vacía es legal: el detector puede emitir sin atribución concreta."""
    ev = _make_event(producer_ids=())
    assert ev.producer_ids == ()


def test_event_equality_by_value() -> None:
    """`frozen=True` implica `eq=True` por default."""
    a = _make_event(stamp_sim_ns=5)
    b = _make_event(stamp_sim_ns=5)
    assert a == b
    assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# NullModeEventSink
# ---------------------------------------------------------------------------


def test_null_sink_publish_is_noop() -> None:
    """No-op: ni levanta ni muta estado externo."""
    sink = NullModeEventSink()
    ev = _make_event()
    sink.publish(ev)  # not raising is the contract


def test_null_sink_satisfies_protocol() -> None:
    sink = NullModeEventSink()
    assert isinstance(sink, ModeEventSink)


# ---------------------------------------------------------------------------
# RecordingModeEventSink
# ---------------------------------------------------------------------------


def test_recording_sink_captures_events_in_order() -> None:
    sink = RecordingModeEventSink()
    ev1 = _make_event(stamp_sim_ns=1)
    ev2 = _make_event(stamp_sim_ns=2)
    sink.publish(ev1)
    sink.publish(ev2)
    assert sink.events == [ev1, ev2]


def test_recording_sink_clear_resets_events() -> None:
    sink = RecordingModeEventSink()
    sink.publish(_make_event())
    sink.publish(_make_event(stamp_sim_ns=2))
    assert len(sink.events) == 2
    sink.clear()
    assert sink.events == []


def test_recording_sink_starts_empty() -> None:
    sink = RecordingModeEventSink()
    assert sink.events == []


def test_recording_sink_satisfies_protocol() -> None:
    sink = RecordingModeEventSink()
    assert isinstance(sink, ModeEventSink)


# ---------------------------------------------------------------------------
# ModeEventSink Protocol — runtime_checkable
# ---------------------------------------------------------------------------


def test_arbitrary_callable_does_not_satisfy_protocol() -> None:
    """Un objeto sin `publish` no es un sink, aunque sea callable."""

    class _NotASink:
        def call(self, event: PerceptionModeChanged) -> None:
            pass

    assert not isinstance(_NotASink(), ModeEventSink)


def test_duck_typed_sink_satisfies_protocol() -> None:
    """Cualquier clase con `publish(event)` cuenta como ModeEventSink."""

    class _Custom:
        def __init__(self) -> None:
            self.calls: int = 0

        def publish(self, event: PerceptionModeChanged) -> None:
            del event
            self.calls += 1

    sink = _Custom()
    assert isinstance(sink, ModeEventSink)
    sink.publish(_make_event())
    assert sink.calls == 1
