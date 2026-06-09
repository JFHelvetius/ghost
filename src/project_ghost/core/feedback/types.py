"""Closed-loop feedback types — el shape de "lo que el agente aprendió
de sus predicciones recientes" (ADR-0026).

Stdlib only. Frozen, pure data, content-addressed por construcción.
Primera composición explícita entre ADRs: ``CalibrationHistory`` agrega
evidencia de ``PredictionOutcome`` (ADR-0025) para informar la próxima
ronda de self-assessment (ADR-0020).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

from project_ghost.core.uncertainty.self_assessment import (
    BeliefSelfAssessment,
    SelfAssessmentLevel,
)

FEEDBACK_PROTOCOL_VERSION: Final[int] = 1

# Same posture as ADR-0023 / ADR-0024 taxonomy: snake_case, starts with
# lowercase letter, length 1-64.
_TAXONOMY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_TAXONOMY_MAX_LEN: Final[int] = 64


def _validate_taxonomy(value: str, *, field: str) -> None:
    """Validar identificador snake_case taxonomizado."""
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{field} cannot be empty")
    if len(value) > _TAXONOMY_MAX_LEN:
        raise ValueError(
            f"{field} must be <= {_TAXONOMY_MAX_LEN} chars; got "
            f"len={len(value)}"
        )
    if not _TAXONOMY_PATTERN.match(value):
        raise ValueError(
            f"{field} must match {_TAXONOMY_PATTERN.pattern!r}; got "
            f"{value!r}"
        )


def _validate_nonneg_count(value: int, *, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{field} must be int; got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{field} must be >= 0; got {value}")


def _validate_mahalanobis(value: float, *, field: str) -> None:
    """Mahalanobis puede ser ``+inf`` cuando std=0 y error!=0 — eso es
    legítimo (consistencia con ADR-0025). NaN nunca lo es.
    """
    if math.isnan(value):
        raise ValueError(f"{field} must not be NaN; got {value}")
    if value < 0.0:
        raise ValueError(f"{field} must be >= 0; got {value}")


@dataclass(frozen=True)
class CalibrationHistory:
    """Snapshot agregado de ``PredictionOutcome`` recientes.

    Sirve como entrada determinista a una
    ``CalibrationAdjustmentPolicy``. Construido por
    ``build_calibration_history`` desde un iterable de outcomes
    cronológicos (caller provee el ordering).

    Invariantes:

    - Counts no negativos.
    - ``sum(counts) == outcomes_considered``. Sin esa identidad el
      snapshot no es interpretable.
    - ``worst_*_mahalanobis``: ``>= 0``, no-NaN, ``+inf`` legítimo
      (consistencia con ADR-0025).
    - Cuando ``outcomes_considered == 0``: ambos worst son ``0.0`` y
      ``most_recent_observed_stamp_sim_ns`` es ``None``. Cuando ``> 0``:
      stamp es ``>= 0``.
    """

    outcomes_considered: int
    count_within_1_std: int
    count_beyond_1_std: int
    count_beyond_3_std: int
    count_beyond_5_std: int
    worst_position_mahalanobis: float
    worst_orientation_mahalanobis: float
    most_recent_observed_stamp_sim_ns: int | None
    schema_version: int = FEEDBACK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _validate_nonneg_count(
            self.outcomes_considered, field="outcomes_considered"
        )
        _validate_nonneg_count(
            self.count_within_1_std, field="count_within_1_std"
        )
        _validate_nonneg_count(
            self.count_beyond_1_std, field="count_beyond_1_std"
        )
        _validate_nonneg_count(
            self.count_beyond_3_std, field="count_beyond_3_std"
        )
        _validate_nonneg_count(
            self.count_beyond_5_std, field="count_beyond_5_std"
        )
        counts_sum = (
            self.count_within_1_std
            + self.count_beyond_1_std
            + self.count_beyond_3_std
            + self.count_beyond_5_std
        )
        if counts_sum != self.outcomes_considered:
            raise ValueError(
                f"sum(counts) ({counts_sum}) must equal "
                f"outcomes_considered ({self.outcomes_considered})"
            )
        _validate_mahalanobis(
            self.worst_position_mahalanobis,
            field="worst_position_mahalanobis",
        )
        _validate_mahalanobis(
            self.worst_orientation_mahalanobis,
            field="worst_orientation_mahalanobis",
        )
        if self.outcomes_considered == 0:
            if self.worst_position_mahalanobis != 0.0:
                raise ValueError(
                    "worst_position_mahalanobis must be 0.0 when "
                    f"outcomes_considered == 0; got "
                    f"{self.worst_position_mahalanobis}"
                )
            if self.worst_orientation_mahalanobis != 0.0:
                raise ValueError(
                    "worst_orientation_mahalanobis must be 0.0 when "
                    f"outcomes_considered == 0; got "
                    f"{self.worst_orientation_mahalanobis}"
                )
            if self.most_recent_observed_stamp_sim_ns is not None:
                raise ValueError(
                    "most_recent_observed_stamp_sim_ns must be None "
                    "when outcomes_considered == 0; got "
                    f"{self.most_recent_observed_stamp_sim_ns}"
                )
        else:
            if self.most_recent_observed_stamp_sim_ns is None:
                raise ValueError(
                    "most_recent_observed_stamp_sim_ns must not be None "
                    "when outcomes_considered > 0"
                )
            if self.most_recent_observed_stamp_sim_ns < 0:
                raise ValueError(
                    "most_recent_observed_stamp_sim_ns must be >= 0; "
                    f"got {self.most_recent_observed_stamp_sim_ns}"
                )
        if self.schema_version != FEEDBACK_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {FEEDBACK_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


@dataclass(frozen=True)
class CalibratedSelfAssessment:
    """Envelope que ata un ``BeliefSelfAssessment`` crudo a la
    ``CalibrationHistory`` que lo informa y al nivel overall ajustado.

    El raw assessment viaja inline para auto-contención auditable. La
    composición es explícita: cualquier consumer puede inspeccionar el
    crudo, la evidencia y el ajuste en un solo record.

    Invariantes:

    - ``raw_assessment`` y ``calibration_history`` son los tipos
      correctos.
    - ``adjusted_overall_level`` pertenece al catálogo cerrado
      ``SelfAssessmentLevel``.
    - ``adjustment_policy_id`` y ``adjustment_reason`` son
      taxonomizados snake_case (mismo posture que ADR-0023).
    - El contrato **no** restringe la dirección del ajuste. Una policy
      puede legítimamente upgrade o downgrade el level. La reference
      sólo hace passthrough o downgrade; otras policies pueden hacer
      otra cosa.
    """

    raw_assessment: BeliefSelfAssessment
    calibration_history: CalibrationHistory
    adjusted_overall_level: SelfAssessmentLevel
    adjustment_policy_id: str
    adjustment_reason: str
    schema_version: int = FEEDBACK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.raw_assessment, BeliefSelfAssessment):
            raise TypeError(
                f"raw_assessment must be BeliefSelfAssessment; got "
                f"{type(self.raw_assessment).__name__}"
            )
        if not isinstance(self.calibration_history, CalibrationHistory):
            raise TypeError(
                f"calibration_history must be CalibrationHistory; got "
                f"{type(self.calibration_history).__name__}"
            )
        if not isinstance(
            self.adjusted_overall_level, SelfAssessmentLevel
        ):
            raise TypeError(
                f"adjusted_overall_level must be SelfAssessmentLevel; "
                f"got {type(self.adjusted_overall_level).__name__}"
            )
        _validate_taxonomy(
            self.adjustment_policy_id, field="adjustment_policy_id"
        )
        _validate_taxonomy(
            self.adjustment_reason, field="adjustment_reason"
        )
        if self.schema_version != FEEDBACK_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {FEEDBACK_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


__all__ = [
    "FEEDBACK_PROTOCOL_VERSION",
    "CalibratedSelfAssessment",
    "CalibrationHistory",
]
