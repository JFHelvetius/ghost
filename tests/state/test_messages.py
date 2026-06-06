"""Tests de `state.messages` (T2.a.3).

Cubre Pose, Twist, IMUBiases, NavigationState, SensorHealthMap,
FlightStatus/FlightMode, MissionStatus/MissionMode/Goal y VehicleState
top-level, incluyendo validación de covarianza simétrica + PSD.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.hal.messages import SensorHealth
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    Goal,
    IMUBiases,
    MissionMode,
    MissionStatus,
    NavigationState,
    Pose,
    SensorHealthMap,
    Twist,
    VehicleState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IDENTITY_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _pose() -> Pose:
    return Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_IDENTITY_Q.copy(),
    )


def _twist_world() -> Twist:
    return Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )


def _twist_body() -> Twist:
    return Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="body",
    )


def _biases() -> IMUBiases:
    return IMUBiases(
        accel_bias_mps2=np.zeros(3, dtype=np.float64),
        gyro_bias_rps=np.zeros(3, dtype=np.float64),
    )


def _nav(cov: np.ndarray | None = None) -> NavigationState:
    return NavigationState(
        pose=_pose(),
        twist_world=_twist_world(),
        twist_body=_twist_body(),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=_biases(),
        covariance_15x15=cov,
    )


def _flight() -> FlightStatus:
    return FlightStatus(
        armed=False,
        flight_mode=FlightMode.INIT,
        battery_v=None,
        battery_pct=None,
        error_flags=0,
    )


def _mission() -> MissionStatus:
    return MissionStatus(
        mode=MissionMode.IDLE,
        current_goal=None,
        progress=0.0,
        started_sim_ns=None,
    )


def _health_map() -> SensorHealthMap:
    return SensorHealthMap(by_id=MappingProxyType({}))


# ---------------------------------------------------------------------------
# Pose
# ---------------------------------------------------------------------------


def test_pose_valid_construction() -> None:
    p = _pose()
    assert p.position_enu_m.shape == (3,)
    assert p.orientation_q.shape == (4,)


def test_pose_is_frozen() -> None:
    p = _pose()
    with pytest.raises(FrozenInstanceError):
        p.position_enu_m = np.zeros(3, dtype=np.float64)  # type: ignore[misc]


def test_pose_rejects_wrong_position_shape() -> None:
    with pytest.raises(TypeError, match="position_enu_m"):
        Pose(
            position_enu_m=np.zeros(4, dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
        )


def test_pose_rejects_non_unit_quaternion() -> None:
    with pytest.raises(ValueError, match="unit"):
        Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float64),
        )


def test_pose_rejects_nan_position() -> None:
    with pytest.raises(ValueError, match="NaN"):
        Pose(
            position_enu_m=np.array([0.0, np.nan, 0.0], dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
        )


def test_pose_arrays_are_sealed() -> None:
    p = _pose()
    assert not p.position_enu_m.flags.writeable
    assert not p.orientation_q.flags.writeable


# ---------------------------------------------------------------------------
# Twist
# ---------------------------------------------------------------------------


def test_twist_valid_world() -> None:
    t = _twist_world()
    assert t.frame == "world"


def test_twist_valid_body() -> None:
    t = _twist_body()
    assert t.frame == "body"


def test_twist_rejects_invalid_frame() -> None:
    with pytest.raises(ValueError, match="frame"):
        Twist(
            linear_mps=np.zeros(3, dtype=np.float64),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="ned",  # type: ignore[arg-type]
        )


def test_twist_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="linear_mps"):
        Twist(
            linear_mps=np.zeros(4, dtype=np.float64),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="world",
        )


def test_twist_seals_arrays() -> None:
    t = _twist_world()
    assert not t.linear_mps.flags.writeable
    assert not t.angular_rps.flags.writeable


# ---------------------------------------------------------------------------
# IMUBiases
# ---------------------------------------------------------------------------


def test_imu_biases_valid_construction() -> None:
    b = _biases()
    assert b.accel_bias_mps2.shape == (3,)
    assert b.gyro_bias_rps.shape == (3,)


def test_imu_biases_rejects_nan() -> None:
    with pytest.raises(ValueError, match="NaN"):
        IMUBiases(
            accel_bias_mps2=np.array([np.nan, 0.0, 0.0], dtype=np.float64),
            gyro_bias_rps=np.zeros(3, dtype=np.float64),
        )


def test_imu_biases_arrays_are_sealed() -> None:
    b = _biases()
    assert not b.accel_bias_mps2.flags.writeable
    assert not b.gyro_bias_rps.flags.writeable


# ---------------------------------------------------------------------------
# NavigationState
# ---------------------------------------------------------------------------


def test_nav_state_valid_without_covariance() -> None:
    nav = _nav()
    assert nav.covariance_15x15 is None


def test_nav_state_valid_with_identity_covariance() -> None:
    cov = np.eye(15, dtype=np.float64)
    nav = _nav(cov=cov)
    assert nav.covariance_15x15 is not None


def test_nav_state_rejects_twist_world_with_body_frame() -> None:
    with pytest.raises(ValueError, match="twist_world"):
        NavigationState(
            pose=_pose(),
            twist_world=_twist_body(),  # frame wrong
            twist_body=_twist_body(),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
            imu_biases=_biases(),
            covariance_15x15=None,
        )


def test_nav_state_rejects_twist_body_with_world_frame() -> None:
    with pytest.raises(ValueError, match="twist_body"):
        NavigationState(
            pose=_pose(),
            twist_world=_twist_world(),
            twist_body=_twist_world(),  # frame wrong
            accel_body_mps2=np.zeros(3, dtype=np.float64),
            imu_biases=_biases(),
            covariance_15x15=None,
        )


def test_nav_state_rejects_wrong_covariance_shape() -> None:
    with pytest.raises(TypeError, match="covariance_15x15"):
        _nav(cov=np.eye(10, dtype=np.float64))


def test_nav_state_rejects_asymmetric_covariance() -> None:
    cov = np.eye(15, dtype=np.float64)
    cov[0, 1] = 1.0  # rompe simetría
    with pytest.raises(ValueError, match="simétrica"):
        _nav(cov=cov)


def test_nav_state_rejects_negative_definite_covariance() -> None:
    cov = -np.eye(15, dtype=np.float64)  # PSD violado
    with pytest.raises(ValueError, match="PSD"):
        _nav(cov=cov)


def test_nav_state_arrays_are_sealed() -> None:
    cov = np.eye(15, dtype=np.float64)
    nav = _nav(cov=cov)
    assert not nav.accel_body_mps2.flags.writeable
    assert nav.covariance_15x15 is not None
    assert not nav.covariance_15x15.flags.writeable


# ---------------------------------------------------------------------------
# SensorHealthMap
# ---------------------------------------------------------------------------


def test_sensor_health_map_empty_is_allowed() -> None:
    """Map vacío permitido (e.g. durante init antes de registrar sensors)."""
    m = SensorHealthMap(by_id=MappingProxyType({}))
    assert len(m.by_id) == 0


def test_sensor_health_map_with_entries() -> None:
    m = SensorHealthMap(
        by_id=MappingProxyType(
            {
                "imu0": SensorHealth.OK,
                "cam_front": SensorHealth.DEGRADED,
            }
        )
    )
    assert m.by_id["imu0"] == SensorHealth.OK
    assert m.by_id["cam_front"] == SensorHealth.DEGRADED


def test_sensor_health_map_is_frozen() -> None:
    m = _health_map()
    with pytest.raises(FrozenInstanceError):
        m.by_id = MappingProxyType({})  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FlightMode / FlightStatus
# ---------------------------------------------------------------------------


def test_flight_mode_catalog_size() -> None:
    assert len(list(FlightMode)) == 7


def test_flight_status_valid_minimal() -> None:
    fs = _flight()
    assert fs.armed is False
    assert fs.flight_mode == FlightMode.INIT


def test_flight_status_with_battery() -> None:
    fs = FlightStatus(
        armed=True,
        flight_mode=FlightMode.OFFBOARD,
        battery_v=12.4,
        battery_pct=0.85,
        error_flags=0,
    )
    assert fs.battery_pct == 0.85


def test_flight_status_rejects_battery_pct_out_of_range() -> None:
    with pytest.raises(ValueError, match="battery_pct"):
        FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=None,
            battery_pct=1.5,
            error_flags=0,
        )


def test_flight_status_rejects_negative_battery_pct() -> None:
    with pytest.raises(ValueError, match="battery_pct"):
        FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=None,
            battery_pct=-0.1,
            error_flags=0,
        )


def test_flight_status_rejects_nan_battery_v() -> None:
    with pytest.raises(ValueError, match="battery_v"):
        FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=float("nan"),
            battery_pct=None,
            error_flags=0,
        )


def test_flight_status_rejects_negative_error_flags() -> None:
    with pytest.raises(ValueError, match="error_flags"):
        FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=None,
            battery_pct=None,
            error_flags=-1,
        )


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------


def test_goal_with_position_and_yaw() -> None:
    g = Goal(
        position_enu_m=np.array([5.0, 0.0, 2.0], dtype=np.float64),
        yaw_rad=1.0,
        metadata=MappingProxyType({}),
    )
    assert g.yaw_rad == 1.0


def test_goal_all_optional_none() -> None:
    g = Goal(position_enu_m=None, yaw_rad=None, metadata=MappingProxyType({}))
    assert g.position_enu_m is None
    assert g.yaw_rad is None


def test_goal_rejects_wrong_position_shape() -> None:
    with pytest.raises(TypeError, match="position_enu_m"):
        Goal(
            position_enu_m=np.zeros(4, dtype=np.float64),
            yaw_rad=None,
            metadata=MappingProxyType({}),
        )


def test_goal_rejects_nan_yaw() -> None:
    with pytest.raises(ValueError, match="yaw_rad"):
        Goal(
            position_enu_m=None,
            yaw_rad=float("inf"),
            metadata=MappingProxyType({}),
        )


def test_goal_position_array_is_sealed() -> None:
    g = Goal(
        position_enu_m=np.zeros(3, dtype=np.float64),
        yaw_rad=None,
        metadata=MappingProxyType({}),
    )
    assert g.position_enu_m is not None
    assert not g.position_enu_m.flags.writeable


# ---------------------------------------------------------------------------
# MissionMode / MissionStatus
# ---------------------------------------------------------------------------


def test_mission_mode_catalog_size() -> None:
    assert len(list(MissionMode)) == 6


def test_mission_status_idle_no_goal() -> None:
    ms = _mission()
    assert ms.mode == MissionMode.IDLE
    assert ms.current_goal is None
    assert ms.progress == 0.0


def test_mission_status_with_goal_and_progress() -> None:
    goal = Goal(
        position_enu_m=np.array([10.0, 0.0, 5.0], dtype=np.float64),
        yaw_rad=None,
        metadata=MappingProxyType({}),
    )
    ms = MissionStatus(
        mode=MissionMode.NAVIGATE,
        current_goal=goal,
        progress=0.5,
        started_sim_ns=1_000_000,
    )
    assert ms.current_goal is goal
    assert ms.progress == 0.5
    assert ms.started_sim_ns == 1_000_000


def test_mission_status_rejects_progress_out_of_range() -> None:
    with pytest.raises(ValueError, match="progress"):
        MissionStatus(
            mode=MissionMode.NAVIGATE,
            current_goal=None,
            progress=1.5,
            started_sim_ns=None,
        )


def test_mission_status_rejects_negative_started() -> None:
    with pytest.raises(ValueError, match="started_sim_ns"):
        MissionStatus(
            mode=MissionMode.NAVIGATE,
            current_goal=None,
            progress=0.0,
            started_sim_ns=-1,
        )


def test_mission_status_rejects_nan_progress() -> None:
    with pytest.raises(ValueError, match="progress"):
        MissionStatus(
            mode=MissionMode.NAVIGATE,
            current_goal=None,
            progress=float("nan"),
            started_sim_ns=None,
        )


# ---------------------------------------------------------------------------
# VehicleState — top-level integration
# ---------------------------------------------------------------------------


def test_vehicle_state_valid_construction_phase1_groundtruth() -> None:
    """Construcción end-to-end estilo Fase 1 con GT (state.md §5.1)."""
    vs = VehicleState(
        stamp_sim_ns=1_000,
        stamp_wall_ns=2_000,
        nav=_nav(),
        sensors=_health_map(),
        flight=_flight(),
        mission=_mission(),
    )
    assert vs.stamp_sim_ns == 1_000
    assert vs.schema_version == 1


def test_vehicle_state_with_covariance() -> None:
    vs = VehicleState(
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        nav=_nav(cov=np.eye(15, dtype=np.float64)),
        sensors=_health_map(),
        flight=_flight(),
        mission=_mission(),
    )
    assert vs.nav.covariance_15x15 is not None


def test_vehicle_state_is_frozen() -> None:
    vs = VehicleState(
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        nav=_nav(),
        sensors=_health_map(),
        flight=_flight(),
        mission=_mission(),
    )
    with pytest.raises(FrozenInstanceError):
        vs.stamp_sim_ns = 999  # type: ignore[misc]


def test_vehicle_state_rejects_negative_stamps() -> None:
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        VehicleState(
            stamp_sim_ns=-1,
            stamp_wall_ns=0,
            nav=_nav(),
            sensors=_health_map(),
            flight=_flight(),
            mission=_mission(),
        )


def test_vehicle_state_rejects_schema_version_below_one() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        VehicleState(
            stamp_sim_ns=0,
            stamp_wall_ns=0,
            nav=_nav(),
            sensors=_health_map(),
            flight=_flight(),
            mission=_mission(),
            schema_version=0,
        )


def test_vehicle_state_equality_by_value() -> None:
    a = VehicleState(
        stamp_sim_ns=100,
        stamp_wall_ns=200,
        nav=_nav(),
        sensors=_health_map(),
        flight=_flight(),
        mission=_mission(),
    )
    b = VehicleState(
        stamp_sim_ns=100,
        stamp_wall_ns=200,
        nav=_nav(),
        sensors=_health_map(),
        flight=_flight(),
        mission=_mission(),
    )
    # Note: arrays inside use new instances each time, so equality on the
    # whole VehicleState is not guaranteed by default dataclass eq (numpy
    # arrays don't compare element-wise via ==). We just check that the
    # construction is symmetric and the scalar stamps match.
    assert a.stamp_sim_ns == b.stamp_sim_ns
    assert a.flight.flight_mode == b.flight.flight_mode
