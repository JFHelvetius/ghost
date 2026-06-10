"""Mensajes del sub-API de actuadores (T2.a.2 del roadmap Fase 1).

Materializa `docs/specs/actuators.md` §2-§5: jerarquía de comandos
(`ActuatorCommand` Protocol + 6 niveles concretos), ack model
(`CommandAck`, `RejectReason`), `SafetyEnvelope` y `ActuatorSpec`.

Mismo patrón que `hal.messages.sensors`:

- Frozen dataclasses con `__post_init__` que valida shape/dtype/finitud
  y rangos físicos.
- Arrays sellados (`flags.writeable=False`) cumpliendo `hal.md` §3.5.
- `TypeError` para tipo/shape/dtype incorrecto, `ValueError` para rangos.

Decisiones de diseño cerradas aquí:

- Cada `*Command` concreto fija su `level` mediante
  `field(default=..., init=False)`: el constructor no acepta override y
  el atributo es inmutable post-construcción. Esto evita la inconsistencia
  `DirectMotorCommand(level=ActuatorLevel.ATTITUDE)`.
- Quaternions se validan con tolerancia de unit-norm 1e-3 (loose enough
  para ruido de composición de rotaciones, estricto para detectar bugs).
- `SafetyEnvelope.geofence_polygon` es `tuple[tuple[float, float], ...]`,
  no `list` — uncertainty.md §10.
- `CommandAck` invariante: `accepted=True XOR reason is not None`.

Fuera de alcance T2.a.2:

- `TorqueCommand` / `WrenchCommand` para control no lineal
  (actuators.md §8, "evolución futura").
- Mezclador X/+/H/octo configurable en `actuators.mixer` (T8).
- Comandos de actuadores auxiliares (gimbal, payload release) en sink
  separado (actuators.md §8).
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Final, Literal, Protocol, runtime_checkable

import numpy as np

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ActuatorLevel(IntEnum):
    """Niveles de comando, ordenados de bajo a alto. Reflejan PX4 offboard.

    Ver actuators.md §2 para mapeo a fases del roadmap.
    """

    DIRECT_MOTOR = 0
    BODY_RATE = 1
    ATTITUDE = 2
    VELOCITY = 3
    POSITION = 4
    TRAJECTORY = 5


class RejectReason(StrEnum):
    """Razones canónicas para `CommandAck.accepted=False` (actuators.md §3).

    Modificar requiere ADR (catálogo cerrado, mismo principio que
    `EventType` en `events/`).
    """

    INVALID_VALUE = "invalid_value"
    OUT_OF_RANGE = "out_of_range"
    STALE_STAMP = "stale_stamp"
    NOT_ARMED = "not_armed"
    UNSUPPORTED_LEVEL = "unsupported_level"
    SAFETY_VIOLATION = "safety_violation"
    BACKEND_BUSY = "backend_busy"


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

# Tolerancia para chequeo de norma unitaria de quaterniones.
_QUAT_NORM_TOLERANCE: Final[float] = 1e-3
_THRUST_MIN: Final[float] = 0.0
_THRUST_MAX: Final[float] = 1.0
_QUAT_LEN: Final[int] = 4
_VEC3_LEN: Final[int] = 3


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


def _check_thrust(value: float, *, name: str = "thrust_normalized") -> None:
    if not _THRUST_MIN <= value <= _THRUST_MAX:
        raise ValueError(f"{name} debe estar en [{_THRUST_MIN}, {_THRUST_MAX}]; recibido {value}")


def _check_stamp_and_schema(stamp_ns: int, schema_version: int) -> None:
    if stamp_ns < 0:
        raise ValueError(f"stamp_ns debe ser >= 0; recibido {stamp_ns}")
    if schema_version < 1:
        raise ValueError(f"schema_version debe ser >= 1; recibido {schema_version}")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ActuatorCommand(Protocol):
    """Atributos comunes a todo comando de actuador (actuators.md §2).

    Declarados como `@property` (read-only per PEP 544): las dataclasses
    concretas (`DirectMotorCommand` etc.) son `frozen=True`, por lo que
    sus atributos son inmutables. Un Protocol con atributos settable
    (`level: ActuatorLevel`) sería incompatible con frozen, así que el
    Protocol declara la variante read-only — cualquier impl (frozen o
    no) satisface.
    """

    @property
    def level(self) -> ActuatorLevel: ...
    @property
    def stamp_ns(self) -> int: ...
    @property
    def schema_version(self) -> int: ...


# ---------------------------------------------------------------------------
# Commands — nivel 0..5
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectMotorCommand:
    """Comando nivel 0: throttle por motor `[0, 1]` (actuators.md §2).

    `throttle` puede tener cualquier longitud >= 1 (API es N-rotor
    agnóstico per spec §7).
    """

    throttle: np.ndarray
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.DIRECT_MOTOR, init=False)

    def __post_init__(self) -> None:
        _validate_array(self.throttle, name="throttle", ndim=1, dtype=np.float64)
        if self.throttle.shape[0] < 1:
            raise ValueError(f"throttle debe tener al menos un motor; shape={self.throttle.shape}")
        if bool(np.any(self.throttle < _THRUST_MIN)) or bool(np.any(self.throttle > _THRUST_MAX)):
            raise ValueError(
                f"throttle fuera de [{_THRUST_MIN}, {_THRUST_MAX}]; "
                f"min={float(self.throttle.min())}, max={float(self.throttle.max())}"
            )
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.throttle)


@dataclass(frozen=True)
class BodyRateCommand:
    """Comando nivel 1: body rates (rps) + thrust normalizado."""

    body_rates_rps: np.ndarray
    thrust_normalized: float
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.BODY_RATE, init=False)

    def __post_init__(self) -> None:
        _validate_array(
            self.body_rates_rps,
            name="body_rates_rps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _check_thrust(self.thrust_normalized)
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.body_rates_rps)


@dataclass(frozen=True)
class AttitudeCommand:
    """Comando nivel 2: cuaternión target Hamilton w-first + thrust."""

    q_target: np.ndarray
    thrust_normalized: float
    yaw_rate_rps: float | None = None
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.ATTITUDE, init=False)

    def __post_init__(self) -> None:
        _validate_array(self.q_target, name="q_target", shape=(_QUAT_LEN,), dtype=np.float64)
        # Norma unit (tolerancia loose para absorber ruido numérico).
        norm = float(np.linalg.norm(self.q_target))
        if abs(norm - 1.0) > _QUAT_NORM_TOLERANCE:
            raise ValueError(
                f"q_target debe ser unit (tolerancia {_QUAT_NORM_TOLERANCE}); norm={norm}"
            )
        _check_thrust(self.thrust_normalized)
        if self.yaw_rate_rps is not None and not np.isfinite(self.yaw_rate_rps):
            raise ValueError(f"yaw_rate_rps debe ser finito; recibido {self.yaw_rate_rps}")
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.q_target)


VelocityFrame = Literal["world", "body"]


@dataclass(frozen=True)
class VelocityCommand:
    """Comando nivel 3: velocidad + yaw opcional."""

    velocity_mps: np.ndarray
    frame: VelocityFrame
    yaw_rad: float | None = None
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.VELOCITY, init=False)

    def __post_init__(self) -> None:
        _validate_array(
            self.velocity_mps,
            name="velocity_mps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        if self.frame not in ("world", "body"):
            raise ValueError(f"frame debe ser 'world' o 'body'; recibido {self.frame!r}")
        if self.yaw_rad is not None and not np.isfinite(self.yaw_rad):
            raise ValueError(f"yaw_rad debe ser finito; recibido {self.yaw_rad}")
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.velocity_mps)


@dataclass(frozen=True)
class PositionCommand:
    """Comando nivel 4: posición ENU + yaw opcional."""

    position_enu_m: np.ndarray
    yaw_rad: float | None = None
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.POSITION, init=False)

    def __post_init__(self) -> None:
        _validate_array(
            self.position_enu_m,
            name="position_enu_m",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        if self.yaw_rad is not None and not np.isfinite(self.yaw_rad):
            raise ValueError(f"yaw_rad debe ser finito; recibido {self.yaw_rad}")
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.position_enu_m)


_MIN_TRAJECTORY_SAMPLES: Final[int] = 2


@dataclass(frozen=True)
class TrajectoryCommand:
    """Comando nivel 5: trayectoria parametrizada por sample times + setpoints.

    Mínimo 2 muestras (de lo contrario no es trayectoria). `sample_times_ns`
    debe ser estrictamente monotónico creciente.
    """

    sample_times_ns: np.ndarray
    positions_enu_m: np.ndarray
    yaws_rad: np.ndarray | None = None
    stamp_ns: int = 0
    schema_version: int = 1
    level: ActuatorLevel = field(default=ActuatorLevel.TRAJECTORY, init=False)

    def __post_init__(self) -> None:
        _validate_array(
            self.sample_times_ns,
            name="sample_times_ns",
            ndim=1,
            dtype=np.int64,
            require_finite=False,  # int64 no admite NaN
        )
        n = self.sample_times_ns.shape[0]
        if n < _MIN_TRAJECTORY_SAMPLES:
            raise ValueError(
                f"sample_times_ns debe tener al menos {_MIN_TRAJECTORY_SAMPLES} "
                f"muestras; recibido {n}"
            )
        if not bool(np.all(np.diff(self.sample_times_ns) > 0)):
            raise ValueError("sample_times_ns debe ser estrictamente monotónico creciente")
        if bool(np.any(self.sample_times_ns < 0)):
            raise ValueError("sample_times_ns no puede tener valores negativos")
        _validate_array(
            self.positions_enu_m,
            name="positions_enu_m",
            shape=(n, _VEC3_LEN),
            dtype=np.float64,
        )
        if self.yaws_rad is not None:
            _validate_array(self.yaws_rad, name="yaws_rad", shape=(n,), dtype=np.float64)
            _seal(self.yaws_rad)
        _check_stamp_and_schema(self.stamp_ns, self.schema_version)
        _seal(self.sample_times_ns)
        _seal(self.positions_enu_m)


# ---------------------------------------------------------------------------
# Ack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandAck:
    """Acuse de envío de comando (actuators.md §3).

    Invariante: ``accepted XOR reason is not None``. Un ack con
    ``accepted=True`` no puede llevar reason; uno con ``accepted=False``
    debe llevar reason.
    """

    accepted: bool
    reason: RejectReason | None
    applied_stamp_ns: int
    saturated: bool
    extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError(
                f"CommandAck(accepted=True) no puede llevar reason; recibido {self.reason!r}"
            )
        if not self.accepted and self.reason is None:
            raise ValueError("CommandAck(accepted=False) debe llevar reason")
        if self.applied_stamp_ns < 0:
            raise ValueError(f"applied_stamp_ns debe ser >= 0; recibido {self.applied_stamp_ns}")


# ---------------------------------------------------------------------------
# SafetyEnvelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyEnvelope:
    """Límites operativos aplicados en frontera del sink (actuators.md §5).

    Configurada por vehículo/misión. `geofence_polygon` es tupla de tuplas
    (no `list`) por la regla de colecciones estables.
    """

    max_tilt_rad: float
    max_climb_rate_mps: float
    max_horiz_speed_mps: float
    max_yaw_rate_rps: float
    altitude_min_m: float
    altitude_max_m: float
    geofence_polygon: tuple[tuple[float, float], ...] | None
    command_timeout_ns: int
    require_arm: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_tilt_rad",
            "max_climb_rate_mps",
            "max_horiz_speed_mps",
            "max_yaw_rate_rps",
        ):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} debe ser > 0; recibido {value}")
        if self.altitude_max_m <= self.altitude_min_m:
            raise ValueError(
                f"altitude_max_m ({self.altitude_max_m}) debe ser > "
                f"altitude_min_m ({self.altitude_min_m})"
            )
        if self.command_timeout_ns <= 0:
            raise ValueError(f"command_timeout_ns debe ser > 0; recibido {self.command_timeout_ns}")
        if self.geofence_polygon is not None:
            if not isinstance(self.geofence_polygon, tuple):
                raise TypeError(
                    "geofence_polygon debe ser tuple (uncertainty.md §10); "
                    f"recibido {type(self.geofence_polygon).__name__}"
                )
            if len(self.geofence_polygon) < _MIN_TRAJECTORY_SAMPLES + 1:
                # Un polígono necesita al menos 3 vértices.
                raise ValueError(
                    f"geofence_polygon debe tener al menos 3 vértices; "
                    f"recibido {len(self.geofence_polygon)}"
                )


# ---------------------------------------------------------------------------
# ActuatorSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActuatorSpec:
    """Configuración estática del sink (referenciada por hal.md §2)."""

    actuator_id: str
    supported_levels: tuple[ActuatorLevel, ...]
    safety_envelope: SafetyEnvelope

    def __post_init__(self) -> None:
        if not self.actuator_id:
            raise ValueError("actuator_id no puede ser vacío")
        if not isinstance(self.supported_levels, tuple):
            raise TypeError(
                "supported_levels debe ser tuple (uncertainty.md §10); "
                f"recibido {type(self.supported_levels).__name__}"
            )
        if len(self.supported_levels) < 1:
            raise ValueError("supported_levels no puede ser vacío")
        # Detectar duplicados con conteo (no usar set, uncertainty.md §10).
        seen: list[ActuatorLevel] = []
        for lvl in self.supported_levels:
            if lvl in seen:
                raise ValueError(f"supported_levels tiene duplicado: {lvl!r}")
            seen.append(lvl)


__all__ = [
    "ActuatorCommand",
    "ActuatorLevel",
    "ActuatorSpec",
    "AttitudeCommand",
    "BodyRateCommand",
    "CommandAck",
    "DirectMotorCommand",
    "PositionCommand",
    "RejectReason",
    "SafetyEnvelope",
    "TrajectoryCommand",
    "VelocityCommand",
    "VelocityFrame",
]
