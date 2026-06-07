"""Tests del `build_behavior_trace` — cubre los 15 criterios del spec T6."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    EventNotFoundError,
    build_behavior_trace,
)

from .conftest import (
    make_event,
    make_imu_sample,
    make_vehicle_state,
    write_actuator_channel,
)

_5_SECONDS_NS: int = 5 * 1_000_000_000


# ---------------------------------------------------------------------------
# Criterio 1: empty replay
# ---------------------------------------------------------------------------


def test_empty_replay_raises_event_not_found(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass
    with MCAPReplayReader(mcap) as reader:
        with pytest.raises(EventNotFoundError):
            build_behavior_trace(reader=reader, event_id=0, window_ns=_5_SECONDS_NS)


# ---------------------------------------------------------------------------
# Criterio 2: missing event
# ---------------------------------------------------------------------------


def test_missing_event_id_raises(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(sequence=0))
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=1))

    with MCAPReplayReader(mcap) as reader:
        with pytest.raises(EventNotFoundError, match="42"):
            build_behavior_trace(reader=reader, event_id=42, window_ns=_5_SECONDS_NS)


def test_missing_event_does_not_match_partial_sequence(tmp_path: Path) -> None:
    """sequence==1 must not match a request for event_id==10."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(sequence=1))

    with MCAPReplayReader(mcap) as reader:
        with pytest.raises(EventNotFoundError):
            build_behavior_trace(reader=reader, event_id=10, window_ns=_5_SECONDS_NS)


# ---------------------------------------------------------------------------
# Criterio 3: single preceding event
# ---------------------------------------------------------------------------


def test_single_preceding_event_captured(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0, type_=EventType.ARMED))
        sink.publish(
            CHANNEL_EVENTS, 200, make_event(sequence=1, type_=EventType.TAKEOFF)
        )

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=1, window_ns=_5_SECONDS_NS)

    assert trace.event_id == 1
    assert trace.event_type == "takeoff"
    assert len(trace.preceding_events) == 1
    assert trace.preceding_events[0].summary["type"] == "armed"
    assert trace.preceding_events[0].summary["sequence"] == 0


# ---------------------------------------------------------------------------
# Criterio 4: multiple preceding events
# ---------------------------------------------------------------------------


def test_multiple_preceding_events_in_order(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        for i, t in enumerate(
            [
                EventType.ARMED,
                EventType.TAKEOFF,
                EventType.WAYPOINT_REACHED,
                EventType.LANDED,  # target
            ]
        ):
            sink.publish(CHANNEL_EVENTS, i * 100, make_event(sequence=i, type_=t))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=3, window_ns=_5_SECONDS_NS)

    assert trace.event_type == "landed"
    assert len(trace.preceding_events) == 3
    # Order by log_time ascending
    assert [m.log_time_sim_ns for m in trace.preceding_events] == [0, 100, 200]
    assert [m.summary["type"] for m in trace.preceding_events] == [
        "armed",
        "takeoff",
        "waypoint_reached",
    ]


# ---------------------------------------------------------------------------
# Criterio 5: actuator capture
# ---------------------------------------------------------------------------


def test_actuator_commands_captured(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        write_actuator_channel(sink, 100)
        write_actuator_channel(sink, 200)
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=0, type_=EventType.ARMED))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=0, window_ns=_5_SECONDS_NS)

    assert len(trace.preceding_actuator_commands) == 2
    assert [m.log_time_sim_ns for m in trace.preceding_actuator_commands] == [100, 200]


# ---------------------------------------------------------------------------
# Criterio 6: sensor capture
# ---------------------------------------------------------------------------


def test_sensor_samples_captured(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(channel_for_sensor("imu0"), 100, make_imu_sample(seq=0))
        sink.publish(channel_for_sensor("imu0"), 200, make_imu_sample(seq=1))
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=5, type_=EventType.ARMED))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=5, window_ns=_5_SECONDS_NS)

    assert len(trace.preceding_sensor_samples) == 2
    assert [m.summary["seq"] for m in trace.preceding_sensor_samples] == [0, 1]


# ---------------------------------------------------------------------------
# Criterio 7: state change capture
# ---------------------------------------------------------------------------


def test_state_changes_captured_on_mode_transition(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(
            CHANNEL_STATE_NAV,
            100,
            make_vehicle_state(flight_mode=FlightMode.OFFBOARD),
        )
        sink.publish(
            CHANNEL_STATE_NAV,
            200,
            make_vehicle_state(mission_mode=MissionMode.NAVIGATE),
        )
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=7, type_=EventType.ARMED))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=7, window_ns=_5_SECONDS_NS)

    assert len(trace.preceding_state_changes) == 2  # initial + mission change
    assert trace.preceding_state_changes[0].summary["mission_mode"] == "idle"
    assert trace.preceding_state_changes[1].summary["mission_mode"] == "navigate"


def test_state_without_mode_change_not_captured_as_change(tmp_path: Path) -> None:
    """Three identical VehicleStates → only the first counts as a change."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        for i in range(3):
            sink.publish(
                CHANNEL_STATE_NAV,
                100 + i * 50,
                make_vehicle_state(
                    flight_mode=FlightMode.OFFBOARD,
                    mission_mode=MissionMode.IDLE,
                ),
            )
        sink.publish(CHANNEL_EVENTS, 500, make_event(sequence=0))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=0, window_ns=_5_SECONDS_NS)

    assert len(trace.preceding_state_changes) == 1


# ---------------------------------------------------------------------------
# Criterio 8: stable ordering
# ---------------------------------------------------------------------------


def test_preceding_lists_ordered_by_log_time_ascending(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        # Mixed channels interleaved
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0, type_=EventType.ARMED))
        sink.publish(channel_for_sensor("imu0"), 150, make_imu_sample(seq=0))
        sink.publish(
            CHANNEL_EVENTS, 200, make_event(sequence=1, type_=EventType.TAKEOFF)
        )
        sink.publish(channel_for_sensor("imu0"), 250, make_imu_sample(seq=1))
        write_actuator_channel(sink, 280)
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=2, type_=EventType.LANDED))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=2, window_ns=_5_SECONDS_NS)

    # Each list independently sorted
    for lst in (
        trace.preceding_events,
        trace.preceding_sensor_samples,
        trace.preceding_actuator_commands,
    ):
        times = [m.log_time_sim_ns for m in lst]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Criterio 9: deterministic output
# ---------------------------------------------------------------------------


def test_same_inputs_produce_same_trace(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0))
        sink.publish(channel_for_sensor("imu0"), 200, make_imu_sample())
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=1))

    traces = []
    for _ in range(3):
        with MCAPReplayReader(mcap) as reader:
            traces.append(
                build_behavior_trace(reader=reader, event_id=1, window_ns=_5_SECONDS_NS)
            )

    assert traces[0] == traces[1] == traces[2]


# ---------------------------------------------------------------------------
# Criterio 12: large replay
# ---------------------------------------------------------------------------


def test_large_replay_completes_correctly(tmp_path: Path) -> None:
    """500 messages preceding a target event; verify counts and ordering."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        for i in range(250):
            sink.publish(
                channel_for_sensor("imu0"),
                i * 10,
                make_imu_sample(seq=i),
            )
        for i in range(250):
            sink.publish(
                CHANNEL_EVENTS,
                2500 + i * 10,
                make_event(sequence=i),
            )
        # Target event at the very end
        sink.publish(
            CHANNEL_EVENTS,
            5500,
            make_event(sequence=999, type_=EventType.SAFETY_VIOLATION),
        )

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(
            reader=reader, event_id=999, window_ns=10 * 1_000_000_000
        )

    assert trace.event_type == "safety_violation"
    assert len(trace.preceding_events) == 250
    assert len(trace.preceding_sensor_samples) == 250


# ---------------------------------------------------------------------------
# Criterio 13: boundary timestamps
# ---------------------------------------------------------------------------


def test_window_boundary_inclusive_at_start_exclusive_at_end(tmp_path: Path) -> None:
    """Window is [event_time - window_ns, event_time). Message at
    exactly window_start is INCLUDED; message at exactly event_time is
    NOT included (and is the target event itself anyway)."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        # event_time = 1000, window_ns = 500 => window = [500, 1000)
        sink.publish(CHANNEL_EVENTS, 499, make_event(sequence=0))  # outside
        sink.publish(CHANNEL_EVENTS, 500, make_event(sequence=1))  # at start
        sink.publish(CHANNEL_EVENTS, 999, make_event(sequence=2))  # inside
        sink.publish(CHANNEL_EVENTS, 1000, make_event(sequence=42))  # target

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=42, window_ns=500)

    captured_sequences = [m.summary["sequence"] for m in trace.preceding_events]
    assert captured_sequences == [1, 2]
    assert trace.window_start_ns == 500
    assert trace.window_end_ns == 1000


# ---------------------------------------------------------------------------
# Criterio 14: zero window
# ---------------------------------------------------------------------------


def test_zero_window_yields_empty_preceding_lists(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0))
        sink.publish(channel_for_sensor("imu0"), 200, make_imu_sample())
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=1))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=1, window_ns=0)

    assert trace.preceding_events == ()
    assert trace.preceding_sensor_samples == ()
    assert trace.preceding_actuator_commands == ()
    assert trace.preceding_state_changes == ()
    # Window collapses to [300, 300) — empty by construction.
    assert trace.window_start_ns == 300
    assert trace.window_end_ns == 300


# ---------------------------------------------------------------------------
# Criterio 15: custom window
# ---------------------------------------------------------------------------


def test_custom_window_filters_correctly(tmp_path: Path) -> None:
    """200-ns window before event at t=1000: messages at t<800 dropped."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 700, make_event(sequence=0))  # outside (t<800)
        sink.publish(CHANNEL_EVENTS, 800, make_event(sequence=1))  # at boundary
        sink.publish(CHANNEL_EVENTS, 900, make_event(sequence=2))  # inside
        sink.publish(CHANNEL_EVENTS, 1000, make_event(sequence=99))  # target

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=99, window_ns=200)

    sequences = [m.summary["sequence"] for m in trace.preceding_events]
    assert sequences == [1, 2]


# ---------------------------------------------------------------------------
# Additional: window_ns negative rejected
# ---------------------------------------------------------------------------


def test_negative_window_ns_raises_value_error(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0))

    with MCAPReplayReader(mcap) as reader:
        with pytest.raises(ValueError, match="window_ns"):
            build_behavior_trace(reader=reader, event_id=0, window_ns=-1)


# ---------------------------------------------------------------------------
# Additional: unrelated channels ignored (per ADR-0014)
# ---------------------------------------------------------------------------


def test_unknown_channel_messages_silently_ignored(tmp_path: Path) -> None:
    """Per ADR-0014: channels not in {/events, /state/nav, /sensors/*,
    /actuators/*} are silently ignored. This test would need to write
    such a channel; since MCAPFileSink validates channels start with
    `/`, we use a non-categorized prefix `/misc/...`."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish("/misc/diagnostic", 100, make_event(sequence=0))
        sink.publish(CHANNEL_EVENTS, 200, make_event(sequence=1))

    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=1, window_ns=_5_SECONDS_NS)

    # /misc not captured as event (channel doesn't match CHANNEL_EVENTS)
    assert len(trace.preceding_events) == 0


# ---------------------------------------------------------------------------
# Additional: state change predecessor tracking spans entire timeline
# ---------------------------------------------------------------------------


def test_state_change_at_window_edge_detected_with_outside_predecessor(
    tmp_path: Path,
) -> None:
    """State change predecessor tracking is global (entire pre-event
    timeline), not local to the window. A state change at the start of
    the window is detected even if its predecessor was outside."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        # OFFBOARD/IDLE outside window
        sink.publish(
            CHANNEL_STATE_NAV,
            100,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD,
                mission_mode=MissionMode.IDLE,
            ),
        )
        # OFFBOARD/NAVIGATE inside window — change detected
        sink.publish(
            CHANNEL_STATE_NAV,
            900,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD,
                mission_mode=MissionMode.NAVIGATE,
            ),
        )
        sink.publish(CHANNEL_EVENTS, 1000, make_event(sequence=0))

    # Window = [800, 1000) — predecessor at t=100 is outside
    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(reader=reader, event_id=0, window_ns=200)

    assert len(trace.preceding_state_changes) == 1
    assert trace.preceding_state_changes[0].log_time_sim_ns == 900
    assert trace.preceding_state_changes[0].summary["mission_mode"] == "navigate"
