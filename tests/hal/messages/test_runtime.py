"""Tests de `hal.messages.runtime` (T2.a.4).

Cubre Capabilities, ScenarioSpec, GroundTruth y StepReport.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.hal import HAL_PROTOCOL_VERSION
from project_ghost.hal.messages import (
    ActuatorLevel,
    Capabilities,
    GroundTruth,
    ScenarioSpec,
    StepReport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IDENTITY_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _capabilities(**overrides: object) -> Capabilities:
    defaults: dict[str, object] = {
        "hal_version": HAL_PROTOCOL_VERSION,
        "sensor_ids": ("imu0", "cam_front"),
        "actuator_levels": (ActuatorLevel.DIRECT_MOTOR,),
        "has_ground_truth": True,
        "synchronous_step": True,
        "deterministic": True,
        "supports_replay": False,
        "extensions": MappingProxyType({}),
    }
    defaults.update(overrides)
    return Capabilities(**defaults)  # type: ignore[arg-type]


def _ground_truth(stamp: int = 0) -> GroundTruth:
    return GroundTruth(
        stamp_sim_ns=stamp,
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_IDENTITY_Q.copy(),
        linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
        angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_capabilities_valid_construction() -> None:
    caps = _capabilities()
    assert caps.hal_version == HAL_PROTOCOL_VERSION
    assert caps.has_ground_truth is True


def test_capabilities_is_frozen() -> None:
    caps = _capabilities()
    with pytest.raises(FrozenInstanceError):
        caps.hal_version = 2  # type: ignore[misc]


def test_capabilities_rejects_zero_version() -> None:
    with pytest.raises(ValueError, match="hal_version"):
        _capabilities(hal_version=0)


def test_capabilities_rejects_list_sensor_ids() -> None:
    with pytest.raises(TypeError, match="sensor_ids"):
        _capabilities(sensor_ids=["imu0"])


def test_capabilities_rejects_list_actuator_levels() -> None:
    with pytest.raises(TypeError, match="actuator_levels"):
        _capabilities(actuator_levels=[ActuatorLevel.DIRECT_MOTOR])


def test_capabilities_rejects_duplicate_sensor_ids() -> None:
    with pytest.raises(ValueError, match="duplicado"):
        _capabilities(sensor_ids=("imu0", "imu0"))


def test_capabilities_rejects_duplicate_actuator_levels() -> None:
    with pytest.raises(ValueError, match="duplicado"):
        _capabilities(
            actuator_levels=(
                ActuatorLevel.DIRECT_MOTOR,
                ActuatorLevel.DIRECT_MOTOR,
            )
        )


def test_capabilities_allows_empty_sensor_ids_and_levels() -> None:
    """Backend sin sensores ni actuadores (e.g. mock degenerado)."""
    caps = _capabilities(sensor_ids=(), actuator_levels=())
    assert caps.sensor_ids == ()
    assert caps.actuator_levels == ()


# ---------------------------------------------------------------------------
# ScenarioSpec
# ---------------------------------------------------------------------------


def test_scenario_spec_valid_construction() -> None:
    spec = ScenarioSpec(
        world_id="empty_room",
        vehicle_id="x500",
        duration_ns=60_000_000_000,
        extensions=MappingProxyType({}),
    )
    assert spec.world_id == "empty_room"
    assert spec.duration_ns == 60_000_000_000


def test_scenario_spec_duration_optional() -> None:
    spec = ScenarioSpec(
        world_id="empty_room",
        vehicle_id="x500",
        duration_ns=None,
        extensions=MappingProxyType({}),
    )
    assert spec.duration_ns is None


def test_scenario_spec_rejects_empty_world_id() -> None:
    with pytest.raises(ValueError, match="world_id"):
        ScenarioSpec(
            world_id="",
            vehicle_id="x500",
            duration_ns=None,
            extensions=MappingProxyType({}),
        )


def test_scenario_spec_rejects_empty_vehicle_id() -> None:
    with pytest.raises(ValueError, match="vehicle_id"):
        ScenarioSpec(
            world_id="empty_room",
            vehicle_id="",
            duration_ns=None,
            extensions=MappingProxyType({}),
        )


def test_scenario_spec_rejects_nonpositive_duration() -> None:
    with pytest.raises(ValueError, match="duration_ns"):
        ScenarioSpec(
            world_id="empty_room",
            vehicle_id="x500",
            duration_ns=0,
            extensions=MappingProxyType({}),
        )


# ---------------------------------------------------------------------------
# GroundTruth
# ---------------------------------------------------------------------------


def test_ground_truth_valid_construction() -> None:
    gt = _ground_truth(stamp=1_000)
    assert gt.stamp_sim_ns == 1_000


def test_ground_truth_rejects_negative_stamp() -> None:
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        GroundTruth(
            stamp_sim_ns=-1,
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
            linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )


def test_ground_truth_rejects_non_unit_quaternion() -> None:
    with pytest.raises(ValueError, match="unit"):
        GroundTruth(
            stamp_sim_ns=0,
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float64),
            linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )


def test_ground_truth_rejects_nan_position() -> None:
    with pytest.raises(ValueError, match="NaN"):
        GroundTruth(
            stamp_sim_ns=0,
            position_enu_m=np.array([0.0, np.nan, 0.0], dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
            linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )


def test_ground_truth_rejects_wrong_velocity_shape() -> None:
    with pytest.raises(TypeError, match="linear_velocity_world_mps"):
        GroundTruth(
            stamp_sim_ns=0,
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
            linear_velocity_world_mps=np.zeros(4, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )


def test_ground_truth_all_arrays_are_sealed() -> None:
    gt = _ground_truth()
    for arr in (
        gt.position_enu_m,
        gt.orientation_q,
        gt.linear_velocity_world_mps,
        gt.angular_velocity_body_rps,
        gt.accel_body_mps2,
    ):
        assert not arr.flags.writeable


# ---------------------------------------------------------------------------
# StepReport
# ---------------------------------------------------------------------------


def test_step_report_valid_construction() -> None:
    report = StepReport(dt_advanced_ns=1_000_000, extensions=MappingProxyType({}))
    assert report.dt_advanced_ns == 1_000_000


def test_step_report_zero_dt_allowed() -> None:
    """duration_ns alcanzado puede dejar el step en 0."""
    report = StepReport(dt_advanced_ns=0, extensions=MappingProxyType({}))
    assert report.dt_advanced_ns == 0


def test_step_report_rejects_negative_dt() -> None:
    with pytest.raises(ValueError, match="dt_advanced_ns"):
        StepReport(dt_advanced_ns=-1, extensions=MappingProxyType({}))
