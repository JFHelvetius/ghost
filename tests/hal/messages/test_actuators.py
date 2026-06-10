"""Tests de `hal.messages.actuators` (T2.a.2).

Cubre enums, Protocol, los 6 niveles de comando, `CommandAck` con su
invariante de coupling accepted/reason, `SafetyEnvelope` y `ActuatorSpec`.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.hal.messages import (
    ActuatorCommand,
    ActuatorLevel,
    ActuatorSpec,
    AttitudeCommand,
    BodyRateCommand,
    CommandAck,
    DirectMotorCommand,
    PositionCommand,
    RejectReason,
    SafetyEnvelope,
    TrajectoryCommand,
    VelocityCommand,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(**overrides: object) -> SafetyEnvelope:
    defaults: dict[str, object] = {
        "max_tilt_rad": 0.7,
        "max_climb_rate_mps": 5.0,
        "max_horiz_speed_mps": 10.0,
        "max_yaw_rate_rps": 3.0,
        "altitude_min_m": 0.0,
        "altitude_max_m": 100.0,
        "geofence_polygon": None,
        "command_timeout_ns": 500_000_000,
        "require_arm": True,
    }
    defaults.update(overrides)
    return SafetyEnvelope(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_actuator_level_total_ordering() -> None:
    assert ActuatorLevel.DIRECT_MOTOR < ActuatorLevel.BODY_RATE
    assert ActuatorLevel.BODY_RATE < ActuatorLevel.ATTITUDE
    assert ActuatorLevel.ATTITUDE < ActuatorLevel.VELOCITY
    assert ActuatorLevel.VELOCITY < ActuatorLevel.POSITION
    assert ActuatorLevel.POSITION < ActuatorLevel.TRAJECTORY


def test_actuator_level_values_match_spec() -> None:
    assert ActuatorLevel.DIRECT_MOTOR.value == 0
    assert ActuatorLevel.TRAJECTORY.value == 5


def test_reject_reason_catalog_size() -> None:
    assert len(list(RejectReason)) == 7


def test_reject_reason_string_values_are_snake_case() -> None:
    for r in RejectReason:
        assert r.value == r.value.lower()
        assert " " not in r.value


# ---------------------------------------------------------------------------
# ActuatorCommand Protocol
# ---------------------------------------------------------------------------


def test_direct_motor_satisfies_actuator_command_protocol() -> None:
    cmd = DirectMotorCommand(throttle=np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64))
    assert isinstance(cmd, ActuatorCommand)


def test_position_command_satisfies_actuator_command_protocol() -> None:
    cmd = PositionCommand(position_enu_m=np.zeros(3, dtype=np.float64))
    assert isinstance(cmd, ActuatorCommand)


# ---------------------------------------------------------------------------
# DirectMotorCommand
# ---------------------------------------------------------------------------


def test_direct_motor_command_valid_construction() -> None:
    cmd = DirectMotorCommand(
        throttle=np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64),
        stamp_ns=1_000,
    )
    assert cmd.level == ActuatorLevel.DIRECT_MOTOR
    assert cmd.stamp_ns == 1_000
    assert cmd.throttle.shape == (4,)


def test_direct_motor_command_n_rotor_agnostic() -> None:
    """API es N-rotor agnóstico (actuators.md §7)."""
    for n in (1, 4, 6, 8):
        cmd = DirectMotorCommand(throttle=np.zeros(n, dtype=np.float64))
        assert cmd.throttle.shape == (n,)


def test_direct_motor_command_rejects_throttle_below_zero() -> None:
    with pytest.raises(ValueError, match="throttle"):
        DirectMotorCommand(throttle=np.array([0.5, -0.1, 0.5, 0.5], dtype=np.float64))


def test_direct_motor_command_rejects_throttle_above_one() -> None:
    with pytest.raises(ValueError, match="throttle"):
        DirectMotorCommand(throttle=np.array([0.5, 1.01, 0.5, 0.5], dtype=np.float64))


def test_direct_motor_command_rejects_nan_throttle() -> None:
    with pytest.raises(ValueError, match="NaN"):
        DirectMotorCommand(throttle=np.array([0.5, np.nan, 0.5, 0.5], dtype=np.float64))


def test_direct_motor_command_rejects_empty_throttle() -> None:
    with pytest.raises(ValueError, match="al menos un motor"):
        DirectMotorCommand(throttle=np.zeros(0, dtype=np.float64))


def test_direct_motor_command_rejects_wrong_dtype() -> None:
    with pytest.raises(TypeError, match="dtype"):
        DirectMotorCommand(throttle=np.array([0.5, 0.5], dtype=np.float32))


def test_direct_motor_command_level_is_immutable_and_not_in_init() -> None:
    """level no se puede sobrescribir desde el constructor."""
    cmd = DirectMotorCommand(throttle=np.zeros(4, dtype=np.float64))
    with pytest.raises(FrozenInstanceError):
        cmd.level = ActuatorLevel.ATTITUDE  # type: ignore[misc]
    with pytest.raises(TypeError, match="unexpected keyword"):
        DirectMotorCommand(  # type: ignore[call-arg]
            throttle=np.zeros(4, dtype=np.float64),
            level=ActuatorLevel.ATTITUDE,
        )


def test_direct_motor_command_throttle_is_sealed() -> None:
    throttle = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64)
    cmd = DirectMotorCommand(throttle=throttle)
    assert not cmd.throttle.flags.writeable


# ---------------------------------------------------------------------------
# BodyRateCommand
# ---------------------------------------------------------------------------


def test_body_rate_command_valid_construction() -> None:
    cmd = BodyRateCommand(
        body_rates_rps=np.array([0.1, 0.0, 0.0], dtype=np.float64),
        thrust_normalized=0.6,
    )
    assert cmd.level == ActuatorLevel.BODY_RATE


def test_body_rate_command_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="body_rates_rps"):
        BodyRateCommand(
            body_rates_rps=np.zeros(2, dtype=np.float64),
            thrust_normalized=0.5,
        )


def test_body_rate_command_rejects_thrust_out_of_range() -> None:
    with pytest.raises(ValueError, match="thrust_normalized"):
        BodyRateCommand(
            body_rates_rps=np.zeros(3, dtype=np.float64),
            thrust_normalized=1.5,
        )


def test_body_rate_command_seals_array() -> None:
    cmd = BodyRateCommand(
        body_rates_rps=np.zeros(3, dtype=np.float64),
        thrust_normalized=0.5,
    )
    assert not cmd.body_rates_rps.flags.writeable


# ---------------------------------------------------------------------------
# AttitudeCommand
# ---------------------------------------------------------------------------


def test_attitude_command_valid_construction() -> None:
    cmd = AttitudeCommand(
        q_target=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
        thrust_normalized=0.5,
    )
    assert cmd.level == ActuatorLevel.ATTITUDE
    assert cmd.yaw_rate_rps is None


def test_attitude_command_accepts_yaw_rate() -> None:
    cmd = AttitudeCommand(
        q_target=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
        thrust_normalized=0.5,
        yaw_rate_rps=0.3,
    )
    assert cmd.yaw_rate_rps == 0.3


def test_attitude_command_rejects_non_unit_quaternion() -> None:
    with pytest.raises(ValueError, match="unit"):
        AttitudeCommand(
            q_target=np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float64),  # norm ~1.41
            thrust_normalized=0.5,
        )


def test_attitude_command_accepts_quaternion_within_norm_tolerance() -> None:
    """Tolerancia 1e-3 absorbe ruido de composición de rotaciones."""
    q = np.array([1.0 + 0.0005, 0.0, 0.0, 0.0], dtype=np.float64)
    cmd = AttitudeCommand(q_target=q, thrust_normalized=0.5)
    assert cmd.q_target[0] == pytest.approx(1.0005)


def test_attitude_command_rejects_nan_yaw_rate() -> None:
    with pytest.raises(ValueError, match="yaw_rate_rps"):
        AttitudeCommand(
            q_target=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
            thrust_normalized=0.5,
            yaw_rate_rps=float("nan"),
        )


def test_attitude_command_rejects_wrong_q_shape() -> None:
    with pytest.raises(TypeError, match="q_target"):
        AttitudeCommand(
            q_target=np.array([1.0, 0.0, 0.0], dtype=np.float64),
            thrust_normalized=0.5,
        )


# ---------------------------------------------------------------------------
# VelocityCommand
# ---------------------------------------------------------------------------


def test_velocity_command_valid_world_frame() -> None:
    cmd = VelocityCommand(
        velocity_mps=np.array([1.0, 0.0, 0.0], dtype=np.float64),
        frame="world",
    )
    assert cmd.level == ActuatorLevel.VELOCITY
    assert cmd.frame == "world"


def test_velocity_command_valid_body_frame() -> None:
    cmd = VelocityCommand(
        velocity_mps=np.zeros(3, dtype=np.float64),
        frame="body",
    )
    assert cmd.frame == "body"


def test_velocity_command_rejects_invalid_frame() -> None:
    with pytest.raises(ValueError, match="frame"):
        VelocityCommand(
            velocity_mps=np.zeros(3, dtype=np.float64),
            frame="ned",  # type: ignore[arg-type]
        )


def test_velocity_command_rejects_nan_yaw() -> None:
    with pytest.raises(ValueError, match="yaw_rad"):
        VelocityCommand(
            velocity_mps=np.zeros(3, dtype=np.float64),
            frame="world",
            yaw_rad=float("inf"),
        )


def test_velocity_command_seals_array() -> None:
    cmd = VelocityCommand(
        velocity_mps=np.array([1.0, 2.0, 3.0], dtype=np.float64),
        frame="world",
    )
    assert not cmd.velocity_mps.flags.writeable


# ---------------------------------------------------------------------------
# PositionCommand
# ---------------------------------------------------------------------------


def test_position_command_valid_construction() -> None:
    cmd = PositionCommand(
        position_enu_m=np.array([10.0, 5.0, 2.0], dtype=np.float64),
        yaw_rad=1.57,
    )
    assert cmd.level == ActuatorLevel.POSITION


def test_position_command_yaw_is_optional() -> None:
    cmd = PositionCommand(position_enu_m=np.zeros(3, dtype=np.float64))
    assert cmd.yaw_rad is None


def test_position_command_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="position_enu_m"):
        PositionCommand(position_enu_m=np.zeros(4, dtype=np.float64))


def test_position_command_seals_array() -> None:
    cmd = PositionCommand(position_enu_m=np.zeros(3, dtype=np.float64))
    assert not cmd.position_enu_m.flags.writeable


# ---------------------------------------------------------------------------
# TrajectoryCommand
# ---------------------------------------------------------------------------


def test_trajectory_command_valid_construction() -> None:
    times = np.array([0, 1_000_000, 2_000_000], dtype=np.int64)
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float64)
    cmd = TrajectoryCommand(sample_times_ns=times, positions_enu_m=positions)
    assert cmd.level == ActuatorLevel.TRAJECTORY
    assert cmd.yaws_rad is None


def test_trajectory_command_with_yaws() -> None:
    times = np.array([0, 1_000_000], dtype=np.int64)
    positions = np.zeros((2, 3), dtype=np.float64)
    yaws = np.array([0.0, 1.57], dtype=np.float64)
    cmd = TrajectoryCommand(sample_times_ns=times, positions_enu_m=positions, yaws_rad=yaws)
    assert cmd.yaws_rad is not None
    assert cmd.yaws_rad.shape == (2,)


def test_trajectory_command_rejects_single_sample() -> None:
    with pytest.raises(ValueError, match="al menos"):
        TrajectoryCommand(
            sample_times_ns=np.array([0], dtype=np.int64),
            positions_enu_m=np.zeros((1, 3), dtype=np.float64),
        )


def test_trajectory_command_rejects_non_monotonic_times() -> None:
    with pytest.raises(ValueError, match="monotónico"):
        TrajectoryCommand(
            sample_times_ns=np.array([0, 1_000, 500], dtype=np.int64),
            positions_enu_m=np.zeros((3, 3), dtype=np.float64),
        )


def test_trajectory_command_rejects_negative_times() -> None:
    with pytest.raises(ValueError, match="negativos"):
        TrajectoryCommand(
            sample_times_ns=np.array([-1_000, 0], dtype=np.int64),
            positions_enu_m=np.zeros((2, 3), dtype=np.float64),
        )


def test_trajectory_command_rejects_mismatched_positions_length() -> None:
    with pytest.raises(TypeError, match="positions_enu_m"):
        TrajectoryCommand(
            sample_times_ns=np.array([0, 1_000, 2_000], dtype=np.int64),
            positions_enu_m=np.zeros((2, 3), dtype=np.float64),  # esperado (3, 3)
        )


def test_trajectory_command_seals_all_arrays() -> None:
    times = np.array([0, 1_000], dtype=np.int64)
    positions = np.zeros((2, 3), dtype=np.float64)
    yaws = np.zeros(2, dtype=np.float64)
    cmd = TrajectoryCommand(sample_times_ns=times, positions_enu_m=positions, yaws_rad=yaws)
    assert not cmd.sample_times_ns.flags.writeable
    assert not cmd.positions_enu_m.flags.writeable
    assert cmd.yaws_rad is not None
    assert not cmd.yaws_rad.flags.writeable


# ---------------------------------------------------------------------------
# CommandAck
# ---------------------------------------------------------------------------


def test_command_ack_accepted_with_no_reason() -> None:
    ack = CommandAck(
        accepted=True,
        reason=None,
        applied_stamp_ns=100,
        saturated=False,
        extensions=MappingProxyType({}),
    )
    assert ack.accepted is True


def test_command_ack_rejected_with_reason() -> None:
    ack = CommandAck(
        accepted=False,
        reason=RejectReason.STALE_STAMP,
        applied_stamp_ns=100,
        saturated=False,
        extensions=MappingProxyType({}),
    )
    assert ack.accepted is False
    assert ack.reason == RejectReason.STALE_STAMP


def test_command_ack_rejects_accepted_with_reason() -> None:
    """Invariante: accepted=True XOR reason is not None."""
    with pytest.raises(ValueError, match="reason"):
        CommandAck(
            accepted=True,
            reason=RejectReason.INVALID_VALUE,
            applied_stamp_ns=0,
            saturated=False,
            extensions=MappingProxyType({}),
        )


def test_command_ack_rejects_rejected_without_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        CommandAck(
            accepted=False,
            reason=None,
            applied_stamp_ns=0,
            saturated=False,
            extensions=MappingProxyType({}),
        )


def test_command_ack_rejects_negative_applied_stamp() -> None:
    with pytest.raises(ValueError, match="applied_stamp_ns"):
        CommandAck(
            accepted=True,
            reason=None,
            applied_stamp_ns=-1,
            saturated=False,
            extensions=MappingProxyType({}),
        )


def test_command_ack_saturated_is_independent_of_accepted() -> None:
    """saturated=True con accepted=True: comando aplicado con clipping."""
    ack = CommandAck(
        accepted=True,
        reason=None,
        applied_stamp_ns=0,
        saturated=True,
        extensions=MappingProxyType({}),
    )
    assert ack.accepted is True
    assert ack.saturated is True


# ---------------------------------------------------------------------------
# SafetyEnvelope
# ---------------------------------------------------------------------------


def test_safety_envelope_valid_no_geofence() -> None:
    env = _envelope()
    assert env.geofence_polygon is None
    assert env.require_arm is True


def test_safety_envelope_valid_with_geofence() -> None:
    polygon = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    env = _envelope(geofence_polygon=polygon)
    assert env.geofence_polygon == polygon


def test_safety_envelope_rejects_nonpositive_limits() -> None:
    for field in (
        "max_tilt_rad",
        "max_climb_rate_mps",
        "max_horiz_speed_mps",
        "max_yaw_rate_rps",
    ):
        with pytest.raises(ValueError, match=field):
            _envelope(**{field: 0.0})


def test_safety_envelope_rejects_altitude_max_le_min() -> None:
    with pytest.raises(ValueError, match="altitude"):
        _envelope(altitude_min_m=10.0, altitude_max_m=5.0)


def test_safety_envelope_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="command_timeout_ns"):
        _envelope(command_timeout_ns=0)


def test_safety_envelope_rejects_list_geofence() -> None:
    """geofence_polygon debe ser tuple (uncertainty.md §10)."""
    polygon = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    with pytest.raises(TypeError, match="tuple"):
        _envelope(geofence_polygon=polygon)


def test_safety_envelope_rejects_degenerate_polygon() -> None:
    with pytest.raises(ValueError, match="3 vértices"):
        _envelope(geofence_polygon=((0.0, 0.0), (1.0, 0.0)))


# ---------------------------------------------------------------------------
# ActuatorSpec
# ---------------------------------------------------------------------------


def test_actuator_spec_valid_construction() -> None:
    spec = ActuatorSpec(
        actuator_id="main_motors",
        supported_levels=(ActuatorLevel.DIRECT_MOTOR, ActuatorLevel.BODY_RATE),
        safety_envelope=_envelope(),
    )
    assert spec.actuator_id == "main_motors"
    assert len(spec.supported_levels) == 2


def test_actuator_spec_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="actuator_id"):
        ActuatorSpec(
            actuator_id="",
            supported_levels=(ActuatorLevel.DIRECT_MOTOR,),
            safety_envelope=_envelope(),
        )


def test_actuator_spec_rejects_list_levels() -> None:
    """supported_levels debe ser tuple."""
    with pytest.raises(TypeError, match="tuple"):
        ActuatorSpec(
            actuator_id="main",
            supported_levels=[ActuatorLevel.DIRECT_MOTOR],  # type: ignore[arg-type]
            safety_envelope=_envelope(),
        )


def test_actuator_spec_rejects_empty_levels() -> None:
    with pytest.raises(ValueError, match="supported_levels"):
        ActuatorSpec(
            actuator_id="main",
            supported_levels=(),
            safety_envelope=_envelope(),
        )


def test_actuator_spec_rejects_duplicate_levels() -> None:
    with pytest.raises(ValueError, match="duplicado"):
        ActuatorSpec(
            actuator_id="main",
            supported_levels=(
                ActuatorLevel.DIRECT_MOTOR,
                ActuatorLevel.DIRECT_MOTOR,
            ),
            safety_envelope=_envelope(),
        )
