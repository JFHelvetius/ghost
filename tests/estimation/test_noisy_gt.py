"""Tests de `NoisyGroundTruthEstimator`.

Cubre los contratos del ADR-0015 sobre la salida del estimador:

- **Producción de creencia**: ``covariance_15x15 is not None``.
- **Estructura del VehicleState**: schema_version, frames de twist,
  IMU biases zero, stamps correctos.
- **Pose válida**: quaternion unit-norm tras perturbación (ADR-0015 §3).
- **Coherencia interna del twist**: usa la quaternion ruidosa para
  R_body_to_world y R_world_to_body (ADR-0015 §4).
- **Perturbación efectiva**: con stds > 0 la salida difiere de GT;
  con stds == 0 la salida coincide con GT por campo.
- **Covarianza preservada bit-a-bit**: la cov en el VehicleState
  iguala a la declarada en el config.
- **No mutación de inputs**: arrays sellados de GT no se modifican.
- **Reusabilidad del estimador**: múltiples calls producen muestras
  independientes (no muestras idénticas).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.estimation import (
    NoisyGroundTruthEstimator,
)
from project_ghost.state.messages import VehicleState
from project_ghost.state.transforms import R_body_to_world, R_world_to_body

if TYPE_CHECKING:
    from project_ghost.core.clock.types import RandomSource
    from project_ghost.estimation import NoisyGroundTruthConfig
    from project_ghost.hal.messages import GroundTruth
from tests.estimation.conftest import (
    Q_IDENTITY,
    make_config,
    make_declared_cov,
    make_flight,
    make_gt,
    make_health,
    make_mission,
    make_rs,
)


def _estimate(
    *,
    config: NoisyGroundTruthConfig | None = None,
    rs: RandomSource | None = None,
    gt: GroundTruth | None = None,
    stamp_wall_ns: int = 0,
) -> VehicleState:
    estimator = NoisyGroundTruthEstimator(
        config=config if config is not None else make_config(),
        random_source=rs if rs is not None else make_rs(),
    )
    return estimator.estimate(
        gt=gt if gt is not None else make_gt(),
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=stamp_wall_ns,
    )


# ---------------------------------------------------------------------------
# Producción de creencia — el contrato principal de ADR-0015
# ---------------------------------------------------------------------------


def test_output_has_non_none_covariance() -> None:
    """El contrato central del ADR-0015: este path produce creencia,
    NO verdad. covariance_15x15 debe estar presente."""
    vs = _estimate()
    assert vs.nav.covariance_15x15 is not None


def test_output_covariance_equals_declared_bitwise() -> None:
    """La cov publicada es exactamente la declarada por el caller
    (no derivada, no propagada)."""
    declared = make_declared_cov(scale=2.5e-2)
    cfg = make_config(declared_covariance_15x15=declared)
    vs = _estimate(config=cfg)
    assert vs.nav.covariance_15x15 is not None
    np.testing.assert_array_equal(vs.nav.covariance_15x15, declared)


def test_output_covariance_is_independent_copy_of_config() -> None:
    """Mutar la cov del VehicleState NO debe afectar la del config
    (NavigationState la sella, pero verificamos que sea otra instancia)."""
    cfg = make_config()
    vs = _estimate(config=cfg)
    assert vs.nav.covariance_15x15 is not cfg.declared_covariance_15x15


# ---------------------------------------------------------------------------
# Estructura del VehicleState
# ---------------------------------------------------------------------------


def test_output_is_vehicle_state() -> None:
    vs = _estimate()
    assert isinstance(vs, VehicleState)


def test_output_schema_version_is_one() -> None:
    vs = _estimate()
    assert vs.schema_version == 1


def test_output_twist_frames_are_world_and_body() -> None:
    vs = _estimate()
    assert vs.nav.twist_world.frame == "world"
    assert vs.nav.twist_body.frame == "body"


def test_output_imu_biases_are_zero() -> None:
    """ADR-0015 §5: este estimador no infiere biases."""
    vs = _estimate()
    np.testing.assert_array_equal(
        vs.nav.imu_biases.accel_bias_mps2, np.zeros(3, dtype=np.float64)
    )
    np.testing.assert_array_equal(
        vs.nav.imu_biases.gyro_bias_rps, np.zeros(3, dtype=np.float64)
    )


def test_output_stamp_sim_ns_from_gt() -> None:
    gt = make_gt(stamp_sim_ns=12345)
    vs = _estimate(gt=gt)
    assert vs.stamp_sim_ns == 12345


def test_output_stamp_wall_ns_from_argument() -> None:
    vs = _estimate(stamp_wall_ns=99999)
    assert vs.stamp_wall_ns == 99999


def test_output_pose_quaternion_is_unit_norm() -> None:
    """Tras la perturbación y la renormalización, la quaternion debe
    pasar `Pose._validate_unit_quaternion` (tol 1e-3). El test
    construye el VehicleState; si fallara la norm, NavigationState ya
    habría lanzado en __post_init__. Verificamos explícitamente."""
    vs = _estimate()
    norm = float(np.linalg.norm(vs.nav.pose.orientation_q))
    assert abs(norm - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Coherencia interna del twist con la pose RUIDOSA (ADR-0015 §4)
# ---------------------------------------------------------------------------


def test_twist_world_is_consistent_with_noisy_quaternion() -> None:
    """Re-derivar twist_world.angular_rps desde twist_body.angular_rps y
    la quaternion publicada debe coincidir bit-a-bit con lo que el
    estimador puso en twist_world."""
    vs = _estimate()
    r_b2w = R_body_to_world(vs.nav.pose.orientation_q)
    expected = r_b2w @ vs.nav.twist_body.angular_rps
    np.testing.assert_allclose(
        vs.nav.twist_world.angular_rps, expected, atol=1e-15
    )


def test_twist_body_is_consistent_with_noisy_quaternion() -> None:
    vs = _estimate()
    r_w2b = R_world_to_body(vs.nav.pose.orientation_q)
    expected = r_w2b @ vs.nav.twist_world.linear_mps
    np.testing.assert_allclose(
        vs.nav.twist_body.linear_mps, expected, atol=1e-15
    )


# ---------------------------------------------------------------------------
# Ruido cero -> no perturbación (regla de honestidad del muestreador)
# ---------------------------------------------------------------------------


def test_zero_noise_position_equals_ground_truth_position() -> None:
    cfg = make_config(
        position_noise_std_m=0.0,
        orientation_noise_std_rad=0.0,
        linear_velocity_noise_std_mps=0.0,
        angular_velocity_noise_std_rps=0.0,
        accel_body_noise_std_mps2=0.0,
    )
    gt = make_gt(
        position_enu_m=np.array([1.5, -0.7, 0.2], dtype=np.float64)
    )
    vs = _estimate(config=cfg, gt=gt)
    np.testing.assert_array_equal(
        vs.nav.pose.position_enu_m, gt.position_enu_m
    )


def test_zero_noise_quaternion_equals_ground_truth_quaternion() -> None:
    """Con std=0 la perturbación tangente es zero y q' = identity ⊗ q = q.
    La renormalización es un no-op (q ya es unit)."""
    cfg = make_config(
        position_noise_std_m=0.0,
        orientation_noise_std_rad=0.0,
        linear_velocity_noise_std_mps=0.0,
        angular_velocity_noise_std_rps=0.0,
        accel_body_noise_std_mps2=0.0,
    )
    q_yaw = np.array(
        [np.sqrt(2.0) / 2.0, 0.0, 0.0, np.sqrt(2.0) / 2.0], dtype=np.float64
    )
    gt = make_gt(orientation_q=q_yaw.copy())
    vs = _estimate(config=cfg, gt=gt)
    np.testing.assert_allclose(
        vs.nav.pose.orientation_q, q_yaw, atol=1e-15
    )


def test_zero_noise_velocities_and_accel_equal_ground_truth() -> None:
    cfg = make_config(
        position_noise_std_m=0.0,
        orientation_noise_std_rad=0.0,
        linear_velocity_noise_std_mps=0.0,
        angular_velocity_noise_std_rps=0.0,
        accel_body_noise_std_mps2=0.0,
    )
    v_world = np.array([0.3, -0.2, 0.1], dtype=np.float64)
    omega_body = np.array([0.05, 0.0, 0.1], dtype=np.float64)
    accel = np.array([0.0, 0.0, 9.81], dtype=np.float64)
    gt = make_gt(
        linear_velocity_world_mps=v_world,
        angular_velocity_body_rps=omega_body,
        accel_body_mps2=accel,
    )
    vs = _estimate(config=cfg, gt=gt)
    np.testing.assert_array_equal(vs.nav.twist_world.linear_mps, v_world)
    np.testing.assert_array_equal(
        vs.nav.twist_body.angular_rps, omega_body
    )
    np.testing.assert_array_equal(vs.nav.accel_body_mps2, accel)


# ---------------------------------------------------------------------------
# Perturbación efectiva con stds > 0
# ---------------------------------------------------------------------------


def test_nonzero_noise_position_differs_from_ground_truth() -> None:
    gt = make_gt(
        position_enu_m=np.array([1.0, 2.0, 3.0], dtype=np.float64)
    )
    vs = _estimate(gt=gt)
    # Casi seguro distinto; pero usamos un margen no-igual para que el
    # test sea robusto a un seed que casualmente diera 0.
    diff = np.abs(vs.nav.pose.position_enu_m - gt.position_enu_m).sum()
    assert diff > 0.0


def test_nonzero_noise_quaternion_differs_from_ground_truth() -> None:
    """Stds > 0 -> la quaternion publicada no es exactamente la GT."""
    vs = _estimate()
    diff = np.abs(vs.nav.pose.orientation_q - Q_IDENTITY).sum()
    assert diff > 0.0


# ---------------------------------------------------------------------------
# Pass-through de campos discretos
# ---------------------------------------------------------------------------


def test_sensors_flight_mission_pass_through_unchanged() -> None:
    vs = _estimate()
    assert vs.flight.armed is True
    assert vs.mission.progress == 0.0
    assert "imu0" in vs.sensors.by_id


# ---------------------------------------------------------------------------
# No mutación de inputs (GT sellado)
# ---------------------------------------------------------------------------


def test_estimator_does_not_mutate_ground_truth_arrays() -> None:
    pos_before = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    q_before = Q_IDENTITY.copy()
    v_before = np.array([0.5, 0.0, -0.3], dtype=np.float64)
    gt = make_gt(
        position_enu_m=pos_before.copy(),
        orientation_q=q_before.copy(),
        linear_velocity_world_mps=v_before.copy(),
    )

    _estimate(gt=gt)

    np.testing.assert_array_equal(gt.position_enu_m, pos_before)
    np.testing.assert_array_equal(gt.orientation_q, q_before)
    np.testing.assert_array_equal(gt.linear_velocity_world_mps, v_before)


# ---------------------------------------------------------------------------
# Reusabilidad: múltiples calls dan muestras distintas
# ---------------------------------------------------------------------------


def test_multiple_estimate_calls_yield_independent_samples() -> None:
    """Cada call avanza el Generator interno; samples sucesivas
    deben diferir (no degenerar a un solo draw cacheado)."""
    estimator = NoisyGroundTruthEstimator(
        config=make_config(), random_source=make_rs()
    )
    vs1 = estimator.estimate(
        gt=make_gt(),
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=0,
    )
    vs2 = estimator.estimate(
        gt=make_gt(),
        sensors_health=make_health(),
        flight=make_flight(),
        mission=make_mission(),
        stamp_wall_ns=0,
    )
    diff = np.abs(
        vs1.nav.pose.position_enu_m - vs2.nav.pose.position_enu_m
    ).sum()
    assert diff > 0.0


def test_estimator_exposes_random_source_label() -> None:
    cfg = make_config(random_source_label="/x/y/z")
    estimator = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs()
    )
    assert estimator.random_source_label == "/x/y/z"


def test_estimator_exposes_config() -> None:
    cfg = make_config()
    estimator = NoisyGroundTruthEstimator(
        config=cfg, random_source=make_rs()
    )
    assert estimator.config is cfg


# ---------------------------------------------------------------------------
# Frame conventions: spawn con yaw 90° + sin ruido -> twist coherente
# ---------------------------------------------------------------------------


def test_zero_noise_yaw_90_twist_world_to_body_matches_transforms() -> None:
    """Con cero ruido y yaw 90°, twist_body.linear_mps debe igualar
    R_world_to_body(q_yaw) @ gt.linear_velocity_world_mps."""
    cfg = make_config(
        position_noise_std_m=0.0,
        orientation_noise_std_rad=0.0,
        linear_velocity_noise_std_mps=0.0,
        angular_velocity_noise_std_rps=0.0,
        accel_body_noise_std_mps2=0.0,
    )
    q_yaw = np.array(
        [np.sqrt(2.0) / 2.0, 0.0, 0.0, np.sqrt(2.0) / 2.0], dtype=np.float64
    )
    v_world = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    gt = make_gt(
        orientation_q=q_yaw.copy(),
        linear_velocity_world_mps=v_world,
    )
    vs = _estimate(config=cfg, gt=gt)
    expected_body = R_world_to_body(q_yaw) @ v_world
    np.testing.assert_allclose(
        vs.nav.twist_body.linear_mps, expected_body, atol=1e-15
    )


# ---------------------------------------------------------------------------
# Cov declarada inválida en el config -> no llegamos al estimador
# ---------------------------------------------------------------------------


def test_estimator_inherits_config_validation() -> None:
    """Las invariantes de la cov declarada las hace `NoisyGroundTruthConfig`.
    Este test documenta que llegar al estimador con cov inválida es
    imposible: el config ya rechazó."""
    bad = -np.eye(15, dtype=np.float64)
    with pytest.raises(ValueError, match="PSD"):
        make_config(declared_covariance_15x15=bad)
