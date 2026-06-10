"""Mensajes del modelo canónico de estado (T2.a.3 del roadmap Fase 1).

Materializa `docs/specs/state.md` §3 como dataclasses frozen con
validación por constructor. Cubre toda la jerarquía: pose / twist /
biases / navigation / sensor health / flight / mission / VehicleState.

Mismo patrón que `hal.messages.sensors` / `actuators`:

- Frozen dataclasses con `__post_init__` que valida shape/dtype/finitud
  y rangos.
- Arrays sellados (`flags.writeable=False`).
- `TypeError` para tipo/shape/dtype incorrecto, `ValueError` para rangos
  e invariantes semánticos.

Convenciones congeladas (state.md §2):

- Marco mundo: ENU.
- Marco cuerpo: FLU.
- Cuaternión: Hamilton `[w, x, y, z]` (validación de norma unitaria con
  tolerancia 1e-3, igual que `AttitudeCommand`).
- SI estricto.
- Tiempo en `int` nanosegundos.
- Precisión: `float64` para pose, twist, accel, biases, covarianzas.

Dependencias salientes: `hal.messages.sensors` para `SensorHealth` y
`SensorId` (`SensorHealthMap`). Dirección legítima: state -> hal (HAL es
fundación; state lo consume). hal NO importa state.

Decisiones cerradas aquí (sin ADR):

- Covarianza 15x15 validada como simétrica (tolerancia 1e-9) y PSD
  (eps 1e-12), mismas tolerancias que `core.uncertainty.estimate` para
  consistencia.
- `battery_pct` en `[0, 1]` cuando no es `None`.
- `MissionStatus.progress` en `[0, 1]`.
- `Goal.metadata` y `SensorHealthMap.by_id` deben ser Mappings inmutables
  (responsabilidad del publisher; las dataclasses no defienden contra
  mutación post-construcción del Mapping).

Fuera de alcance T2.a.3:

- `state.transforms` (helpers quaternion ↔ rotation matrix ↔ Euler,
  ENU↔NED, FLU↔FRD) — diferido a T2.a.5.
- `accel_world_mps2` opcional (state.md §8, evolución futura).
"""

from __future__ import annotations

# `SensorHealth`, `SensorId` y `Mapping` se importan a runtime (no en
# TYPE_CHECKING) para que `typing.get_type_hints` pueda resolver las
# anotaciones — `telemetry.serialization.from_json_dict` lo necesita para
# round-trip decoding.
from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

import numpy as np

from project_ghost.hal.messages import SensorHealth, SensorId  # noqa: TC001

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_VEC3_LEN: Final[int] = 3
_QUAT_LEN: Final[int] = 4
_QUAT_NORM_TOLERANCE: Final[float] = 1e-3
_COV_DIM: Final[int] = 15
_COV_SYMMETRY_TOL: Final[float] = 1e-9
_COV_PSD_EPS: Final[float] = 1e-12
_PERCENTAGE_MIN: Final[float] = 0.0
_PERCENTAGE_MAX: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Helpers internos de validación
# ---------------------------------------------------------------------------


def _validate_array(
    arr: Any,
    *,
    name: str,
    shape: tuple[int, ...] | None = None,
    ndim: int | None = None,
    dtype: Any = None,
    require_finite: bool = True,
) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} debe ser np.ndarray; recibido {type(arr).__name__}")
    if shape is not None and arr.shape != shape:
        raise TypeError(f"{name} debe tener shape {shape}; recibido {arr.shape}")
    if ndim is not None and arr.ndim != ndim:
        raise TypeError(f"{name} debe tener ndim {ndim}; recibido {arr.ndim}")
    if dtype is not None:
        expected = np.dtype(dtype)
        if arr.dtype != expected:
            raise TypeError(f"{name} debe tener dtype {expected}; recibido {arr.dtype}")
    if require_finite and not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contiene NaN o Inf")


def _seal(arr: np.ndarray) -> None:
    arr.setflags(write=False)


def _validate_unit_quaternion(q: np.ndarray, *, name: str) -> None:
    _validate_array(q, name=name, shape=(_QUAT_LEN,), dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if abs(norm - 1.0) > _QUAT_NORM_TOLERANCE:
        raise ValueError(f"{name} debe ser unit (tolerancia {_QUAT_NORM_TOLERANCE}); norm={norm}")


def _validate_covariance(c: np.ndarray, *, name: str = "covariance_15x15") -> None:
    _validate_array(c, name=name, shape=(_COV_DIM, _COV_DIM), dtype=np.float64)
    asymmetry = float(np.max(np.abs(c - c.T)))
    if asymmetry > _COV_SYMMETRY_TOL:
        raise ValueError(
            f"{name} no es simétrica (max asimetría {asymmetry}, tolerancia {_COV_SYMMETRY_TOL})"
        )
    # PSD via eigvalsh sobre simétrica (tomada como (c + c.T) / 2 para reducir
    # ruido en la simetría tras pasar el chequeo).
    eigvals = np.linalg.eigvalsh((c + c.T) / 2.0)
    min_eig = float(eigvals.min())
    if min_eig < -_COV_PSD_EPS:
        raise ValueError(f"{name} no es PSD (eigenvalor mínimo {min_eig}, eps {_COV_PSD_EPS})")


# ---------------------------------------------------------------------------
# Pose / Twist / IMUBiases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pose:
    """Pose 6-DoF en marco mundo (state.md §3).

    `position_enu_m` en ENU; `orientation_q` Hamilton w-first, unit norm
    con tolerancia 1e-3.
    """

    position_enu_m: np.ndarray
    orientation_q: np.ndarray

    def __post_init__(self) -> None:
        _validate_array(
            self.position_enu_m,
            name="position_enu_m",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_unit_quaternion(self.orientation_q, name="orientation_q")
        _seal(self.position_enu_m)
        _seal(self.orientation_q)


TwistFrame = Literal["world", "body"]


@dataclass(frozen=True)
class Twist:
    """Velocidad lineal + angular en un frame declarado (state.md §3)."""

    linear_mps: np.ndarray
    angular_rps: np.ndarray
    frame: TwistFrame

    def __post_init__(self) -> None:
        _validate_array(
            self.linear_mps,
            name="linear_mps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_array(
            self.angular_rps,
            name="angular_rps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        if self.frame not in ("world", "body"):
            raise ValueError(f"frame debe ser 'world' o 'body'; recibido {self.frame!r}")
        _seal(self.linear_mps)
        _seal(self.angular_rps)


@dataclass(frozen=True)
class IMUBiases:
    """Biases del IMU (accel + gyro) en frame cuerpo FLU."""

    accel_bias_mps2: np.ndarray
    gyro_bias_rps: np.ndarray

    def __post_init__(self) -> None:
        _validate_array(
            self.accel_bias_mps2,
            name="accel_bias_mps2",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_array(
            self.gyro_bias_rps,
            name="gyro_bias_rps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _seal(self.accel_bias_mps2)
        _seal(self.gyro_bias_rps)


# ---------------------------------------------------------------------------
# NavigationState
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NavigationState:
    """Estado navegacional canónico (state.md §3).

    `twist_body` es redundante por conveniencia (state.md §3): el frame
    debe ser ``"body"``; `twist_world` debe ser ``"world"``.

    `covariance_15x15` orden: ``[p(3), v(3), q_tangent(3), b_a(3), b_g(3)]``.
    Puede ser `None` cuando no se estima (Fase 1 con groundtruth) o cuando
    no se confía. Si está presente: simétrica (tol 1e-9) y PSD (eps 1e-12).
    """

    pose: Pose
    twist_world: Twist
    twist_body: Twist
    accel_body_mps2: np.ndarray
    imu_biases: IMUBiases
    covariance_15x15: np.ndarray | None

    def __post_init__(self) -> None:
        if self.twist_world.frame != "world":
            raise ValueError(
                f"twist_world.frame debe ser 'world'; recibido {self.twist_world.frame!r}"
            )
        if self.twist_body.frame != "body":
            raise ValueError(
                f"twist_body.frame debe ser 'body'; recibido {self.twist_body.frame!r}"
            )
        _validate_array(
            self.accel_body_mps2,
            name="accel_body_mps2",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        if self.covariance_15x15 is not None:
            _validate_covariance(self.covariance_15x15)
            _seal(self.covariance_15x15)
        _seal(self.accel_body_mps2)


# ---------------------------------------------------------------------------
# SensorHealthMap
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorHealthMap:
    """Salud por sensor en el momento del snapshot.

    `by_id` debe ser un Mapping inmutable (e.g. `MappingProxyType`)
    construido por el publisher. La dataclass no defiende contra mutación
    post-construcción del Mapping.
    """

    by_id: Mapping[SensorId, SensorHealth]


# ---------------------------------------------------------------------------
# FlightStatus / FlightMode
# ---------------------------------------------------------------------------


class FlightMode(StrEnum):
    """Modo de vuelo del autopilot (state.md §3).

    Modificar requiere ADR (catálogo cerrado, mismo principio que
    `EventType` y `RejectReason`).
    """

    INIT = "init"
    MANUAL = "manual"
    STABILIZE = "stabilize"
    OFFBOARD = "offboard"
    RTL = "rtl"
    LAND = "land"
    KILL = "kill"


@dataclass(frozen=True)
class FlightStatus:
    """Estado del vuelo (state.md §3).

    `battery_pct` en `[0, 1]` cuando no es `None`. `error_flags` es un
    bitfield no-negativo cuya semántica vive en `core.errors` (cuando
    exista; por ahora opaco).
    """

    armed: bool
    flight_mode: FlightMode
    battery_v: float | None
    battery_pct: float | None
    error_flags: int

    def __post_init__(self) -> None:
        if self.battery_v is not None and not np.isfinite(self.battery_v):
            raise ValueError(f"battery_v debe ser finito; recibido {self.battery_v}")
        if self.battery_pct is not None:
            if not np.isfinite(self.battery_pct):
                raise ValueError(f"battery_pct debe ser finito; recibido {self.battery_pct}")
            if not _PERCENTAGE_MIN <= self.battery_pct <= _PERCENTAGE_MAX:
                raise ValueError(
                    f"battery_pct debe estar en [{_PERCENTAGE_MIN}, "
                    f"{_PERCENTAGE_MAX}]; recibido {self.battery_pct}"
                )
        if self.error_flags < 0:
            raise ValueError(f"error_flags debe ser >= 0; recibido {self.error_flags}")


# ---------------------------------------------------------------------------
# MissionStatus / MissionMode / Goal
# ---------------------------------------------------------------------------


class MissionMode(StrEnum):
    """Modo de misión (state.md §3). Modificar requiere ADR."""

    IDLE = "idle"
    EXPLORE = "explore"
    NAVIGATE = "navigate"
    RETURN = "return"
    DONE = "done"
    ABORT = "abort"


@dataclass(frozen=True)
class Goal:
    """Goal de navegación con posición y/o yaw, plus metadata opaca."""

    position_enu_m: np.ndarray | None
    yaw_rad: float | None
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.position_enu_m is not None:
            _validate_array(
                self.position_enu_m,
                name="position_enu_m",
                shape=(_VEC3_LEN,),
                dtype=np.float64,
            )
            _seal(self.position_enu_m)
        if self.yaw_rad is not None and not np.isfinite(self.yaw_rad):
            raise ValueError(f"yaw_rad debe ser finito; recibido {self.yaw_rad}")


@dataclass(frozen=True)
class MissionStatus:
    """Estado de la misión (state.md §3).

    `progress` en `[0, 1]`; semántica específica por misión.
    `started_sim_ns >= 0` cuando no es `None`.
    """

    mode: MissionMode
    current_goal: Goal | None
    progress: float
    started_sim_ns: int | None

    def __post_init__(self) -> None:
        if not np.isfinite(self.progress):
            raise ValueError(f"progress debe ser finito; recibido {self.progress}")
        if not _PERCENTAGE_MIN <= self.progress <= _PERCENTAGE_MAX:
            raise ValueError(
                f"progress debe estar en [{_PERCENTAGE_MIN}, "
                f"{_PERCENTAGE_MAX}]; recibido {self.progress}"
            )
        if self.started_sim_ns is not None and self.started_sim_ns < 0:
            raise ValueError(f"started_sim_ns debe ser >= 0; recibido {self.started_sim_ns}")


# ---------------------------------------------------------------------------
# VehicleState
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VehicleState:
    """Estado canónico del vehículo (state.md §3).

    Único struct top-level que describe el dron. Frozen; cada ciclo
    produce un nuevo `VehicleState`. **No contiene datos crudos**
    (imágenes, IMU samples, point clouds) — esos viajan por sus canales
    `/sensors/...`.
    """

    stamp_sim_ns: int
    stamp_wall_ns: int
    nav: NavigationState
    sensors: SensorHealthMap
    flight: FlightStatus
    mission: MissionStatus
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.stamp_sim_ns < 0:
            raise ValueError(f"stamp_sim_ns debe ser >= 0; recibido {self.stamp_sim_ns}")
        if self.stamp_wall_ns < 0:
            raise ValueError(f"stamp_wall_ns debe ser >= 0; recibido {self.stamp_wall_ns}")
        if self.schema_version < 1:
            raise ValueError(f"schema_version debe ser >= 1; recibido {self.schema_version}")


__all__ = [
    "FlightMode",
    "FlightStatus",
    "Goal",
    "IMUBiases",
    "MissionMode",
    "MissionStatus",
    "NavigationState",
    "Pose",
    "SensorHealthMap",
    "Twist",
    "TwistFrame",
    "VehicleState",
]
