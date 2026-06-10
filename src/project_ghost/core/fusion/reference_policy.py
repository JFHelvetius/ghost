"""Reference fusion policy: ``LinearMotionOracleFusionPolicy`` (ADR-0028).

Policy mínima documentada que valida el contrato
``SensorFusionPolicy``. **No es estimación.** Ignora
``sensor_samples`` y computa pose por propagación lineal desde una
configuración conocida — equivalente a "kill-only" en el lado de
actuación.

Útil para sim deterministic donde la trayectoria verdadera es
conocida. Estimadores reales (KF, EKF, UKF, factor graph) implementan
el mismo Protocol consumiendo ``sensor_samples`` y produciendo
``belief`` con covariance real.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np

from project_ghost.hal.messages.sensors import SensorHealth
from project_ghost.state.messages import (
    FlightMode,
    FlightStatus,
    IMUBiases,
    MissionMode,
    MissionStatus,
    NavigationState,
    Pose,
    SensorHealthMap,
    Twist,
    VehicleState,
)

from .types import FusionResult, compute_fusion_input_sha256

if TYPE_CHECKING:
    from .types import FusionInput


_Q_IDENTITY: Final[np.ndarray] = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


class LinearMotionOracleFusionPolicy:
    """Oracle fusion: propaga linealmente desde origen configurado.

    Parameters:

    - ``initial_position_enu_m``: pose inicial en frame ENU.
    - ``velocity_world_mps``: velocidad constante asumida en frame
      world.
    - ``start_stamp_sim_ns``: instante referencia (``t=0`` lógico).
    - ``covariance_diag``: varianza diagonal uniforme para la
      covariance reportada en el belief (> 0).

    ``fusion_policy_id`` incluye los parámetros en su nombre para
    que dos instancias con configuración distinta produzcan records
    distinguibles en MCAP.
    """

    POLICY_ID_BASE: ClassVar[str] = "linear_motion_oracle_v1"

    def __init__(
        self,
        *,
        initial_position_enu_m: np.ndarray,
        velocity_world_mps: np.ndarray,
        start_stamp_sim_ns: int,
        covariance_diag: float,
    ) -> None:
        if (
            not isinstance(initial_position_enu_m, np.ndarray)
            or initial_position_enu_m.shape != (3,)
            or initial_position_enu_m.dtype != np.float64
        ):
            raise ValueError("initial_position_enu_m must be float64 ndarray shape (3,)")
        if (
            not isinstance(velocity_world_mps, np.ndarray)
            or velocity_world_mps.shape != (3,)
            or velocity_world_mps.dtype != np.float64
        ):
            raise ValueError("velocity_world_mps must be float64 ndarray shape (3,)")
        if start_stamp_sim_ns < 0:
            raise ValueError(f"start_stamp_sim_ns must be >= 0; got {start_stamp_sim_ns}")
        if not (covariance_diag > 0.0 and np.isfinite(covariance_diag)):
            raise ValueError(f"covariance_diag must be finite and > 0; got {covariance_diag}")

        self._initial_position: np.ndarray = initial_position_enu_m.astype(np.float64, copy=True)
        self._velocity: np.ndarray = velocity_world_mps.astype(np.float64, copy=True)
        self._start_stamp: int = start_stamp_sim_ns
        self._covariance_diag: float = float(covariance_diag)
        # Pin parameters into the policy_id so MCAP records are
        # mechanically distinguishable.
        self._policy_id: str = f"{self.POLICY_ID_BASE}_cov{int(covariance_diag * 1_000_000):d}"

    @property
    def fusion_policy_id(self) -> str:
        return self._policy_id

    @property
    def initial_position(self) -> np.ndarray:
        return self._initial_position

    @property
    def velocity_world(self) -> np.ndarray:
        return self._velocity

    def fuse(self, fusion_input: FusionInput) -> FusionResult:
        dt_s = (fusion_input.target_stamp_sim_ns - self._start_stamp) / 1.0e9
        position = (self._initial_position + self._velocity * dt_s).astype(np.float64, copy=True)
        pose = Pose(
            position_enu_m=position,
            orientation_q=_Q_IDENTITY.copy(),
        )
        twist_world = Twist(
            linear_mps=self._velocity.astype(np.float64, copy=True),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="world",
        )
        twist_body = Twist(
            linear_mps=self._velocity.astype(np.float64, copy=True),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="body",
        )
        biases = IMUBiases(
            accel_bias_mps2=np.zeros(3, dtype=np.float64),
            gyro_bias_rps=np.zeros(3, dtype=np.float64),
        )
        covariance = np.eye(15, dtype=np.float64) * self._covariance_diag
        nav = NavigationState(
            pose=pose,
            twist_world=twist_world,
            twist_body=twist_body,
            accel_body_mps2=np.zeros(3, dtype=np.float64),
            imu_biases=biases,
            covariance_15x15=covariance,
        )
        belief = VehicleState(
            stamp_sim_ns=fusion_input.target_stamp_sim_ns,
            stamp_wall_ns=0,
            nav=nav,
            sensors=SensorHealthMap(by_id=MappingProxyType({"imu0": SensorHealth.OK})),
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
        )
        return FusionResult(
            belief=belief,
            fusion_input_sha256=compute_fusion_input_sha256(fusion_input),
            fusion_policy_id=self._policy_id,
        )


__all__ = ["LinearMotionOracleFusionPolicy"]
