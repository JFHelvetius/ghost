"""Dataclasses runtime del HAL: configuración, descubrimiento y oráculo.

Cubre `docs/specs/hal.md` §2 (Capabilities) y los tipos referenciados por
los Protocols de backend que NO son mensajes de sensor/actuador:

- `Capabilities` — descubrimiento estático (sensor_ids, actuator_levels,
  flags `has_ground_truth`/`synchronous_step`/`deterministic`/
  `supports_replay`, extensions).
- `ScenarioSpec` — input a `SimulationBackend.reset()`. Schema mínimo:
  identificadores de world y vehicle, duración opcional y `extensions`
  opacas. La carga del world (YAML) vive en su propio módulo cuando
  llegue (Fase 1 T13).
- `GroundTruth` — oráculo opcional de simulador (returnado por
  `SimulationBackend.ground_truth()`). Schema minimal, frame ENU world /
  body FLU igual que `state.NavigationState` pero sin biases/cov/flight/
  mission (es el dato crudo del simulador, no el estado canónico).
- `StepReport` — output de `SimulationBackend.step(dt_ns)`. Reporta el dt
  efectivamente avanzado y extensions opacas.

Decisión: estos tipos viven en `hal.messages.runtime` (no en
`hal.protocols`) porque son dataclasses con validación de invariantes,
no Protocols. Quedan agrupados con los demás "mensajes" del HAL para
facilitar imports `from project_ghost.hal.messages import ...`.
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

# `SensorId`, `ActuatorLevel` y `Mapping` se importan a runtime (no en
# TYPE_CHECKING) para que `typing.get_type_hints` pueda resolver las
# anotaciones — `telemetry.serialization.from_json_dict` lo necesita para
# round-trip decoding.
from .actuators import ActuatorLevel  # noqa: TC001
from .sensors import SensorId  # noqa: TC001

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_VEC3_LEN: Final[int] = 3
_QUAT_LEN: Final[int] = 4
_QUAT_NORM_TOLERANCE: Final[float] = 1e-3


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _validate_array(
    arr: Any,
    *,
    name: str,
    shape: tuple[int, ...] | None = None,
    dtype: Any = None,
    require_finite: bool = True,
) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{name} debe ser np.ndarray; recibido {type(arr).__name__}"
        )
    if shape is not None and arr.shape != shape:
        raise TypeError(
            f"{name} debe tener shape {shape}; recibido {arr.shape}"
        )
    if dtype is not None:
        expected = np.dtype(dtype)
        if arr.dtype != expected:
            raise TypeError(
                f"{name} debe tener dtype {expected}; recibido {arr.dtype}"
            )
    if require_finite and not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contiene NaN o Inf")


def _seal(arr: np.ndarray) -> None:
    arr.setflags(write=False)


def _validate_unit_quaternion(q: np.ndarray, *, name: str) -> None:
    _validate_array(q, name=name, shape=(_QUAT_LEN,), dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if abs(norm - 1.0) > _QUAT_NORM_TOLERANCE:
        raise ValueError(
            f"{name} debe ser unit (tolerancia {_QUAT_NORM_TOLERANCE}); "
            f"norm={norm}"
        )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capabilities:
    """Descubrimiento estático de capabilities del backend (hal.md §2).

    Los consumidores que dependen de features opcionales consultan estos
    flags antes de usar la feature (hal.md §6 — "Capability discovery
    antes de uso").
    """

    hal_version: int
    sensor_ids: tuple[SensorId, ...]
    actuator_levels: tuple[ActuatorLevel, ...]
    has_ground_truth: bool
    synchronous_step: bool
    deterministic: bool
    supports_replay: bool
    extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.hal_version < 1:
            raise ValueError(
                f"hal_version debe ser >= 1; recibido {self.hal_version}"
            )
        if not isinstance(self.sensor_ids, tuple):
            raise TypeError(
                "sensor_ids debe ser tuple (uncertainty.md §10); "
                f"recibido {type(self.sensor_ids).__name__}"
            )
        if not isinstance(self.actuator_levels, tuple):
            raise TypeError(
                "actuator_levels debe ser tuple (uncertainty.md §10); "
                f"recibido {type(self.actuator_levels).__name__}"
            )
        # Detectar duplicados sin set (uncertainty.md §10).
        seen_sensors: list[str] = []
        for sid in self.sensor_ids:
            if sid in seen_sensors:
                raise ValueError(f"sensor_ids tiene duplicado: {sid!r}")
            seen_sensors.append(sid)
        seen_levels: list[ActuatorLevel] = []
        for lvl in self.actuator_levels:
            if lvl in seen_levels:
                raise ValueError(f"actuator_levels tiene duplicado: {lvl!r}")
            seen_levels.append(lvl)


# ---------------------------------------------------------------------------
# ScenarioSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    """Input a `SimulationBackend.reset()` (hal.md §5.1).

    `world_id` y `vehicle_id` son identificadores estables (no rutas):
    el backend resuelve a archivos concretos en `worlds/` y
    `configs/vehicles/`. `duration_ns` es opcional — `None` significa
    sin límite duro (típico para sesiones de demo manual). `extensions`
    transporta opciones específicas del backend que el caller pasa
    opacas.
    """

    world_id: str
    vehicle_id: str
    duration_ns: int | None
    extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.world_id:
            raise ValueError("world_id no puede ser vacío")
        if not self.vehicle_id:
            raise ValueError("vehicle_id no puede ser vacío")
        if self.duration_ns is not None and self.duration_ns <= 0:
            raise ValueError(
                f"duration_ns debe ser > 0 cuando no es None; "
                f"recibido {self.duration_ns}"
            )


# ---------------------------------------------------------------------------
# GroundTruth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundTruth:
    """Oráculo del simulador (hal.md §2.6).

    Schema minimal, pensado para alimentar `state.NavigationState` en
    Fase 1 (state.md §5.1). En Fase 1 con groundtruth, este es el único
    "estimador" del sistema; en fases posteriores convive con el
    estimador real para evaluación.

    Frames: position ENU, orientation Hamilton w-first, linear velocity
    en world, angular velocity en body (ambos disponibles porque ambos
    se usan en distintas partes del controlador).
    """

    stamp_sim_ns: int
    position_enu_m: np.ndarray
    orientation_q: np.ndarray
    linear_velocity_world_mps: np.ndarray
    angular_velocity_body_rps: np.ndarray
    accel_body_mps2: np.ndarray

    def __post_init__(self) -> None:
        if self.stamp_sim_ns < 0:
            raise ValueError(
                f"stamp_sim_ns debe ser >= 0; recibido {self.stamp_sim_ns}"
            )
        _validate_array(
            self.position_enu_m,
            name="position_enu_m",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_unit_quaternion(self.orientation_q, name="orientation_q")
        _validate_array(
            self.linear_velocity_world_mps,
            name="linear_velocity_world_mps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_array(
            self.angular_velocity_body_rps,
            name="angular_velocity_body_rps",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _validate_array(
            self.accel_body_mps2,
            name="accel_body_mps2",
            shape=(_VEC3_LEN,),
            dtype=np.float64,
        )
        _seal(self.position_enu_m)
        _seal(self.orientation_q)
        _seal(self.linear_velocity_world_mps)
        _seal(self.angular_velocity_body_rps)
        _seal(self.accel_body_mps2)


# ---------------------------------------------------------------------------
# StepReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepReport:
    """Output de `SimulationBackend.step(dt_ns)`.

    `dt_advanced_ns` es el dt efectivamente avanzado por el backend; en
    general coincide con el dt solicitado pero puede diferir si el
    backend tiene un sub-step interno o si `duration_ns` del scenario se
    alcanzó. `extensions` opacas para métricas específicas del backend
    (e.g. número de colisiones procesadas en PyBullet).
    """

    dt_advanced_ns: int
    extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.dt_advanced_ns < 0:
            raise ValueError(
                f"dt_advanced_ns debe ser >= 0; recibido {self.dt_advanced_ns}"
            )


__all__ = [
    "Capabilities",
    "GroundTruth",
    "ScenarioSpec",
    "StepReport",
]
