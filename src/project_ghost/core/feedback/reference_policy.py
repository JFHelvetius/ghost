"""Reference policy: ``MahalanobisDowngradePolicy`` (ADR-0026).

Policy mínima documentada que demuestra que el contrato
``CalibrationAdjustmentPolicy`` es sound.

Regla (frozen):

- Si ``history.outcomes_considered == 0``: passthrough, reason
  ``no_outcomes_yet``.
- Si
  ``history.count_beyond_3_std + history.count_beyond_5_std >=
   downgrade_threshold`` AND
  ``history.outcomes_considered >= min_outcomes``: downgrade un nivel
  (KNOWN → UNCERTAIN, UNCERTAIN → UNKNOWN, UNKNOWN stays). Reason
  ``downgrade_from_calibration``.
- Else: passthrough, reason ``calibration_within_tolerance``.

**No es recomendación operacional.** Es la policy más simple que
valida la composición. Operadores reales construyen policies con más
contexto (per-axis, hysteresis, recency-weighted) que implementan el
mismo Protocol sin reabrir el envelope.

Determinista, pure, stdlib only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from project_ghost.core.uncertainty.self_assessment import (
    SelfAssessmentLevel,
)

from .types import CalibratedSelfAssessment

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )

    from .types import CalibrationHistory


_REASON_NO_OUTCOMES: Final[str] = "no_outcomes_yet"
_REASON_DOWNGRADE: Final[str] = "downgrade_from_calibration"
_REASON_WITHIN_TOLERANCE: Final[str] = "calibration_within_tolerance"

_DOWNGRADE: Final[dict[SelfAssessmentLevel, SelfAssessmentLevel]] = {
    SelfAssessmentLevel.KNOWN: SelfAssessmentLevel.UNCERTAIN,
    SelfAssessmentLevel.UNCERTAIN: SelfAssessmentLevel.UNKNOWN,
    SelfAssessmentLevel.UNKNOWN: SelfAssessmentLevel.UNKNOWN,
}


class MahalanobisDowngradePolicy:
    """Reference policy: downgrade un nivel si los outcomes recientes
    muestran overconfidence.

    Parameters:

    - ``min_outcomes``: número mínimo de outcomes requeridos para
      considerar la evidencia significativa. Por debajo de esto la
      policy hace passthrough con reason ``no_outcomes_yet`` (cuando
      es 0) o ``calibration_within_tolerance`` (cuando es positivo
      pero < min). Default 4.
    - ``downgrade_threshold``: número mínimo de outcomes con verdict
      beyond_3_std o peor para gatillar el downgrade. Default 2.

    Ambos parámetros forman parte del ``policy_id`` para que dos
    instancias con parámetros distintos produzcan ajustes
    inequívocamente distinguibles en MCAP.
    """

    POLICY_ID_BASE: ClassVar[str] = "mahalanobis_downgrade_v1"

    def __init__(self, *, min_outcomes: int = 4, downgrade_threshold: int = 2) -> None:
        if min_outcomes < 0:
            raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
        if downgrade_threshold < 1:
            raise ValueError(f"downgrade_threshold must be >= 1; got {downgrade_threshold}")
        self._min_outcomes: int = min_outcomes
        self._downgrade_threshold: int = downgrade_threshold
        self._policy_id: str = f"{self.POLICY_ID_BASE}_min{min_outcomes}_thr{downgrade_threshold}"

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def min_outcomes(self) -> int:
        return self._min_outcomes

    @property
    def downgrade_threshold(self) -> int:
        return self._downgrade_threshold

    def adjust(
        self,
        raw: BeliefSelfAssessment,
        history: CalibrationHistory,
    ) -> CalibratedSelfAssessment:
        if history.outcomes_considered == 0:
            return CalibratedSelfAssessment(
                raw_assessment=raw,
                calibration_history=history,
                adjusted_overall_level=raw.overall_level,
                adjustment_policy_id=self._policy_id,
                adjustment_reason=_REASON_NO_OUTCOMES,
            )
        beyond_3_or_worse = history.count_beyond_3_std + history.count_beyond_5_std
        should_downgrade = (
            history.outcomes_considered >= self._min_outcomes
            and beyond_3_or_worse >= self._downgrade_threshold
        )
        if should_downgrade:
            adjusted = _DOWNGRADE[raw.overall_level]
            reason = _REASON_DOWNGRADE
        else:
            adjusted = raw.overall_level
            reason = _REASON_WITHIN_TOLERANCE
        return CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=adjusted,
            adjustment_policy_id=self._policy_id,
            adjustment_reason=reason,
        )


__all__ = ["MahalanobisDowngradePolicy"]
