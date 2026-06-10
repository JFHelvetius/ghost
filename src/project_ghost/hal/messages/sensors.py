"""Mensajes del sub-API de sensores (T2.a.1 del roadmap Fase 1).

Materializa el catálogo de `docs/specs/sensors.md` §2-§3 como dataclasses
frozen con validación por constructor. Los arrays se sellan
(`flags.writeable=False`) en `__post_init__` cumpliendo el contrato de
`hal.md` §3.5 ("Sin mutación cruzada").

Alcance T2.a.1:

- Estructura común: `SensorHealth`, `SensorMeta`, `SensorSample[T]`,
  `SensorSpec`.
- Payloads concretos: `IMUPayload`, `CameraIntrinsics`, `RGBImagePayload`,
  `DepthImagePayload`, `GpsFix`, `GpsPayload`, `AltimeterPayload`.
- `NoiseModel` Protocol como **marker** mínimo (las implementaciones
  concretas — bias estable + random walk + ruido blanco para IMU, etc. —
  llegan en su propia tarea cuando los productores reales aterricen en
  Fase 3).

Fuera de alcance T2.a.1:

- `LiDAR`/`PointCloudPayload`, magnetómetro, barómetro, event camera
  (sensors.md §3.6, "previstos" — entran al ser necesitados).
- Compresión nativa de imagen (`encoding="jpeg"`, sensors.md §9).
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Generic, Literal, Protocol, TypeVar

import numpy as np

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

SensorId = str
"""Identificador estable de un sensor (e.g. ``"imu0"``, ``"cam_front"``).

Convención: corto, kebab-o-snake-case, no espacios, no slashes. El consumo
por canal de bus usa ``/sensors/<sensor_id>``. Etiquetas dinámicas
(uuid, timestamp) **prohibidas** por la misma razón que en
`RandomSource.child` (rompen replay).
"""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SensorHealth(IntEnum):
    """Estado de salud por muestra. Total-orden: OK < DEGRADED < FAULTY < OFFLINE."""

    OK = 0
    DEGRADED = 1
    FAULTY = 2
    OFFLINE = 3


class GpsFix(IntEnum):
    """Calidad del fix GPS. Total-orden: NO_FIX < FIX_2D < FIX_3D < RTK."""

    NO_FIX = 0
    FIX_2D = 1
    FIX_3D = 2
    RTK = 3


# ---------------------------------------------------------------------------
# NoiseModel — marker Protocol
# ---------------------------------------------------------------------------


class NoiseModel(Protocol):
    """Marker Protocol para modelos de ruido.

    En T2.a.1 no se requieren métodos: el campo `SensorSpec.noise_model`
    aún puede ser `None` cuando no hay simulación de ruido. Las
    implementaciones concretas (IMU con bias estable + random walk +
    ruido blanco gaussiano, cámara con motion blur / dropout, GPS con
    multipath, etc.) llegarán como tareas dedicadas cuando los productores
    reales de Fase 3 las necesiten. Por ahora el Protocol solo sirve de
    marker de tipo en signatures.
    """


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
    """Valida shape/ndim/dtype y, opcionalmente, finitud.

    `TypeError` para shape/dtype incorrectos; `ValueError` para NaN/Inf.
    Esa distinción mirrors el patrón de `core.uncertainty.estimate`.
    """
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
    """Sella un array contra mutación in-place (hal.md §3.5)."""
    arr.setflags(write=False)


# ---------------------------------------------------------------------------
# Estructuras compartidas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorMeta:
    """Metadata transversal a cualquier muestra (sensors.md §2).

    `extensions` debe ser un Mapping inmutable (e.g. `MappingProxyType`)
    cuando se construye desde el backend; el dataclass no defiende contra
    mutación posterior por el publisher.
    """

    frame_id: str
    calibration_id: str | None
    extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.frame_id:
            raise ValueError("frame_id no puede ser vacío")


T = TypeVar("T")


@dataclass(frozen=True)
class SensorSample(Generic[T]):
    """Muestra canónica de cualquier sensor (sensors.md §2).

    Tres relojes per spec §5:

    - ``stamp_sensor_ns``: reloj del sensor (puede driftear via
      `NoiseModel.clock_drift_ppm` cuando exista).
    - ``stamp_sim_ns``: reloj de simulación al publicar.
    - ``stamp_wall_ns``: reloj de pared (debug; no usar para algoritmos).

    ``seq`` monotónico **por sensor** (no global). Gaps en `seq` señalan
    drops, per spec §6 ("Sobrecarga / drop interno: salto en seq").
    """

    sensor_id: SensorId
    seq: int
    stamp_sensor_ns: int
    stamp_sim_ns: int
    stamp_wall_ns: int
    health: SensorHealth
    payload: T
    meta: SensorMeta
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.sensor_id:
            raise ValueError("sensor_id no puede ser vacío")
        if self.seq < 0:
            raise ValueError(f"seq debe ser >= 0; recibido {self.seq}")
        if self.stamp_sensor_ns < 0:
            raise ValueError(f"stamp_sensor_ns debe ser >= 0; recibido {self.stamp_sensor_ns}")
        if self.stamp_sim_ns < 0:
            raise ValueError(f"stamp_sim_ns debe ser >= 0; recibido {self.stamp_sim_ns}")
        if self.stamp_wall_ns < 0:
            raise ValueError(f"stamp_wall_ns debe ser >= 0; recibido {self.stamp_wall_ns}")
        if self.schema_version < 1:
            raise ValueError(f"schema_version debe ser >= 1; recibido {self.schema_version}")


@dataclass(frozen=True)
class SensorSpec:
    """Configuración estática del sensor (sensors.md §2)."""

    sensor_id: SensorId
    payload_type: str
    nominal_rate_hz: float
    frame_id: str
    noise_model: NoiseModel | None
    latency_ns: int = 0

    def __post_init__(self) -> None:
        if not self.sensor_id:
            raise ValueError("sensor_id no puede ser vacío")
        if not self.payload_type:
            raise ValueError("payload_type no puede ser vacío")
        if not self.frame_id:
            raise ValueError("frame_id no puede ser vacío")
        if self.nominal_rate_hz <= 0:
            raise ValueError(f"nominal_rate_hz debe ser > 0; recibido {self.nominal_rate_hz}")
        if self.latency_ns < 0:
            raise ValueError(f"latency_ns debe ser >= 0; recibido {self.latency_ns}")


# ---------------------------------------------------------------------------
# IMU
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IMUPayload:
    """IMU sample (sensors.md §3.1). Frame body FLU; SI estricto.

    ``accel_mps2`` y ``gyro_rps`` se sellan en `__post_init__`.
    """

    accel_mps2: np.ndarray
    gyro_rps: np.ndarray
    temperature_c: float | None

    def __post_init__(self) -> None:
        _validate_array(self.accel_mps2, name="accel_mps2", shape=(3,), dtype=np.float64)
        _validate_array(self.gyro_rps, name="gyro_rps", shape=(3,), dtype=np.float64)
        _seal(self.accel_mps2)
        _seal(self.gyro_rps)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

# Modelos de distorsión soportados y número de coeficientes per OpenCV / spec.
_DISTORTION_COEFFS_COUNT: Final[dict[str, int]] = {
    "none": 0,
    "plumb_bob": 5,  # k1, k2, p1, p2, k3
    "equidistant": 4,  # k1, k2, k3, k4 (Kannala-Brandt)
}

# Canales esperados en imagen RGB (sensors.md §3.2 — encoding "rgb8").
_RGB_CHANNELS: Final[int] = 3

# Rangos válidos de latitud/longitud en grados (WGS-84).
_LAT_MIN_DEG: Final[float] = -90.0
_LAT_MAX_DEG: Final[float] = 90.0
_LON_MIN_DEG: Final[float] = -180.0
_LON_MAX_DEG: Final[float] = 180.0

DistortionModel = Literal["none", "plumb_bob", "equidistant"]


@dataclass(frozen=True)
class CameraIntrinsics:
    """Parámetros intrínsecos de cámara (sensors.md §3.2).

    ``distortion_coeffs`` debe tener exactamente la longitud que dicta
    ``distortion_model``: 0 / 5 / 4 para none / plumb_bob / equidistant.
    """

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion_model: DistortionModel
    distortion_coeffs: np.ndarray

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"width y height deben ser > 0; recibido ({self.width}, {self.height})"
            )
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError(f"fx y fy deben ser > 0; recibido ({self.fx}, {self.fy})")
        if self.distortion_model not in _DISTORTION_COEFFS_COUNT:
            raise ValueError(
                f"distortion_model inválido: {self.distortion_model!r}. "
                f"Permitidos: {tuple(_DISTORTION_COEFFS_COUNT)}"
            )
        expected = _DISTORTION_COEFFS_COUNT[self.distortion_model]
        _validate_array(
            self.distortion_coeffs,
            name="distortion_coeffs",
            shape=(expected,),
            dtype=np.float64,
        )
        _seal(self.distortion_coeffs)


@dataclass(frozen=True)
class RGBImagePayload:
    """Imagen RGB (sensors.md §3.2). Canal sRGB, encoding ``rgb8``."""

    image: np.ndarray
    intrinsics: CameraIntrinsics
    exposure_ns: int
    encoding: Literal["rgb8"]

    def __post_init__(self) -> None:
        _validate_array(
            self.image,
            name="image",
            ndim=3,
            dtype=np.uint8,
            require_finite=False,  # uint8 no admite NaN/Inf por definición
        )
        # Verificar coherencia con intrinsics
        h, w, ch = self.image.shape
        if ch != _RGB_CHANNELS:
            raise TypeError(f"image debe tener {_RGB_CHANNELS} canales en el eje -1; recibido {ch}")
        if (h, w) != (self.intrinsics.height, self.intrinsics.width):
            raise ValueError(
                f"image shape ({h}, {w}) no coincide con intrinsics "
                f"({self.intrinsics.height}, {self.intrinsics.width})"
            )
        if self.exposure_ns < 0:
            raise ValueError(f"exposure_ns debe ser >= 0; recibido {self.exposure_ns}")
        if self.encoding != "rgb8":
            raise ValueError(f"encoding debe ser 'rgb8'; recibido {self.encoding!r}")
        _seal(self.image)


@dataclass(frozen=True)
class DepthImagePayload:
    """Imagen de profundidad (sensors.md §3.3). NaN = inválido."""

    depth_m: np.ndarray
    intrinsics: CameraIntrinsics
    min_range_m: float
    max_range_m: float

    def __post_init__(self) -> None:
        _validate_array(
            self.depth_m,
            name="depth_m",
            ndim=2,
            dtype=np.float32,
            require_finite=False,  # NaN explícitamente permitido per spec §3.3
        )
        h, w = self.depth_m.shape
        if (h, w) != (self.intrinsics.height, self.intrinsics.width):
            raise ValueError(
                f"depth_m shape ({h}, {w}) no coincide con intrinsics "
                f"({self.intrinsics.height}, {self.intrinsics.width})"
            )
        if self.min_range_m < 0:
            raise ValueError(f"min_range_m debe ser >= 0; recibido {self.min_range_m}")
        if self.max_range_m <= self.min_range_m:
            raise ValueError(
                f"max_range_m ({self.max_range_m}) debe ser > min_range_m ({self.min_range_m})"
            )
        _seal(self.depth_m)


# ---------------------------------------------------------------------------
# GPS
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpsPayload:
    """GPS sample (sensors.md §3.4).

    Política recordada en docstring: el estimador de navegación principal
    **no** consume `GpsPayload` (ADR-0000); solo evaluación / groundtruth.
    """

    lat_deg: float
    lon_deg: float
    alt_m: float
    enu_local_m: np.ndarray
    fix_type: GpsFix
    hacc_m: float
    vacc_m: float

    def __post_init__(self) -> None:
        if not _LAT_MIN_DEG <= self.lat_deg <= _LAT_MAX_DEG:
            raise ValueError(
                f"lat_deg fuera de rango [{_LAT_MIN_DEG}, {_LAT_MAX_DEG}]; recibido {self.lat_deg}"
            )
        if not _LON_MIN_DEG <= self.lon_deg <= _LON_MAX_DEG:
            raise ValueError(
                f"lon_deg fuera de rango [{_LON_MIN_DEG}, {_LON_MAX_DEG}]; recibido {self.lon_deg}"
            )
        _validate_array(self.enu_local_m, name="enu_local_m", shape=(3,), dtype=np.float64)
        if self.hacc_m < 0:
            raise ValueError(f"hacc_m debe ser >= 0; recibido {self.hacc_m}")
        if self.vacc_m < 0:
            raise ValueError(f"vacc_m debe ser >= 0; recibido {self.vacc_m}")
        _seal(self.enu_local_m)


# ---------------------------------------------------------------------------
# Altimeter
# ---------------------------------------------------------------------------

AltimeterReference = Literal["AMSL", "AGL", "LOCAL"]


@dataclass(frozen=True)
class AltimeterPayload:
    """Altímetro barométrico/láser (sensors.md §3.5)."""

    altitude_m: float
    reference: AltimeterReference
    variance_m2: float

    def __post_init__(self) -> None:
        if self.reference not in ("AMSL", "AGL", "LOCAL"):
            raise ValueError(
                f"reference inválido: {self.reference!r}. Permitidos: 'AMSL', 'AGL', 'LOCAL'."
            )
        if self.variance_m2 < 0:
            raise ValueError(f"variance_m2 debe ser >= 0; recibido {self.variance_m2}")


__all__ = [
    "AltimeterPayload",
    "AltimeterReference",
    "CameraIntrinsics",
    "DepthImagePayload",
    "DistortionModel",
    "GpsFix",
    "GpsPayload",
    "IMUPayload",
    "NoiseModel",
    "RGBImagePayload",
    "SensorHealth",
    "SensorId",
    "SensorMeta",
    "SensorSample",
    "SensorSpec",
]
