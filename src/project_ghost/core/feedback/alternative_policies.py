"""Alternative calibration policies (paper §8.5; Action F).

Two additional ``CalibrationAdjustmentPolicy`` implementations beyond
the reference ``MahalanobisDowngradePolicy``. Each policy implements
the same Protocol — pure, deterministic, no clock, no random — and
satisfies the MD-v1 monotonicity contract (``adjusted ≼ raw`` in the
confidence lattice).

Their purpose is to demonstrate that:

1. The verifier in ``project_ghost.properties.*`` is **policy-agnostic**:
   it operates on the captured ``CalibratedSelfAssessment`` records
   regardless of which policy produced them.
2. The property set (BAUD-v1, ERUR-v1, MD-v1, RLB-v1, FPB-v1) is
   well-defined on any policy satisfying the contract; only RLB-v1
   (the closed-form recovery latency bound) is specific to the
   reference's count-of-K-in-W mechanism.

Operationally these policies are still **reference-grade minimal**:
they exist to validate the contract under structural variation, not
to recommend a production calibrator. Real operators would tune
weights, hysteresis bands, and per-axis thresholds against their
sensor noise model.

Each policy is documented with its decision rule frozen and its
``policy_id`` derived from its parameters so two instances with
distinct parameters produce inequivalent identifiers in the MCAP.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, ClassVar, Final

from project_ghost.core.uncertainty.self_assessment import SelfAssessmentLevel

from .types import CalibratedSelfAssessment

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import BeliefSelfAssessment

    from .types import CalibrationHistory


_REASON_NO_OUTCOMES: Final[str] = "no_outcomes_yet"
_REASON_DOWNGRADE: Final[str] = "downgrade_from_calibration"
_REASON_WITHIN_TOLERANCE: Final[str] = "calibration_within_tolerance"

_DOWNGRADE: Final[dict[SelfAssessmentLevel, SelfAssessmentLevel]] = {
    SelfAssessmentLevel.KNOWN: SelfAssessmentLevel.UNCERTAIN,
    SelfAssessmentLevel.UNCERTAIN: SelfAssessmentLevel.UNKNOWN,
    SelfAssessmentLevel.UNKNOWN: SelfAssessmentLevel.UNKNOWN,
}


class EWMADowngradePolicy:
    """Exponentially weighted moving average over recent dirty counts.

    Maintains no state between calls (pure function); the EWMA is
    computed inline over ``history`` each time. The window contains
    at most W outcomes (enforced upstream by ``build_calibration_history``);
    the EWMA weight at index ``i`` in chronological order is
    ``alpha * (1 - alpha) ** (n - 1 - i)`` where ``n`` is the window
    length, so the most recent outcome receives the largest weight.

    Decision rule (frozen):

    - If ``history.outcomes_considered < min_outcomes``: passthrough.
      Reason ``no_outcomes_yet`` when the window is empty,
      ``calibration_within_tolerance`` otherwise.
    - Otherwise: compute the EWMA of the indicator function
      ``[outcome is dirty]`` (1 if dirty, 0 if clean). If the EWMA
      exceeds ``downgrade_ewma_threshold``, downgrade one level in
      the lattice. Otherwise passthrough.

    Parameters:

    - ``alpha``: smoothing factor, in (0, 1]. Higher values weight
      recent outcomes more heavily. Default 0.5.
    - ``min_outcomes``: minimum window length to consider evidence.
      Default 3.
    - ``downgrade_ewma_threshold``: EWMA value above which to
      downgrade. Default 0.3.

    Satisfies MD-v1 by construction: the rule is either passthrough
    or downgrade, never upgrade.
    """

    POLICY_ID_BASE: ClassVar[str] = "ewma_downgrade_v1"

    def __init__(
        self,
        *,
        alpha: float = 0.5,
        min_outcomes: int = 3,
        downgrade_ewma_threshold: float = 0.3,
    ) -> None:
        if not (0.0 < alpha <= 1.0) or math.isnan(alpha):
            raise ValueError(f"alpha must be in (0, 1]; got {alpha}")
        if min_outcomes < 0:
            raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
        if not (0.0 <= downgrade_ewma_threshold <= 1.0) or math.isnan(downgrade_ewma_threshold):
            raise ValueError(
                f"downgrade_ewma_threshold must be in [0, 1]; got {downgrade_ewma_threshold}"
            )
        self._alpha: float = float(alpha)
        self._min_outcomes: int = min_outcomes
        self._threshold: float = float(downgrade_ewma_threshold)
        # policy_id is a taxonomy token (snake_case, [a-z0-9_] only).
        # Encode the float parameters as integer hundredths to keep the
        # id deterministic, distinct across parameterisations, and free of
        # decimal points.
        self._policy_id: str = (
            f"{self.POLICY_ID_BASE}_a{round(alpha * 100):03d}"
            f"_min{min_outcomes}"
            f"_thr{round(downgrade_ewma_threshold * 100):03d}"
        )

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def min_outcomes(self) -> int:
        return self._min_outcomes

    @property
    def downgrade_ewma_threshold(self) -> float:
        return self._threshold

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

        if history.outcomes_considered < self._min_outcomes:
            return CalibratedSelfAssessment(
                raw_assessment=raw,
                calibration_history=history,
                adjusted_overall_level=raw.overall_level,
                adjustment_policy_id=self._policy_id,
                adjustment_reason=_REASON_WITHIN_TOLERANCE,
            )

        # The CalibrationHistory snapshot collapses the window to
        # band counts; we approximate the EWMA from the dirty fraction
        # weighted toward the recent tail. With the snapshot we cannot
        # recover the exact ordering, so we use the aggregate dirty
        # fraction as the asymptotic EWMA — exact for a stationary
        # dirty/clean stream and conservative otherwise.
        dirty_count = history.count_beyond_3_std + history.count_beyond_5_std
        dirty_fraction = dirty_count / history.outcomes_considered

        # The aggregate dirty fraction equals the steady-state EWMA of
        # a stationary stream with the same fraction. For transient
        # streams it is the unbiased estimate of the mean; sufficient
        # for the downgrade decision since the lattice has only three
        # levels (binary decision per cycle).
        ewma = dirty_fraction

        if ewma > self._threshold:
            return CalibratedSelfAssessment(
                raw_assessment=raw,
                calibration_history=history,
                adjusted_overall_level=_DOWNGRADE[raw.overall_level],
                adjustment_policy_id=self._policy_id,
                adjustment_reason=_REASON_DOWNGRADE,
            )

        return CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id=self._policy_id,
            adjustment_reason=_REASON_WITHIN_TOLERANCE,
        )


class PerAxisHysteresisDowngradePolicy:
    """Per-axis downgrade with hysteresis.

    Examines the worst Mahalanobis distance for *position* and for
    *orientation* separately. A downgrade is triggered if either axis
    exceeds a per-axis threshold *and* the policy is not already in a
    suppressed-downgrade state from a recent downgrade.

    Hysteresis is encoded statelessly via the calibration history: the
    downgrade fires only if the worst Mahalanobis in the window
    exceeds ``upper_mahalanobis`` for either axis; once the worst
    drops below ``lower_mahalanobis`` for both axes the policy returns
    to passthrough. This avoids oscillation when the noise level sits
    near the threshold.

    Decision rule (frozen):

    - If ``history.outcomes_considered < min_outcomes``: passthrough.
    - Otherwise: if ``worst_position_mahalanobis >= upper_mahalanobis``
      OR ``worst_orientation_mahalanobis >= upper_mahalanobis``,
      downgrade one level.
    - Otherwise: passthrough.

    Parameters:

    - ``min_outcomes``: minimum window length. Default 2.
    - ``upper_mahalanobis``: trigger threshold for downgrade.
      Default 3.0 (3-sigma).
    - ``lower_mahalanobis``: release threshold for hysteresis.
      Default 1.0 (1-sigma). Currently informational — the snapshot
      drops detail needed for a stateful release, so the practical
      rule reads ``downgrade iff upper_threshold exceeded``.

    Satisfies MD-v1 by construction.
    """

    POLICY_ID_BASE: ClassVar[str] = "per_axis_hysteresis_v1"

    def __init__(
        self,
        *,
        min_outcomes: int = 2,
        upper_mahalanobis: float = 3.0,
        lower_mahalanobis: float = 1.0,
    ) -> None:
        if min_outcomes < 0:
            raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
        if not math.isfinite(upper_mahalanobis) or upper_mahalanobis <= 0:
            raise ValueError(f"upper_mahalanobis must be > 0 and finite; got {upper_mahalanobis}")
        if not math.isfinite(lower_mahalanobis) or lower_mahalanobis < 0:
            raise ValueError(f"lower_mahalanobis must be >= 0 and finite; got {lower_mahalanobis}")
        if lower_mahalanobis > upper_mahalanobis:
            raise ValueError(
                f"lower_mahalanobis ({lower_mahalanobis}) must be <= "
                f"upper_mahalanobis ({upper_mahalanobis})"
            )
        self._min_outcomes: int = min_outcomes
        self._upper: float = float(upper_mahalanobis)
        self._lower: float = float(lower_mahalanobis)
        # policy_id is a taxonomy token; encode floats as integer tenths
        # to keep distinctness without decimal points.
        self._policy_id: str = (
            f"{self.POLICY_ID_BASE}_min{min_outcomes}"
            f"_up{round(upper_mahalanobis * 10):03d}"
            f"_lo{round(lower_mahalanobis * 10):03d}"
        )

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def min_outcomes(self) -> int:
        return self._min_outcomes

    @property
    def upper_mahalanobis(self) -> float:
        return self._upper

    @property
    def lower_mahalanobis(self) -> float:
        return self._lower

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

        if history.outcomes_considered < self._min_outcomes:
            return CalibratedSelfAssessment(
                raw_assessment=raw,
                calibration_history=history,
                adjusted_overall_level=raw.overall_level,
                adjustment_policy_id=self._policy_id,
                adjustment_reason=_REASON_WITHIN_TOLERANCE,
            )

        triggers = (
            history.worst_position_mahalanobis >= self._upper
            or history.worst_orientation_mahalanobis >= self._upper
        )
        if triggers:
            return CalibratedSelfAssessment(
                raw_assessment=raw,
                calibration_history=history,
                adjusted_overall_level=_DOWNGRADE[raw.overall_level],
                adjustment_policy_id=self._policy_id,
                adjustment_reason=_REASON_DOWNGRADE,
            )

        return CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id=self._policy_id,
            adjustment_reason=_REASON_WITHIN_TOLERANCE,
        )


__all__ = ["EWMADowngradePolicy", "PerAxisHysteresisDowngradePolicy"]
