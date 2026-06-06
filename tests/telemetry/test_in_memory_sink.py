"""Tests de `telemetry.sink.InMemorySink` + Protocol check."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from project_ghost.events import Event, EventSeverity, EventType
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CapturedMessage,
    InMemorySink,
    TelemetrySink,
)


def _event(seq: int = 0) -> Event:
    return Event(
        type=EventType.MISSION_START,
        severity=EventSeverity.INFO,
        source="test.source",
        stamp_sim_ns=seq * 100,
        stamp_wall_ns=seq * 100,
        sequence=seq,
        payload=MappingProxyType({}),
        correlation_id=None,
    )


def test_in_memory_sink_satisfies_telemetry_sink_protocol() -> None:
    sink = InMemorySink()
    assert isinstance(sink, TelemetrySink)


def test_in_memory_sink_records_messages_in_publish_order() -> None:
    sink = InMemorySink()
    for i in range(5):
        sink.publish(CHANNEL_EVENTS, i * 100, _event(seq=i))
    assert len(sink.captured) == 5
    assert [m.stamp_sim_ns for m in sink.captured] == [0, 100, 200, 300, 400]
    assert all(m.channel == CHANNEL_EVENTS for m in sink.captured)


def test_in_memory_sink_preserves_message_identity() -> None:
    sink = InMemorySink()
    ev = _event()
    sink.publish(CHANNEL_EVENTS, 0, ev)
    assert sink.captured[0].message is ev


def test_in_memory_sink_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="must start with '/'"):
        sink.publish("events", 0, _event())


def test_in_memory_sink_rejects_negative_stamp() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        sink.publish(CHANNEL_EVENTS, -1, _event())


def test_in_memory_sink_rejects_publish_after_close() -> None:
    sink = InMemorySink()
    sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        sink.publish(CHANNEL_EVENTS, 0, _event())


def test_in_memory_sink_close_is_idempotent() -> None:
    sink = InMemorySink()
    sink.close()
    sink.close()  # second close must not raise


def test_in_memory_sink_clear_resets_captured() -> None:
    sink = InMemorySink()
    sink.publish(CHANNEL_EVENTS, 0, _event())
    assert len(sink.captured) == 1
    sink.clear()
    assert sink.captured == []


def test_in_memory_sink_context_manager_closes_on_exit() -> None:
    with InMemorySink() as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())
    assert len(sink.captured) == 1
    with pytest.raises(RuntimeError, match="closed"):
        sink.publish(CHANNEL_EVENTS, 100, _event())


def test_captured_message_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    cm = CapturedMessage(channel="/x", stamp_sim_ns=0, message=None)
    with pytest.raises(FrozenInstanceError):
        cm.channel = "/y"  # type: ignore[misc]
