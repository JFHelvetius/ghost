"""Tests de `telemetry.replay.MCAPReplayReader` + `decode_message`.

Cubre apertura, iteración, time-range, conteo, decodificación a tipos,
y round-trip end-to-end (encode -> file -> read -> decode -> compare).
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.events import Event, EventSeverity, EventType
from project_ghost.hal.messages import (
    GroundTruth,
    IMUPayload,
    SensorHealth,
    SensorMeta,
    SensorSample,
)
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    MissionMode,
    MissionStatus,
    SensorHealthMap,
    VehicleState,
    vehicle_state_from_ground_truth,
)
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    MCAPFileSink,
    MCAPReplayReader,
    ReplayMessage,
    channel_for_sensor,
    decode_message,
    supported_schemas,
)

_IDENTITY_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _event(seq: int = 0) -> Event:
    return Event(
        type=EventType.MISSION_START,
        severity=EventSeverity.INFO,
        source="mission.fsm",
        stamp_sim_ns=seq * 100,
        stamp_wall_ns=seq * 100,
        sequence=seq,
        payload=MappingProxyType({"idx": seq}),
        correlation_id="run-1",
    )


def _imu_sample(seq: int = 0) -> SensorSample[IMUPayload]:
    return SensorSample[IMUPayload](
        sensor_id="imu0",
        seq=seq,
        stamp_sensor_ns=seq * 100,
        stamp_sim_ns=seq * 100,
        stamp_wall_ns=seq * 100,
        health=SensorHealth.OK,
        payload=IMUPayload(
            accel_mps2=np.array([0.1, 0.2, 9.81], dtype=np.float64),
            gyro_rps=np.array([0.0, 0.0, 0.01], dtype=np.float64),
            temperature_c=22.5,
        ),
        meta=SensorMeta(
            frame_id="body",
            calibration_id="cal-01",
            extensions=MappingProxyType({}),
        ),
    )


def _vehicle_state(stamp: int = 0) -> VehicleState:
    gt = GroundTruth(
        stamp_sim_ns=stamp,
        position_enu_m=np.array([1.0, 2.0, 3.0], dtype=np.float64),
        orientation_q=_IDENTITY_Q.copy(),
        linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
        angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
    )
    return vehicle_state_from_ground_truth(
        gt=gt,
        sensors_health=SensorHealthMap(
            by_id=MappingProxyType({"imu0": SensorHealth.OK})
        ),
        flight=FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=12.0,
            battery_pct=0.9,
            error_flags=0,
        ),
        mission=MissionStatus(
            mode=MissionMode.IDLE,
            current_goal=None,
            progress=0.0,
            started_sim_ns=None,
        ),
        stamp_wall_ns=stamp,
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_supported_schemas_lists_event_and_vehicle_state() -> None:
    schemas = supported_schemas()
    assert "project_ghost.events.types.Event" in schemas
    assert "project_ghost.state.messages.VehicleState" in schemas


def test_supported_schemas_lists_all_sensor_sample_variants() -> None:
    schemas = supported_schemas()
    for payload_name in (
        "IMUPayload",
        "RGBImagePayload",
        "DepthImagePayload",
        "GpsPayload",
        "AltimeterPayload",
    ):
        assert (
            f"project_ghost.hal.messages.sensors.SensorSample.{payload_name}"
            in schemas
        )


# ---------------------------------------------------------------------------
# MCAPReplayReader basic
# ---------------------------------------------------------------------------


def test_reader_requires_context_manager(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())

    reader = MCAPReplayReader(p)
    with pytest.raises(RuntimeError, match="context manager"):
        list(reader.iter_messages())
    with pytest.raises(RuntimeError, match="abrirse"):
        reader.message_count()


def test_reader_yields_messages_in_log_time_order(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        for i in range(5):
            sink.publish(CHANNEL_EVENTS, i * 100, _event(seq=i))

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 5
    assert [m.log_time_sim_ns for m in msgs] == [0, 100, 200, 300, 400]
    assert all(m.channel == CHANNEL_EVENTS for m in msgs)


def test_reader_message_count_matches_published(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        for i in range(7):
            sink.publish(CHANNEL_EVENTS, i * 100, _event(seq=i))

    with MCAPReplayReader(p) as reader:
        assert reader.message_count() == 7


def test_reader_time_range_anchor(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_EVENTS, 100, _event(seq=0))
        sink.publish(CHANNEL_EVENTS, 999, _event(seq=1))

    with MCAPReplayReader(p) as reader:
        rng = reader.time_range_sim_ns()
    assert rng == (100, 999)


def test_reader_time_range_none_for_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p):
        pass

    with MCAPReplayReader(p) as reader:
        assert reader.time_range_sim_ns() is None
        assert reader.message_count() == 0


def test_reader_replay_message_is_frozen(tmp_path: Path) -> None:
    from dataclasses import FrozenInstanceError

    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())

    with MCAPReplayReader(p) as reader:
        msg = next(iter(reader.iter_messages()))
    with pytest.raises(FrozenInstanceError):
        msg.channel = "/y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Round-trip — publish, file close, read, decode, compare
# ---------------------------------------------------------------------------


def test_event_round_trip_via_mcap(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    original = _event(seq=3)
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_EVENTS, original.stamp_sim_ns, original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, Event)
    assert decoded == original


def test_vehicle_state_round_trip_via_mcap(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    original = _vehicle_state(stamp=1000)
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_STATE_NAV, original.stamp_sim_ns, original)

    with MCAPReplayReader(p) as reader:
        decoded = decode_message(next(iter(reader.iter_messages())))

    assert isinstance(decoded, VehicleState)
    assert decoded.stamp_sim_ns == original.stamp_sim_ns
    assert decoded.flight.flight_mode == FlightMode.OFFBOARD
    assert decoded.nav.covariance_15x15 is None  # GT path: truth, not belief
    np.testing.assert_array_equal(
        decoded.nav.pose.position_enu_m, original.nav.pose.position_enu_m
    )


def test_sensor_sample_imu_round_trip_via_mcap(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    original = _imu_sample(seq=7)
    with MCAPFileSink(p) as sink:
        sink.publish(channel_for_sensor("imu0"), original.stamp_sim_ns, original)

    with MCAPReplayReader(p) as reader:
        decoded = decode_message(next(iter(reader.iter_messages())))

    assert isinstance(decoded, SensorSample)
    assert isinstance(decoded.payload, IMUPayload)
    assert decoded.sensor_id == original.sensor_id
    assert decoded.seq == 7
    assert decoded.health == SensorHealth.OK
    np.testing.assert_array_equal(
        decoded.payload.accel_mps2, original.payload.accel_mps2
    )
    np.testing.assert_array_equal(
        decoded.payload.gyro_rps, original.payload.gyro_rps
    )
    assert decoded.payload.temperature_c == 22.5


# ---------------------------------------------------------------------------
# Determinism on read — two identical files yield identical message streams
# ---------------------------------------------------------------------------


def test_two_identical_writes_yield_identical_message_streams(
    tmp_path: Path,
) -> None:
    def write(p: Path) -> None:
        with MCAPFileSink(p) as sink:
            for i in range(3):
                sink.publish(CHANNEL_EVENTS, i * 100, _event(seq=i))

    p1 = tmp_path / "a.mcap"
    p2 = tmp_path / "b.mcap"
    write(p1)
    write(p2)

    def stream(p: Path) -> list[tuple[str, int, str]]:
        with MCAPReplayReader(p) as reader:
            return [
                (m.channel, m.log_time_sim_ns, str(sorted(m.payload_dict.items())))
                for m in reader.iter_messages()
            ]

    assert stream(p1) == stream(p2)


# ---------------------------------------------------------------------------
# decode_message — unknown schema raises loudly
# ---------------------------------------------------------------------------


def test_decode_message_raises_for_unknown_schema() -> None:
    msg = ReplayMessage(
        channel="/custom",
        schema_name="not.a.known.schema",
        log_time_sim_ns=0,
        payload_dict={},
    )
    with pytest.raises(KeyError, match="desconocido"):
        decode_message(msg)


def test_decode_message_runs_post_init_validation(tmp_path: Path) -> None:
    """Hand-craft a ReplayMessage with corrupt payload; decode must fail
    loud rather than producing an invalid object."""
    msg = ReplayMessage(
        channel=CHANNEL_EVENTS,
        schema_name="project_ghost.events.types.Event",
        log_time_sim_ns=0,
        payload_dict={
            "type": "mission_start",
            "severity": 20,
            "source": "",  # invalid — Event requires non-empty source
            "stamp_sim_ns": 0,
            "stamp_wall_ns": 0,
            "sequence": 0,
            "payload": {},
            "correlation_id": None,
            "schema_version": 1,
        },
    )
    with pytest.raises(ValueError, match="source"):
        decode_message(msg)
