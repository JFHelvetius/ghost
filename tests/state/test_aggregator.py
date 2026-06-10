"""Tests de `state.aggregator.vehicle_state_from_ground_truth` (T2.a.6).

Estrategia: la función es pura, así que probamos:

- **Anchor**: quadrotor estático en spawn (T9 criterio de aceptación
  "pose.position_enu_m corresponde al spawn point").
- **Frame conversions**: traslación pura (sin rotación) y rotación pura
  (yaw 90°) — verificamos que `twist_body` y `twist_world` se calculan
  correctamente vía `R_body_to_world` / `R_world_to_body`.
- **Contratos del path GT**: `covariance_15x15 is None`, `imu_biases`
  son zero. Estos tests **documentan en código** la decisión
  "truth ≠ belief" — el agregador NO finge incertidumbre.
- **Pass-through**: campos discretos (`SensorHealthMap`, `FlightStatus`,
  `MissionStatus`) llegan sin modificar.
- **Determinismo**: misma input -> mismo output bit a bit.
- **No mutación de inputs**: los arrays sellados del `GroundTruth` no
  se tocan.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.hal.messages import GroundTruth, SensorHealth
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    MissionMode,
    MissionStatus,
    SensorHealthMap,
    VehicleState,
    vehicle_state_from_ground_truth,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
_Q_YAW_90 = np.array([np.sqrt(2.0) / 2.0, 0.0, 0.0, np.sqrt(2.0) / 2.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Fixtures helper
# ---------------------------------------------------------------------------


def _gt(
    *,
    stamp_sim_ns: int = 0,
    position_enu_m: np.ndarray | None = None,
    orientation_q: np.ndarray | None = None,
    linear_velocity_world_mps: np.ndarray | None = None,
    angular_velocity_body_rps: np.ndarray | None = None,
    accel_body_mps2: np.ndarray | None = None,
) -> GroundTruth:
    return GroundTruth(
        stamp_sim_ns=stamp_sim_ns,
        position_enu_m=(
            position_enu_m if position_enu_m is not None else np.zeros(3, dtype=np.float64)
        ),
        orientation_q=(orientation_q if orientation_q is not None else _Q_IDENTITY.copy()),
        linear_velocity_world_mps=(
            linear_velocity_world_mps
            if linear_velocity_world_mps is not None
            else np.zeros(3, dtype=np.float64)
        ),
        angular_velocity_body_rps=(
            angular_velocity_body_rps
            if angular_velocity_body_rps is not None
            else np.zeros(3, dtype=np.float64)
        ),
        accel_body_mps2=(
            accel_body_mps2 if accel_body_mps2 is not None else np.zeros(3, dtype=np.float64)
        ),
    )


def _flight() -> FlightStatus:
    return FlightStatus(
        armed=True,
        flight_mode=FlightMode.OFFBOARD,
        battery_v=12.4,
        battery_pct=0.85,
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
    return SensorHealthMap(
        by_id=MappingProxyType(
            {
                "imu0": SensorHealth.OK,
                "cam_front": SensorHealth.OK,
            }
        )
    )


def _aggregate(
    *,
    gt: GroundTruth | None = None,
    stamp_wall_ns: int = 0,
) -> VehicleState:
    return vehicle_state_from_ground_truth(
        gt=gt if gt is not None else _gt(),
        sensors_health=_health_map(),
        flight=_flight(),
        mission=_mission(),
        stamp_wall_ns=stamp_wall_ns,
    )


# ---------------------------------------------------------------------------
# Anchor — quadrotor estático en spawn
# ---------------------------------------------------------------------------


def test_static_quadrotor_at_spawn_reports_spawn_pose() -> None:
    """T9 criterio: quadrotor estático -> pose corresponde al spawn point."""
    spawn = np.array([2.5, 1.3, 0.5], dtype=np.float64)
    gt = _gt(position_enu_m=spawn, orientation_q=_Q_IDENTITY.copy())

    vs = _aggregate(gt=gt)

    np.testing.assert_array_equal(vs.nav.pose.position_enu_m, spawn)
    np.testing.assert_array_equal(vs.nav.pose.orientation_q, _Q_IDENTITY)


def test_static_quadrotor_has_zero_twists() -> None:
    """Estático -> ambos twists son cero."""
    vs = _aggregate(gt=_gt())
    np.testing.assert_array_equal(vs.nav.twist_world.linear_mps, np.zeros(3, dtype=np.float64))
    np.testing.assert_array_equal(vs.nav.twist_world.angular_rps, np.zeros(3, dtype=np.float64))
    np.testing.assert_array_equal(vs.nav.twist_body.linear_mps, np.zeros(3, dtype=np.float64))
    np.testing.assert_array_equal(vs.nav.twist_body.angular_rps, np.zeros(3, dtype=np.float64))


# ---------------------------------------------------------------------------
# Path GT: covariance None, biases zero — "truth ≠ belief"
# ---------------------------------------------------------------------------


def test_gt_path_yields_no_covariance() -> None:
    """Contrato del path GT: covariance_15x15 es None. Documenta que GT
    NO es una estimación con baja incertidumbre — es la verdad."""
    vs = _aggregate()
    assert vs.nav.covariance_15x15 is None


def test_gt_path_yields_zero_imu_biases() -> None:
    """Contrato del path GT: biases del IMU son zero. En sim con GT no
    hay biases que estimar."""
    vs = _aggregate()
    np.testing.assert_array_equal(vs.nav.imu_biases.accel_bias_mps2, np.zeros(3, dtype=np.float64))
    np.testing.assert_array_equal(vs.nav.imu_biases.gyro_bias_rps, np.zeros(3, dtype=np.float64))


# ---------------------------------------------------------------------------
# Frame conversions — traslación pura
# ---------------------------------------------------------------------------


def test_translation_only_no_rotation_twist_body_equals_world() -> None:
    """Sin rotación (q=identity), twist_body.linear_mps == twist_world.linear_mps
    porque R_world_to_body es la identidad."""
    v_world = np.array([3.0, 1.0, -0.5], dtype=np.float64)
    gt = _gt(orientation_q=_Q_IDENTITY.copy(), linear_velocity_world_mps=v_world)

    vs = _aggregate(gt=gt)

    np.testing.assert_array_equal(vs.nav.twist_world.linear_mps, v_world)
    np.testing.assert_allclose(vs.nav.twist_body.linear_mps, v_world, atol=1e-15)


def test_translation_only_no_rotation_angular_world_equals_body() -> None:
    omega_body = np.array([0.1, 0.2, 0.3], dtype=np.float64)
    gt = _gt(orientation_q=_Q_IDENTITY.copy(), angular_velocity_body_rps=omega_body)

    vs = _aggregate(gt=gt)

    np.testing.assert_array_equal(vs.nav.twist_body.angular_rps, omega_body)
    np.testing.assert_allclose(vs.nav.twist_world.angular_rps, omega_body, atol=1e-15)


# ---------------------------------------------------------------------------
# Frame conversions — rotación pura (yaw 90°)
# ---------------------------------------------------------------------------


def test_yaw_90_world_x_velocity_maps_to_negative_body_y() -> None:
    """Tras yaw 90° (body rotado 90° CCW), un vector que apunta a world-east
    (eje x mundo) está a la derecha del body (eje -y body en FLU)."""
    v_world = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    gt = _gt(orientation_q=_Q_YAW_90.copy(), linear_velocity_world_mps=v_world)

    vs = _aggregate(gt=gt)

    np.testing.assert_array_equal(vs.nav.twist_world.linear_mps, v_world)
    np.testing.assert_allclose(
        vs.nav.twist_body.linear_mps,
        np.array([0.0, -1.0, 0.0], dtype=np.float64),
        atol=1e-15,
    )


def test_yaw_90_body_x_angular_velocity_maps_to_world_y() -> None:
    """omega_body = [1, 0, 0] (roll en body) -> en world se ve como pitch."""
    omega_body = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    gt = _gt(orientation_q=_Q_YAW_90.copy(), angular_velocity_body_rps=omega_body)

    vs = _aggregate(gt=gt)

    np.testing.assert_array_equal(vs.nav.twist_body.angular_rps, omega_body)
    np.testing.assert_allclose(
        vs.nav.twist_world.angular_rps,
        np.array([0.0, 1.0, 0.0], dtype=np.float64),
        atol=1e-15,
    )


# ---------------------------------------------------------------------------
# Pass-through y stamps
# ---------------------------------------------------------------------------


def test_stamp_sim_ns_comes_from_ground_truth() -> None:
    vs = _aggregate(gt=_gt(stamp_sim_ns=12345))
    assert vs.stamp_sim_ns == 12345


def test_stamp_wall_ns_comes_from_argument() -> None:
    vs = _aggregate(stamp_wall_ns=99999)
    assert vs.stamp_wall_ns == 99999


def test_sensors_flight_mission_pass_through_unchanged() -> None:
    vs = _aggregate()
    assert vs.flight.flight_mode == FlightMode.OFFBOARD
    assert vs.flight.armed is True
    assert vs.mission.mode == MissionMode.IDLE
    assert vs.sensors.by_id["imu0"] == SensorHealth.OK


def test_accel_body_is_copied_from_ground_truth() -> None:
    accel = np.array([0.0, 0.0, 9.81], dtype=np.float64)
    gt = _gt(accel_body_mps2=accel)
    vs = _aggregate(gt=gt)
    np.testing.assert_array_equal(vs.nav.accel_body_mps2, accel)


def test_schema_version_is_one() -> None:
    vs = _aggregate()
    assert vs.schema_version == 1


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------


def test_aggregator_is_deterministic_bitwise() -> None:
    """Misma input -> mismo output bit a bit (ADR-0002)."""
    gt = _gt(
        stamp_sim_ns=1_000,
        position_enu_m=np.array([1.5, -2.5, 0.7], dtype=np.float64),
        orientation_q=_Q_YAW_90.copy(),
        linear_velocity_world_mps=np.array([0.3, 0.0, -0.1], dtype=np.float64),
        angular_velocity_body_rps=np.array([0.0, 0.05, 0.2], dtype=np.float64),
        accel_body_mps2=np.array([0.0, 0.0, 9.81], dtype=np.float64),
    )

    vs1 = _aggregate(gt=gt, stamp_wall_ns=42)
    vs2 = _aggregate(gt=gt, stamp_wall_ns=42)

    assert vs1.stamp_sim_ns == vs2.stamp_sim_ns
    assert vs1.stamp_wall_ns == vs2.stamp_wall_ns
    for attr in ("position_enu_m", "orientation_q"):
        np.testing.assert_array_equal(getattr(vs1.nav.pose, attr), getattr(vs2.nav.pose, attr))
    for attr in ("linear_mps", "angular_rps"):
        np.testing.assert_array_equal(
            getattr(vs1.nav.twist_world, attr),
            getattr(vs2.nav.twist_world, attr),
        )
        np.testing.assert_array_equal(
            getattr(vs1.nav.twist_body, attr),
            getattr(vs2.nav.twist_body, attr),
        )
    np.testing.assert_array_equal(vs1.nav.accel_body_mps2, vs2.nav.accel_body_mps2)


# ---------------------------------------------------------------------------
# No mutación de inputs
# ---------------------------------------------------------------------------


def test_aggregator_does_not_mutate_ground_truth_arrays() -> None:
    """Los arrays de GroundTruth están sellados — el agregador no debe
    tocarlos."""
    pos_before = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    q_before = _Q_YAW_90.copy()
    v_before = np.array([0.5, 0.0, -0.3], dtype=np.float64)

    gt = _gt(
        position_enu_m=pos_before.copy(),
        orientation_q=q_before.copy(),
        linear_velocity_world_mps=v_before.copy(),
    )

    _aggregate(gt=gt)

    np.testing.assert_array_equal(gt.position_enu_m, pos_before)
    np.testing.assert_array_equal(gt.orientation_q, q_before)
    np.testing.assert_array_equal(gt.linear_velocity_world_mps, v_before)


# ---------------------------------------------------------------------------
# Quaternion no-unit en GT — agregador hereda la validación de los componentes
# ---------------------------------------------------------------------------


def test_aggregator_propagates_quaternion_validation_through_transforms() -> None:
    """Si por alguna vía el quaternion no fuera unit, `R_body_to_world`
    lanzaría ValueError. GT ya valida unit-norm en construcción, así que
    este test es defensivo: documenta que la cadena entera de validaciones
    es robusta."""
    bad_q = np.array([2.0, 0.0, 0.0, 0.0], dtype=np.float64)  # norm=2
    with pytest.raises(ValueError, match="unit"):
        # GroundTruth.__post_init__ rechaza antes de llegar al agregador.
        GroundTruth(
            stamp_sim_ns=0,
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=bad_q,
            linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )
