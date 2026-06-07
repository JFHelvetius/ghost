"""Helpers compartidos para tests de `project_ghost.estimation`.

Centraliza la construcción de:

- ``GroundTruth`` con defaults razonables (spawn estático).
- ``SensorHealthMap`` / ``FlightStatus`` / ``MissionStatus``.
- ``NoisyGroundTruthConfig`` con covarianza declarada PSD.
- ``RandomSource`` con seed conocido para tests deterministas.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from project_ghost.core.clock.random_source import RandomSourceImpl
from project_ghost.estimation import NoisyGroundTruthConfig
from project_ghost.hal.messages import GroundTruth, SensorHealth
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    MissionMode,
    MissionStatus,
    SensorHealthMap,
)

if TYPE_CHECKING:
    from project_ghost.core.clock.types import RandomSource


Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def make_gt(
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
            position_enu_m
            if position_enu_m is not None
            else np.zeros(3, dtype=np.float64)
        ),
        orientation_q=(
            orientation_q if orientation_q is not None else Q_IDENTITY.copy()
        ),
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
            accel_body_mps2
            if accel_body_mps2 is not None
            else np.zeros(3, dtype=np.float64)
        ),
    )


def make_flight() -> FlightStatus:
    return FlightStatus(
        armed=True,
        flight_mode=FlightMode.OFFBOARD,
        battery_v=12.4,
        battery_pct=0.85,
        error_flags=0,
    )


def make_mission() -> MissionStatus:
    return MissionStatus(
        mode=MissionMode.IDLE,
        current_goal=None,
        progress=0.0,
        started_sim_ns=None,
    )


def make_health() -> SensorHealthMap:
    return SensorHealthMap(
        by_id=MappingProxyType(
            {
                "imu0": SensorHealth.OK,
                "cam_front": SensorHealth.OK,
            }
        )
    )


def make_declared_cov(scale: float = 1e-3) -> np.ndarray:
    """Cov 15x15 PSD diagonal. ``scale`` controla la magnitud."""
    return np.eye(15, dtype=np.float64) * scale


def make_config(
    *,
    position_noise_std_m: float = 0.05,
    orientation_noise_std_rad: float = 0.01,
    linear_velocity_noise_std_mps: float = 0.02,
    angular_velocity_noise_std_rps: float = 0.005,
    accel_body_noise_std_mps2: float = 0.1,
    declared_covariance_15x15: np.ndarray | None = None,
    random_source_label: str = "/estimation/noisy_gt",
) -> NoisyGroundTruthConfig:
    return NoisyGroundTruthConfig(
        position_noise_std_m=position_noise_std_m,
        orientation_noise_std_rad=orientation_noise_std_rad,
        linear_velocity_noise_std_mps=linear_velocity_noise_std_mps,
        angular_velocity_noise_std_rps=angular_velocity_noise_std_rps,
        accel_body_noise_std_mps2=accel_body_noise_std_mps2,
        declared_covariance_15x15=(
            declared_covariance_15x15
            if declared_covariance_15x15 is not None
            else make_declared_cov()
        ),
        random_source_label=random_source_label,
    )


def make_rs(seed: int = 0xC0FFEE) -> RandomSource:
    return RandomSourceImpl(seed=seed, label="/")
