"""Tests del `build_run_summary`.

Cubre los criterios del spec T5:

1. Empty replay
2. Single event
3. Multiple event types
4. Multiple sensor types
5. Multiple actuator types
6. State hash stable
9. Replay order preserved (first/last timestamps)
14. Different replay => different summary
"""

from __future__ import annotations

from pathlib import Path

from project_ghost.analysis import build_run_summary
from project_ghost.events import EventType
from project_ghost.hal.messages import SensorHealth
from project_ghost.state import FlightMode, MissionMode
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    MCAPFileSink,
    MCAPReplayReader,
    channel_for_sensor,
)

from .conftest import (
    make_event,
    make_imu_sample,
    make_vehicle_state,
    write_actuator_channel,
)

# ---------------------------------------------------------------------------
# Test 1: empty replay
# ---------------------------------------------------------------------------


def test_empty_replay_yields_zero_counts(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass
    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="empty-run", reader=reader, final_state=state)

    assert summary.event_count == 0
    assert summary.sensor_sample_count == 0
    assert summary.actuator_command_count == 0
    assert summary.state_transition_count == 0
    assert summary.event_type_counts == {}
    assert summary.sensor_type_counts == {}
    assert summary.actuator_type_counts == {}


def test_empty_replay_has_none_timestamps(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass
    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="empty", reader=reader, final_state=state)

    assert summary.first_timestamp_ns is None
    assert summary.last_timestamp_ns is None
    assert summary.duration_ns is None


def test_empty_replay_still_hashes_final_state(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass
    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="empty", reader=reader, final_state=state)

    assert summary.final_state_hash
    # SHA-256 hex is 64 chars
    assert len(summary.final_state_hash) == 64


# ---------------------------------------------------------------------------
# Test 2: single event
# ---------------------------------------------------------------------------


def test_single_event_counts_one_event(tmp_path: Path) -> None:
    mcap = tmp_path / "single.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(type_=EventType.ARMED))

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="single", reader=reader, final_state=state)

    assert summary.event_count == 1
    assert summary.event_type_counts == {"armed": 1}
    assert summary.first_timestamp_ns == 100
    assert summary.last_timestamp_ns == 100
    assert summary.duration_ns == 0


# ---------------------------------------------------------------------------
# Test 3: multiple event types
# ---------------------------------------------------------------------------


def test_multiple_event_types_are_counted_independently(tmp_path: Path) -> None:
    mcap = tmp_path / "events.mcap"
    types = [
        EventType.ARMED,
        EventType.TAKEOFF,
        EventType.TAKEOFF,
        EventType.LANDED,
        EventType.DISARMED,
    ]
    with MCAPFileSink(mcap) as sink:
        for i, t in enumerate(types):
            sink.publish(CHANNEL_EVENTS, i * 100, make_event(type_=t))

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="multi-events", reader=reader, final_state=state)

    assert summary.event_count == 5
    assert summary.event_type_counts == {
        "armed": 1,
        "disarmed": 1,
        "landed": 1,
        "takeoff": 2,
    }


def test_event_type_counts_keys_are_sorted_alphabetically(tmp_path: Path) -> None:
    mcap = tmp_path / "events.mcap"
    with MCAPFileSink(mcap) as sink:
        # Publish in NON-alphabetical type order
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.TAKEOFF))
        sink.publish(CHANNEL_EVENTS, 1, make_event(type_=EventType.ARMED))
        sink.publish(CHANNEL_EVENTS, 2, make_event(type_=EventType.LANDED))

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert list(summary.event_type_counts.keys()) == ["armed", "landed", "takeoff"]


# ---------------------------------------------------------------------------
# Test 4: multiple sensor types
# ---------------------------------------------------------------------------


def test_sensor_samples_counted_by_payload_type(tmp_path: Path) -> None:
    mcap = tmp_path / "sensors.mcap"
    with MCAPFileSink(mcap) as sink:
        for i in range(3):
            sink.publish(channel_for_sensor("imu0"), i * 100, make_imu_sample(seq=i))

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="sensors", reader=reader, final_state=state)

    assert summary.sensor_sample_count == 3
    assert summary.sensor_type_counts == {"IMUPayload": 3}


# ---------------------------------------------------------------------------
# Test 5: multiple actuator types
# ---------------------------------------------------------------------------


def test_actuator_commands_counted_from_actuator_channel(tmp_path: Path) -> None:
    """Until real publishers exist, conftest synthesizes /actuators/ traffic.
    The analyzer counts whatever appears on any /actuators/* channel."""
    mcap = tmp_path / "actuators.mcap"
    with MCAPFileSink(mcap) as sink:
        for i in range(4):
            write_actuator_channel(sink, i * 100)

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="actuators", reader=reader, final_state=state)

    assert summary.actuator_command_count == 4
    assert summary.actuator_type_counts == {"DirectMotorCommand": 4}


# ---------------------------------------------------------------------------
# Healthy / unhealthy sensor counts come from FINAL state
# ---------------------------------------------------------------------------


def test_healthy_sensor_count_from_final_state(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state = make_vehicle_state(
        sensor_health={
            "imu0": SensorHealth.OK,
            "cam_front": SensorHealth.OK,
            "alt0": SensorHealth.OK,
        }
    )

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.healthy_sensor_count == 3
    assert summary.unhealthy_sensor_count == 0


def test_unhealthy_sensor_count_from_final_state(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state = make_vehicle_state(
        sensor_health={
            "imu0": SensorHealth.OK,
            "cam_front": SensorHealth.FAULTY,
            "alt0": SensorHealth.OFFLINE,
        }
    )

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.healthy_sensor_count == 1
    assert summary.unhealthy_sensor_count == 2


# ---------------------------------------------------------------------------
# State transitions — count of (flight_mode, mission_mode) changes
# ---------------------------------------------------------------------------


def test_state_transition_counted_once_for_single_vehicle_state(
    tmp_path: Path,
) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(
            CHANNEL_STATE_NAV,
            0,
            make_vehicle_state(flight_mode=FlightMode.OFFBOARD),
        )

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.state_transition_count == 1


def test_state_transition_increments_only_on_mode_change(
    tmp_path: Path,
) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        # Three states, all with same modes => one transition (the first)
        for i in range(3):
            sink.publish(
                CHANNEL_STATE_NAV,
                i * 100,
                make_vehicle_state(
                    flight_mode=FlightMode.OFFBOARD,
                    mission_mode=MissionMode.IDLE,
                ),
            )

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.state_transition_count == 1


def test_state_transition_counts_each_mode_change(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    sequence = [
        (FlightMode.OFFBOARD, MissionMode.IDLE),
        (FlightMode.OFFBOARD, MissionMode.NAVIGATE),
        (FlightMode.OFFBOARD, MissionMode.NAVIGATE),
        (FlightMode.LAND, MissionMode.RETURN),
    ]
    with MCAPFileSink(mcap) as sink:
        for i, (fm, mm) in enumerate(sequence):
            sink.publish(
                CHANNEL_STATE_NAV,
                i * 100,
                make_vehicle_state(flight_mode=fm, mission_mode=mm),
            )

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    # transitions: t=0 (initial), t=1 (mission change), t=3 (both change)
    assert summary.state_transition_count == 3


# ---------------------------------------------------------------------------
# Replay order preserved (Test 9 of spec)
# ---------------------------------------------------------------------------


def test_first_and_last_timestamps_track_replay_window(tmp_path: Path) -> None:
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event())
        sink.publish(CHANNEL_EVENTS, 250, make_event())
        sink.publish(CHANNEL_EVENTS, 999, make_event())

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.first_timestamp_ns == 100
    assert summary.last_timestamp_ns == 999
    assert summary.duration_ns == 899


# ---------------------------------------------------------------------------
# Test 14: different replay => different summary
# ---------------------------------------------------------------------------


def test_different_replays_yield_different_summaries(tmp_path: Path) -> None:
    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"

    with MCAPFileSink(a_path) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.ARMED))
    with MCAPFileSink(b_path) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.ARMED))
        sink.publish(CHANNEL_EVENTS, 100, make_event(type_=EventType.TAKEOFF))

    state = make_vehicle_state()

    with MCAPReplayReader(a_path) as r:
        a = build_run_summary(run_id="a", reader=r, final_state=state)
    with MCAPReplayReader(b_path) as r:
        b = build_run_summary(run_id="b", reader=r, final_state=state)

    assert a.event_count == 1
    assert b.event_count == 2
    assert a != b


# ---------------------------------------------------------------------------
# Mixed traffic — sanity integration over all channel types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T6 backward-compatible extension: traceable_events_count
# ---------------------------------------------------------------------------


def test_traceable_events_count_equals_event_count(tmp_path: Path) -> None:
    """Per ADR-0014: every event on /events is a valid trace target,
    so traceable_events_count == event_count."""
    mcap = tmp_path / "x.mcap"
    with MCAPFileSink(mcap) as sink:
        for i in range(7):
            sink.publish(CHANNEL_EVENTS, i * 100, make_event(type_=EventType.ARMED))

    state = make_vehicle_state()
    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.event_count == 7
    assert summary.traceable_events_count == 7


def test_traceable_events_count_zero_on_empty_replay(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state = make_vehicle_state()
    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="x", reader=reader, final_state=state)

    assert summary.traceable_events_count == 0


def test_mixed_traffic_counted_separately_per_channel_type(
    tmp_path: Path,
) -> None:
    mcap = tmp_path / "mixed.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.ARMED))
        sink.publish(CHANNEL_STATE_NAV, 100, make_vehicle_state(flight_mode=FlightMode.OFFBOARD))
        sink.publish(channel_for_sensor("imu0"), 200, make_imu_sample(seq=0))
        sink.publish(channel_for_sensor("imu0"), 300, make_imu_sample(seq=1))
        write_actuator_channel(sink, 400)
        sink.publish(CHANNEL_EVENTS, 500, make_event(type_=EventType.TAKEOFF))

    state = make_vehicle_state()

    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(run_id="mixed", reader=reader, final_state=state)

    assert summary.event_count == 2
    assert summary.sensor_sample_count == 2
    assert summary.actuator_command_count == 1
    assert summary.state_transition_count == 1
    assert summary.first_timestamp_ns == 0
    assert summary.last_timestamp_ns == 500
    assert summary.duration_ns == 500
