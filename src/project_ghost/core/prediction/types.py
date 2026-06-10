"""Forward-prediction emission types — el shape de "lo que el agente
predice que va a observar" (ADR-0024).

Stdlib + numpy (numpy ya transitivamente presente vía HAL). Frozen,
pure data, content-addressed por construcción.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import numpy as np

from project_ghost.state.messages import Pose

PREDICTION_PROTOCOL_VERSION: Final[int] = 1

# Same format as ADR-0021/ADR-0023 taxonomy: snake_case, starts with
# lowercase letter, length 1-64.
_TAXONOMY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_TAXONOMY_MAX_LEN: Final[int] = 64

# SHA-256 hex format (same as ADR-0022 chain).
_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")

_VEC3_LEN: Final[int] = 3


def _validate_taxonomy(value: str, *, field: str) -> None:
    """Validar identificador snake_case taxonomizado."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str; got {type(value).__name__}")
    if not value:
        raise ValueError(f"{field} cannot be empty")
    if len(value) > _TAXONOMY_MAX_LEN:
        raise ValueError(f"{field} must be <= {_TAXONOMY_MAX_LEN} chars; got len={len(value)}")
    if not _TAXONOMY_PATTERN.match(value):
        raise ValueError(f"{field} must match {_TAXONOMY_PATTERN.pattern!r}; got {value!r}")


def _validate_sha256_hex(value: str, *, field: str) -> None:
    """Validar hex SHA-256 lowercase de 64 chars (igual que ADR-0022)."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str; got {type(value).__name__}")
    if len(value) != _SHA256_HEX_LEN:
        raise ValueError(f"{field} must be {_SHA256_HEX_LEN} hex chars; got len={len(value)}")
    if not all(c in _HEX_CHARS for c in value):
        raise ValueError(f"{field} must be lowercase hex; got {value!r}")


def _validate_nonneg_vec3(arr: np.ndarray, *, field: str) -> None:
    """Validar np.ndarray shape (3,), float64, finite y >= 0."""
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{field} must be np.ndarray; got {type(arr).__name__}")
    if arr.shape != (_VEC3_LEN,):
        raise ValueError(f"{field} must have shape ({_VEC3_LEN},); got shape={arr.shape}")
    if arr.dtype != np.float64:
        raise ValueError(f"{field} must have dtype float64; got dtype={arr.dtype}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{field} must be finite; got {arr!r}")
    if np.any(arr < 0.0):
        raise ValueError(f"{field} must be >= 0; got {arr!r}")


@dataclass(frozen=True)
class PoseStd:
    """Desviación típica predicha sobre la pose.

    ``position_std_enu_m``: std posicional por eje, en ENU. Shape (3,),
    float64, componentes >= 0.

    ``orientation_std_rad``: std orientacional en parametrización
    axis-angle (yaw/pitch/roll tangent). Shape (3,), float64,
    componentes >= 0.

    Mantiene paralelismo con ``Pose``: misma estructura por eje, sólo
    incertidumbre en lugar de valor central.
    """

    position_std_enu_m: np.ndarray
    orientation_std_rad: np.ndarray

    def __post_init__(self) -> None:
        _validate_nonneg_vec3(self.position_std_enu_m, field="position_std_enu_m")
        _validate_nonneg_vec3(self.orientation_std_rad, field="orientation_std_rad")
        self.position_std_enu_m.setflags(write=False)
        self.orientation_std_rad.setflags(write=False)


@dataclass(frozen=True)
class BeliefForwardPrediction:
    """Envelope que ata una creencia presente a una predicción de pose
    en un horizonte declarado.

    ``source_belief_stamp_sim_ns`` es el stamp del ``VehicleState`` que
    originó la predicción.

    ``predicted_observation_stamp_sim_ns`` debe ser exactamente
    ``source_belief_stamp_sim_ns + horizon_ns`` — esa identidad es lo
    que hace la predicción refutable: cuando llegue una observación con
    stamp matching, se podrá computar divergencia.

    ``horizon_ns`` debe ser ``> 0``. ``horizon_ns == 0`` sería
    self-assessment del presente, no predicción.

    ``associated_directive_hash`` es el SHA-256 del
    ``ActuationDirective`` (ADR-0023) al que esta predicción está
    causalmente atada — formato idéntico al chain de ADR-0022.
    ``None`` es legítimo: el predictor corre standalone (forecasting
    puro, sin comando asociado).

    ``predictor_id`` identifica qué predictor produjo el record
    (taxonomía snake_case, igual que ``policy_id`` de ADR-0023).
    """

    source_belief_stamp_sim_ns: int
    predicted_observation_stamp_sim_ns: int
    horizon_ns: int
    predicted_pose: Pose
    predicted_pose_std: PoseStd
    associated_directive_hash: str | None
    predictor_id: str
    schema_version: int = PREDICTION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.source_belief_stamp_sim_ns < 0:
            raise ValueError(
                f"source_belief_stamp_sim_ns must be >= 0; got {self.source_belief_stamp_sim_ns}"
            )
        if self.horizon_ns <= 0:
            raise ValueError(
                f"horizon_ns must be > 0 (use self-assessment for "
                f"present-time); got {self.horizon_ns}"
            )
        expected_stamp = self.source_belief_stamp_sim_ns + self.horizon_ns
        if self.predicted_observation_stamp_sim_ns != expected_stamp:
            raise ValueError(
                f"predicted_observation_stamp_sim_ns "
                f"({self.predicted_observation_stamp_sim_ns}) must equal "
                f"source_belief_stamp_sim_ns + horizon_ns "
                f"({expected_stamp})"
            )
        if not isinstance(self.predicted_pose, Pose):
            raise TypeError(
                f"predicted_pose must be Pose; got {type(self.predicted_pose).__name__}"
            )
        if not isinstance(self.predicted_pose_std, PoseStd):
            raise TypeError(
                f"predicted_pose_std must be PoseStd; got {type(self.predicted_pose_std).__name__}"
            )
        if self.associated_directive_hash is not None:
            _validate_sha256_hex(
                self.associated_directive_hash,
                field="associated_directive_hash",
            )
        _validate_taxonomy(self.predictor_id, field="predictor_id")
        if self.schema_version != PREDICTION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {PREDICTION_PROTOCOL_VERSION}; got {self.schema_version}"
            )


__all__ = [
    "PREDICTION_PROTOCOL_VERSION",
    "BeliefForwardPrediction",
    "PoseStd",
]
