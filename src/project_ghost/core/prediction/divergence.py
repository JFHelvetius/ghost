"""Prediction-observation divergence check (ADR-0025).

Cierra el lado dinámico de la honestidad epistémica abierto por
ADR-0024: cada ``BeliefForwardPrediction`` queda atada a su observación
real con los residuos computados y un verdict categórico cerrado.

Stdlib + numpy. Pure functions. Frozen dataclasses. Catálogo cerrado.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np

from project_ghost.state.messages import Pose

from .types import BeliefForwardPrediction

DIVERGENCE_PROTOCOL_VERSION: Final[int] = 1

_VEC3_LEN: Final[int] = 3

# Verdict thresholds on max(pos_mahal_max, ori_mahal_max).
_THRESHOLD_1_STD: Final[float] = 1.0
_THRESHOLD_3_STD: Final[float] = 3.0
_THRESHOLD_5_STD: Final[float] = 5.0

# Numerical tolerance for small-angle branch in quaternion log.
_ANGLE_EPS: Final[float] = 1e-12


class DivergenceVerdict(StrEnum):
    """Catálogo cerrado de verdicts sobre divergencia predicción↔observación.

    Modificar (añadir/renombrar/borrar) requiere ADR amendment
    explícito. Mismo posture que ``DecisionKind`` y ``PerceptionMode``.

    Semántica (vinculante, basada en ``max(position_mahalanobis_max,
    orientation_mahalanobis_max)``):

    - ``WITHIN_1_STD``: ``< 1`` — predicción consistente con
      observación al nivel de incertidumbre declarado.
    - ``BEYOND_1_STD``: ``[1, 3)`` — observación fuera de 1sigma;
      desviación normal pero declarada.
    - ``BEYOND_3_STD``: ``[3, 5)`` — desviación significativa; el
      predictor está siendo overconfident o el modelo dinámico no
      cubre lo que pasó.
    - ``BEYOND_5_STD``: ``>= 5`` o ``+inf`` — observación radicalmente
      incompatible con la predicción.
    """

    WITHIN_1_STD = "within_1_std"
    BEYOND_1_STD = "beyond_1_std"
    BEYOND_3_STD = "beyond_3_std"
    BEYOND_5_STD = "beyond_5_std"


def _verdict_from_max_mahalanobis(value: float) -> DivergenceVerdict:
    """Mapea ``max(pos_mahal, ori_mahal)`` a un verdict cerrado.

    ``+inf`` cae naturalmente en ``BEYOND_5_STD``.
    """
    if value < _THRESHOLD_1_STD:
        return DivergenceVerdict.WITHIN_1_STD
    if value < _THRESHOLD_3_STD:
        return DivergenceVerdict.BEYOND_1_STD
    if value < _THRESHOLD_5_STD:
        return DivergenceVerdict.BEYOND_3_STD
    return DivergenceVerdict.BEYOND_5_STD


def _validate_finite_vec3(arr: np.ndarray, *, field: str) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{field} must be np.ndarray; got {type(arr).__name__}"
        )
    if arr.shape != (_VEC3_LEN,):
        raise ValueError(
            f"{field} must have shape ({_VEC3_LEN},); got shape={arr.shape}"
        )
    if arr.dtype != np.float64:
        raise ValueError(
            f"{field} must have dtype float64; got dtype={arr.dtype}"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{field} must be finite; got {arr!r}")


def _validate_finite_nonneg(value: float, *, field: str) -> None:
    if not np.isfinite(value):
        raise ValueError(f"{field} must be finite; got {value}")
    if value < 0.0:
        raise ValueError(f"{field} must be >= 0; got {value}")


def _validate_mahalanobis(value: float, *, field: str) -> None:
    """Mahalanobis puede ser ``+inf`` cuando std=0 y error≠0 — eso es
    legítimo. NaN nunca lo es.
    """
    if np.isnan(value):
        raise ValueError(f"{field} must not be NaN; got {value}")
    if value < 0.0:
        raise ValueError(f"{field} must be >= 0; got {value}")


@dataclass(frozen=True)
class PredictionOutcome:
    """Envelope que ata una predicción a su observación real.

    El record es self-contained: incluye la ``BeliefForwardPrediction``
    original inline para que el outcome sea auditable sin depender del
    canal ``/predictions/forward``.

    Stamps:

    - ``actual_belief_stamp_sim_ns`` debe matchear
      ``prediction.predicted_observation_stamp_sim_ns``. Sin esa
      identidad la divergencia no es comparable.

    Errores:

    - ``position_error_enu_m = actual - predicted``, ENU, shape (3,).
    - ``orientation_error_rad``: axis-angle delta del producto
      ``actual_q * predicted_q_conj``, shape (3,) (rotation vector).

    Mahalanobis:

    - ``position_mahalanobis_max`` y ``orientation_mahalanobis_max`` son
      ``max_i(|err_i| / std_i)`` con la convención: ``0/0 = 0``,
      ``!0/0 = +inf``.

    Verdict:

    - Catálogo cerrado, derivado de
      ``max(position_mahalanobis_max, orientation_mahalanobis_max)``.
    """

    prediction: BeliefForwardPrediction
    actual_belief_stamp_sim_ns: int
    actual_pose: Pose
    position_error_enu_m: np.ndarray
    position_error_norm_m: float
    orientation_error_rad: np.ndarray
    orientation_error_norm_rad: float
    position_mahalanobis_max: float
    orientation_mahalanobis_max: float
    verdict: DivergenceVerdict
    schema_version: int = DIVERGENCE_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.prediction, BeliefForwardPrediction):
            raise TypeError(
                f"prediction must be BeliefForwardPrediction; got "
                f"{type(self.prediction).__name__}"
            )
        if not isinstance(self.actual_pose, Pose):
            raise TypeError(
                f"actual_pose must be Pose; got "
                f"{type(self.actual_pose).__name__}"
            )
        expected_stamp = self.prediction.predicted_observation_stamp_sim_ns
        if self.actual_belief_stamp_sim_ns != expected_stamp:
            raise ValueError(
                f"actual_belief_stamp_sim_ns "
                f"({self.actual_belief_stamp_sim_ns}) must equal "
                f"prediction.predicted_observation_stamp_sim_ns "
                f"({expected_stamp})"
            )
        _validate_finite_vec3(
            self.position_error_enu_m, field="position_error_enu_m"
        )
        _validate_finite_vec3(
            self.orientation_error_rad, field="orientation_error_rad"
        )
        _validate_finite_nonneg(
            self.position_error_norm_m, field="position_error_norm_m"
        )
        _validate_finite_nonneg(
            self.orientation_error_norm_rad,
            field="orientation_error_norm_rad",
        )
        _validate_mahalanobis(
            self.position_mahalanobis_max,
            field="position_mahalanobis_max",
        )
        _validate_mahalanobis(
            self.orientation_mahalanobis_max,
            field="orientation_mahalanobis_max",
        )
        if not isinstance(self.verdict, DivergenceVerdict):
            raise TypeError(
                f"verdict must be DivergenceVerdict; got "
                f"{type(self.verdict).__name__}"
            )
        expected_verdict = _verdict_from_max_mahalanobis(
            max(
                self.position_mahalanobis_max,
                self.orientation_mahalanobis_max,
            )
        )
        if self.verdict != expected_verdict:
            raise ValueError(
                f"verdict ({self.verdict.value}) inconsistent with "
                f"max mahalanobis "
                f"({max(self.position_mahalanobis_max, self.orientation_mahalanobis_max)}); "
                f"expected {expected_verdict.value}"
            )
        if self.schema_version != DIVERGENCE_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {DIVERGENCE_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )
        self.position_error_enu_m.setflags(write=False)
        self.orientation_error_rad.setflags(write=False)


def _quaternion_error_axis_angle(
    q_predicted: np.ndarray, q_actual: np.ndarray
) -> np.ndarray:
    """Compute axis-angle rotation vector from ``q_predicted`` to
    ``q_actual``.

    Returns shape (3,) float64. Magnitude is angle in radians,
    direction is rotation axis.

    Convention: quaternions Hamilton w-first ``[w, x, y, z]``.
    """
    w1, x1, y1, z1 = (float(c) for c in q_actual)
    w2, x2, y2, z2 = (float(c) for c in q_predicted)
    # q_err = q_actual * q_predicted_conjugate
    w = w1 * w2 + x1 * x2 + y1 * y2 + z1 * z2
    x = -w1 * x2 + x1 * w2 - y1 * z2 + z1 * y2
    y = -w1 * y2 + x1 * z2 + y1 * w2 - z1 * x2
    z = -w1 * z2 - x1 * y2 + y1 * x2 + z1 * w2
    # Resolve double-cover ambiguity: q and -q represent same rotation.
    # Pick the representation with positive scalar so angle is in [0, pi].
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    sin_half = float(np.sqrt(x * x + y * y + z * z))
    angle = 2.0 * float(np.arctan2(sin_half, w))
    if sin_half < _ANGLE_EPS:
        # Small-angle: axis is degenerate; return near-zero rotation
        # vector. The 2 * vec(q_err) approx is exact at first order.
        return np.array([2.0 * x, 2.0 * y, 2.0 * z], dtype=np.float64)
    axis_unit = np.array([x, y, z], dtype=np.float64) / sin_half
    return axis_unit * angle


def _per_axis_mahalanobis_max(
    error: np.ndarray, std: np.ndarray
) -> float:
    """Compute ``max_i(|error_i| / std_i)`` with the convention
    ``0/0 = 0`` and ``!0/0 = +inf``.

    All inputs are shape (3,) float64.
    """
    worst = 0.0
    for err_i, std_i in zip(error, std, strict=True):
        a = float(abs(err_i))
        s = float(std_i)
        term = (0.0 if a == 0.0 else float("inf")) if s == 0.0 else a / s
        worst = max(worst, term)
    return worst


def compute_divergence(
    prediction: BeliefForwardPrediction,
    actual_pose: Pose,
    actual_belief_stamp_sim_ns: int,
) -> PredictionOutcome:
    """Compute ``PredictionOutcome`` from a prediction + actual observation.

    Pure: misma entrada → mismo ``PredictionOutcome``. Sin reloj, sin
    random.

    Raises:

    - ``ValueError`` si ``actual_belief_stamp_sim_ns`` no matchea
      ``prediction.predicted_observation_stamp_sim_ns``. La identidad
      stamp es prerrequisito de comparabilidad.
    """
    if not isinstance(prediction, BeliefForwardPrediction):
        raise TypeError(
            f"prediction must be BeliefForwardPrediction; got "
            f"{type(prediction).__name__}"
        )
    if not isinstance(actual_pose, Pose):
        raise TypeError(
            f"actual_pose must be Pose; got {type(actual_pose).__name__}"
        )
    expected_stamp = prediction.predicted_observation_stamp_sim_ns
    if actual_belief_stamp_sim_ns != expected_stamp:
        raise ValueError(
            f"actual_belief_stamp_sim_ns ({actual_belief_stamp_sim_ns}) "
            f"must equal prediction.predicted_observation_stamp_sim_ns "
            f"({expected_stamp})"
        )

    predicted_pose = prediction.predicted_pose
    predicted_std = prediction.predicted_pose_std

    position_error = (
        actual_pose.position_enu_m - predicted_pose.position_enu_m
    ).astype(np.float64, copy=True)
    position_error_norm = float(np.linalg.norm(position_error))

    orientation_error = _quaternion_error_axis_angle(
        predicted_pose.orientation_q, actual_pose.orientation_q
    )
    orientation_error_norm = float(np.linalg.norm(orientation_error))

    position_mahal = _per_axis_mahalanobis_max(
        position_error, predicted_std.position_std_enu_m
    )
    orientation_mahal = _per_axis_mahalanobis_max(
        orientation_error, predicted_std.orientation_std_rad
    )

    verdict = _verdict_from_max_mahalanobis(
        max(position_mahal, orientation_mahal)
    )

    return PredictionOutcome(
        prediction=prediction,
        actual_belief_stamp_sim_ns=actual_belief_stamp_sim_ns,
        actual_pose=actual_pose,
        position_error_enu_m=position_error,
        position_error_norm_m=position_error_norm,
        orientation_error_rad=orientation_error,
        orientation_error_norm_rad=orientation_error_norm,
        position_mahalanobis_max=position_mahal,
        orientation_mahalanobis_max=orientation_mahal,
        verdict=verdict,
    )


__all__ = [
    "DIVERGENCE_PROTOCOL_VERSION",
    "DivergenceVerdict",
    "PredictionOutcome",
    "compute_divergence",
]
