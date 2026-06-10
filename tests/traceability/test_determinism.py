"""Determinism tests para `build_behavior_trace` end-to-end."""

from __future__ import annotations

from pathlib import Path

from project_ghost.events import EventType
from project_ghost.state import FlightMode, MissionMode
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    MCAPFileSink,
    MCAPReplayReader,
    channel_for_sensor,
)
from project_ghost.traceability import (
    build_behavior_trace,
    encode_trace_to_bytes,
)

from .conftest import (
    make_event,
    make_imu_sample,
    make_vehicle_state,
    write_actuator_channel,
)


def _write_mixed_mcap(path: Path) -> None:
    with MCAPFileSink(path) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0, type_=EventType.ARMED))
        sink.publish(
            CHANNEL_STATE_NAV,
            200,
            make_vehicle_state(flight_mode=FlightMode.OFFBOARD),
        )
        sink.publish(channel_for_sensor("imu0"), 300, make_imu_sample(seq=0))
        sink.publish(channel_for_sensor("imu0"), 400, make_imu_sample(seq=1))
        write_actuator_channel(sink, 500)
        sink.publish(
            CHANNEL_STATE_NAV,
            600,
            make_vehicle_state(mission_mode=MissionMode.NAVIGATE),
        )
        sink.publish(CHANNEL_EVENTS, 700, make_event(sequence=1, type_=EventType.TAKEOFF))
        sink.publish(
            CHANNEL_EVENTS,
            800,
            make_event(sequence=2, type_=EventType.SAFETY_VIOLATION),
        )


# ---------------------------------------------------------------------------
# Trace equality across repeated invocations
# ---------------------------------------------------------------------------


def test_same_mcap_produces_identical_trace_object(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)

    traces = []
    for _ in range(3):
        with MCAPReplayReader(mcap) as reader:
            traces.append(build_behavior_trace(reader=reader, event_id=2, window_ns=10**9))

    assert traces[0] == traces[1] == traces[2]


def test_same_mcap_produces_byte_identical_report_bytes(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)

    def trace_bytes() -> bytes:
        with MCAPReplayReader(mcap) as r:
            t = build_behavior_trace(reader=r, event_id=2, window_ns=10**9)
        return encode_trace_to_bytes(t)

    a = trace_bytes()
    b = trace_bytes()
    c = trace_bytes()
    assert a == b == c


# ---------------------------------------------------------------------------
# Different inputs => different traces
# ---------------------------------------------------------------------------


def test_different_event_id_produces_different_trace(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)

    with MCAPReplayReader(mcap) as r:
        t_e1 = build_behavior_trace(reader=r, event_id=1, window_ns=10**9)
    with MCAPReplayReader(mcap) as r:
        t_e2 = build_behavior_trace(reader=r, event_id=2, window_ns=10**9)

    assert t_e1.event_id != t_e2.event_id
    assert t_e1.event_type == "takeoff"
    assert t_e2.event_type == "safety_violation"
    assert encode_trace_to_bytes(t_e1) != encode_trace_to_bytes(t_e2)


def test_different_window_produces_different_trace(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)

    with MCAPReplayReader(mcap) as r:
        small = build_behavior_trace(reader=r, event_id=2, window_ns=200)
    with MCAPReplayReader(mcap) as r:
        large = build_behavior_trace(reader=r, event_id=2, window_ns=10**9)

    assert small.window_start_ns != large.window_start_ns
    assert len(small.preceding_events) <= len(large.preceding_events)
    assert len(small.preceding_sensor_samples) <= len(large.preceding_sensor_samples)


# ---------------------------------------------------------------------------
# Cross-replay determinism: independent file path, same content
# ---------------------------------------------------------------------------


def test_two_identical_mcaps_produce_identical_traces(tmp_path: Path) -> None:
    mcap_a = tmp_path / "a.mcap"
    mcap_b = tmp_path / "b.mcap"
    _write_mixed_mcap(mcap_a)
    _write_mixed_mcap(mcap_b)

    with MCAPReplayReader(mcap_a) as r:
        t_a = build_behavior_trace(reader=r, event_id=2, window_ns=10**9)
    with MCAPReplayReader(mcap_b) as r:
        t_b = build_behavior_trace(reader=r, event_id=2, window_ns=10**9)

    assert encode_trace_to_bytes(t_a) == encode_trace_to_bytes(t_b)
