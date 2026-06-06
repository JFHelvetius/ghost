"""Shared fixtures for analysis tests.

Helpers to synthesize VehicleState, GroundTruth, MCAP files with mixed
message types, and final-state JSON files. All deterministic — no
random, no clock.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import numpy as np

from project_ghost.events import Event, EventSeverity, EventType
from project_ghost.hal.messages import (
    DirectMotorCommand,
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
    MCAPFileSink,
    to_json_safe,
)

_IDENTITY_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
_ACTUATOR_CHANNEL: str = "/actuators/main"


def make_event(
    *,
    type_: EventType = EventType.MISSION_START,
    severity: EventSeverity = EventSeverity.INFO,
    source: str = "test.source",
    stamp_sim_ns: int = 0,
) -> Event:
    return Event(
        type=type_,
        severity=severity,
        source=source,
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=stamp_sim_ns,
        sequence=0,
        payload=MappingProxyType({}),
        correlation_id=None,
    )


def make_imu_sample(
    *,
    seq: int = 0,
    stamp_sim_ns: int = 0,
    sensor_id: str = "imu0",
) -> SensorSample[IMUPayload]:
    return SensorSample[IMUPayload](
        sensor_id=sensor_id,
        seq=seq,
        stamp_sensor_ns=stamp_sim_ns,
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=stamp_sim_ns,
        health=SensorHealth.OK,
        payload=IMUPayload(
            accel_mps2=np.zeros(3, dtype=np.float64),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        ),
        meta=SensorMeta(
            frame_id="body",
            calibration_id=None,
            extensions=MappingProxyType({}),
        ),
    )


def make_actuator_command() -> DirectMotorCommand:
    return DirectMotorCommand(
        throttle=np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64)
    )


def make_vehicle_state(
    *,
    stamp_sim_ns: int = 0,
    flight_mode: FlightMode = FlightMode.OFFBOARD,
    mission_mode: MissionMode = MissionMode.IDLE,
    sensor_health: dict[str, SensorHealth] | None = None,
) -> VehicleState:
    gt = GroundTruth(
        stamp_sim_ns=stamp_sim_ns,
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_IDENTITY_Q.copy(),
        linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
        angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
    )
    return vehicle_state_from_ground_truth(
        gt=gt,
        sensors_health=SensorHealthMap(
            by_id=MappingProxyType(sensor_health or {"imu0": SensorHealth.OK})
        ),
        flight=FlightStatus(
            armed=True,
            flight_mode=flight_mode,
            battery_v=12.0,
            battery_pct=0.9,
            error_flags=0,
        ),
        mission=MissionStatus(
            mode=mission_mode,
            current_goal=None,
            progress=0.0,
            started_sim_ns=None,
        ),
        stamp_wall_ns=stamp_sim_ns,
    )


def write_state_json(state: VehicleState, path: Path) -> None:
    """Serialize ``state`` to ``path`` in the canonical encoding."""
    data = to_json_safe(state)
    path.write_text(
        json.dumps(data, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def write_actuator_channel(sink: MCAPFileSink, stamp_ns: int) -> None:
    """Publish a DirectMotorCommand on an /actuators/ channel.

    Until publishers exist for actuator commands in the rest of the
    codebase, tests synthesize this channel manually so we can verify
    the analyzer counts what it claims to count.
    """
    sink.publish(_ACTUATOR_CHANNEL, stamp_ns, make_actuator_command())


__all__ = [
    "make_actuator_command",
    "make_event",
    "make_imu_sample",
    "make_vehicle_state",
    "write_actuator_channel",
    "write_state_json",
]
