"""Tipos congelados del modelo de incertidumbre.

Contratos definidos en `docs/specs/uncertainty.md` §2 y ADR-0008 / ADR-0010.

Solo data y enums; toda lógica vive en los demás módulos del paquete.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Literal, get_args

import numpy as np

# ---------------------------------------------------------------------------
# Validity (uncertainty.md §2)
# ---------------------------------------------------------------------------


class Validity(IntEnum):
    """Validez total-ordenada. Mayor valor = mejor.

    Orden: ``VALID > DEGRADED > STALE > INVALID``.

    Usar `min(*validities)` para componer (uncertainty.md §6.1).
    """

    INVALID = 0
    STALE = 1
    DEGRADED = 2
    VALID = 3


# ---------------------------------------------------------------------------
# PerceptionMode (uncertainty.md §2 + ADR-0010 §1)
# ---------------------------------------------------------------------------


class PerceptionMode(StrEnum):
    """Catálogo cerrado de modos perceptuales.

    Frozen en ADR-0008 con 7 modos; enmendado por ADR-0010 §1 con
    ``MOTION_AGGRESSIVE`` (8º modo). Modos rechazados y su razón en ADR-0010 §2.

    Añadir o renombrar requiere ADR que enmiende o supersede ADR-0008.
    """

    NOMINAL = "nominal"
    LOW_TEXTURE = "low_texture"
    LOW_LIGHT = "low_light"
    IMU_SATURATION = "imu_saturation"
    VIO_LOST = "vio_lost"
    MAP_AMBIGUOUS = "map_ambiguous"
    MOTION_AGGRESSIVE = "motion_aggressive"
    PERCEPTION_DEAD = "perception_dead"


# ---------------------------------------------------------------------------
# EstimateSource (uncertainty.md §2)
# ---------------------------------------------------------------------------


EstimateKind = Literal["sensor", "filter", "vo", "slam", "groundtruth", "fused"]
_VALID_KINDS: tuple[str, ...] = get_args(EstimateKind)


@dataclass(frozen=True)
class EstimateSource:
    """Identidad del productor de un `Estimate`.

    El ``kind`` distingue groundtruth (sin covarianza, solo en sim) de los
    productores reales. El constructor valida ``kind`` contra `_VALID_KINDS`.
    """

    module_id: str
    kind: EstimateKind
    schema_version: int

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"EstimateSource.kind={self.kind!r} no está en {_VALID_KINDS}")
        if not self.module_id:
            raise ValueError("EstimateSource.module_id no puede ser vacío")
        if self.schema_version < 1:
            raise ValueError(
                f"EstimateSource.schema_version debe ser ≥ 1, recibido {self.schema_version}"
            )


# ---------------------------------------------------------------------------
# NominalEnvelope (uncertainty.md §3.10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NominalEnvelope:
    """Envelope nominal declarado por un productor.

    Usado por `make_estimate` para verificar la consistencia
    validity↔covariance (uncertainty.md §3.10):

    - ``VALID`` exige `covariance` dentro del envelope.
    - ``DEGRADED`` y ``STALE`` exigen `covariance` fuera del envelope
      (es decir, inflada por §5).
    - ``INVALID`` no se comprueba (valor no usable).

    Criterio "dentro del envelope":
        ``all(diag(C) <= max_diag) and trace(C) <= max_trace``
    """

    max_diag: np.ndarray  # (n,) float64; cota superior por eje de la diagonal
    max_trace: float

    def __post_init__(self) -> None:
        arr = np.asarray(self.max_diag, dtype=np.float64)
        if arr.ndim != 1:
            raise ValueError(f"NominalEnvelope.max_diag debe ser 1-D, recibido shape={arr.shape}")
        if not np.all(arr > 0):
            raise ValueError("NominalEnvelope.max_diag debe ser estrictamente positivo")
        if self.max_trace <= 0:
            raise ValueError(f"NominalEnvelope.max_trace debe ser > 0, recibido {self.max_trace}")
        arr.flags.writeable = False
        # Reemplazamos el campo en la dataclass frozen vía object.__setattr__.
        object.__setattr__(self, "max_diag", arr)

    def contains(self, covariance: np.ndarray) -> bool:
        """True si la covarianza está dentro del envelope nominal."""
        diag = np.diag(covariance)
        if diag.shape != self.max_diag.shape:
            raise ValueError(
                f"contains: shape mismatch diag={diag.shape} vs envelope={self.max_diag.shape}"
            )
        return bool(np.all(diag <= self.max_diag)) and float(np.trace(covariance)) <= self.max_trace


# ---------------------------------------------------------------------------
# NavUncertainty (uncertainty.md §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NavUncertainty:
    """Envelope de incertidumbre adjunto a `NavigationState`.

    Tres sigma marginales (posición ENU, velocidad, actitud en tangente del
    cuaternión), validez, horizonte y edad de la observación más antigua que
    contribuyó al estimado fusionado.
    """

    validity: Validity
    pos_sigma_m: np.ndarray  # (3,) float64
    vel_sigma_mps: np.ndarray  # (3,) float64
    att_sigma_rad: np.ndarray  # (3,) float64
    horizon_ns: int
    age_ns: int

    def __post_init__(self) -> None:
        for name in ("pos_sigma_m", "vel_sigma_mps", "att_sigma_rad"):
            arr = np.asarray(getattr(self, name), dtype=np.float64)
            if arr.shape != (3,):
                raise ValueError(
                    f"NavUncertainty.{name} debe tener shape (3,), recibido {arr.shape}"
                )
            if not np.all(arr >= 0):
                raise ValueError(f"NavUncertainty.{name} debe ser no-negativo")
            arr.flags.writeable = False
            object.__setattr__(self, name, arr)
        if self.horizon_ns < 0:
            raise ValueError(f"NavUncertainty.horizon_ns debe ser ≥ 0, recibido {self.horizon_ns}")
        if self.age_ns < 0:
            raise ValueError(f"NavUncertainty.age_ns debe ser ≥ 0, recibido {self.age_ns}")


__all__ = [
    "EstimateKind",
    "EstimateSource",
    "NavUncertainty",
    "NominalEnvelope",
    "PerceptionMode",
    "Validity",
]
