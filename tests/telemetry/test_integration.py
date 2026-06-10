"""Integration tests: EventBus → telemetry sink → file → replay.

End-to-end verification that the three-line subscriber adapter (described
in the T4 architecture doc) successfully captures EventBus traffic to an
MCAP file, and that replay reconstructs the same events.

This is the documented public path — what real publishers would do.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from project_ghost.events import (
    Event,
    EventBus,
    EventSeverity,
    EventType,
)
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    TelemetrySink,
    decode_message,
)


def _ev(
    *,
    type_: EventType = EventType.MISSION_START,
    severity: EventSeverity = EventSeverity.INFO,
    source: str = "test.source",
    payload: dict[str, object] | None = None,
) -> Event:
    return Event(
        type=type_,
        severity=severity,
        source=source,
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        sequence=0,
        payload=MappingProxyType(payload or {}),
        correlation_id=None,
    )


def _wire_bus_to_sink(bus: EventBus, sink: TelemetrySink) -> None:
    """The three-line adapter from the T4 design doc.

    The EventBus rewrites `sequence` on publish; we use the sealed event's
    stamp_sim_ns as the log time."""
    bus.subscribe_all(lambda ev: sink.publish(CHANNEL_EVENTS, ev.stamp_sim_ns, ev))


# ---------------------------------------------------------------------------
# In-memory path — fast, no I/O
# ---------------------------------------------------------------------------


def test_event_bus_to_in_memory_sink_captures_published_events() -> None:
    bus = EventBus()
    sink = InMemorySink()
    _wire_bus_to_sink(bus, sink)

    bus.publish(_ev(type_=EventType.ARMED))
    bus.publish(_ev(type_=EventType.TAKEOFF))
    bus.publish(_ev(type_=EventType.LANDED))

    assert len(sink.captured) == 3
    assert [m.message.type for m in sink.captured] == [
        EventType.ARMED,
        EventType.TAKEOFF,
        EventType.LANDED,
    ]


def test_event_bus_to_in_memory_sink_preserves_severity_filter() -> None:
    """The wiring goes through subscribe_all (no filter) — all events
    captured regardless of severity."""
    bus = EventBus()
    sink = InMemorySink()
    _wire_bus_to_sink(bus, sink)

    bus.publish(_ev(severity=EventSeverity.DEBUG))
    bus.publish(_ev(severity=EventSeverity.CRITICAL))

    assert len(sink.captured) == 2
    severities = [m.message.severity for m in sink.captured]
    assert EventSeverity.DEBUG in severities
    assert EventSeverity.CRITICAL in severities


# ---------------------------------------------------------------------------
# Full path: EventBus → MCAPFileSink → file → replay → decode
# ---------------------------------------------------------------------------


def test_event_bus_to_mcap_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "run.mcap"
    bus = EventBus()

    with MCAPFileSink(p) as sink:
        _wire_bus_to_sink(bus, sink)
        bus.publish(_ev(type_=EventType.ARMED, source="hal.adapter"))
        bus.publish(_ev(type_=EventType.MISSION_START, source="mission.fsm"))
        bus.publish(
            _ev(
                type_=EventType.SAFETY_VIOLATION,
                severity=EventSeverity.WARN,
                source="actuators.sink",
                payload={"reason": "max_tilt_exceeded"},
            )
        )

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 3
    decoded_events = [decode_message(m) for m in msgs]
    assert all(isinstance(ev, Event) for ev in decoded_events)
    assert [ev.type for ev in decoded_events] == [
        EventType.ARMED,
        EventType.MISSION_START,
        EventType.SAFETY_VIOLATION,
    ]
    # Sequences are assigned monotonically by the bus and survive
    # round-trip.
    assert [ev.sequence for ev in decoded_events] == [0, 1, 2]
    # Payload preserved on the safety violation.
    assert decoded_events[2].payload["reason"] == "max_tilt_exceeded"


def test_event_bus_to_mcap_replay_equals_original_published_sequence(
    tmp_path: Path,
) -> None:
    """The decoded stream equals the published stream (modulo bus-assigned
    sequence). Replay is honest about what flowed through the bus."""
    p = tmp_path / "run.mcap"
    bus = EventBus()
    originals: list[Event] = []
    captured_via_callback: list[Event] = []
    bus.subscribe_all(captured_via_callback.append)

    with MCAPFileSink(p) as sink:
        _wire_bus_to_sink(bus, sink)
        for i in range(5):
            originals.append(bus.publish(_ev(type_=EventType.WAYPOINT_REACHED, source=f"wp.{i}")))

    with MCAPReplayReader(p) as reader:
        decoded = [decode_message(m) for m in reader.iter_messages()]

    assert len(decoded) == 5
    assert decoded == originals
    assert decoded == captured_via_callback


def test_event_bus_to_mcap_round_trip_is_byte_deterministic(
    tmp_path: Path,
) -> None:
    """Two identical bus run sequences produce byte-identical MCAP files
    (T4 review requirement, end-to-end)."""

    def run(p: Path) -> None:
        bus = EventBus()
        with MCAPFileSink(p) as sink:
            _wire_bus_to_sink(bus, sink)
            for i in range(4):
                bus.publish(_ev(type_=EventType.WAYPOINT_REACHED, source=f"wp.{i}"))

    a = tmp_path / "a.mcap"
    b = tmp_path / "b.mcap"
    run(a)
    run(b)
    assert a.read_bytes() == b.read_bytes()
