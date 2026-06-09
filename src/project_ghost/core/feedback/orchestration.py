"""Orquestación canónica de la capa de feedback (ADR-0026).

``build_calibration_history``: agrega un iterable de
``PredictionOutcome`` (cronológico) en un snapshot ``CalibrationHistory``.

``assess_with_feedback``: one-shot canónico — construye history, llama
al policy, devuelve el ``CalibratedSelfAssessment``. Pure function
(asumiendo policy y outcomes puros).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_ghost.core.prediction.divergence import DivergenceVerdict

from .types import CalibrationHistory

if TYPE_CHECKING:
    from collections.abc import Iterable

    from project_ghost.core.prediction.divergence import PredictionOutcome
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )

    from .protocols import CalibrationAdjustmentPolicy
    from .types import CalibratedSelfAssessment


_DEFAULT_MAX_HISTORY: int = 32


def build_calibration_history(
    outcomes: Iterable[PredictionOutcome],
    max_n: int = _DEFAULT_MAX_HISTORY,
) -> CalibrationHistory:
    """Construye un ``CalibrationHistory`` desde un iterable de outcomes.

    El caller provee outcomes en orden cronológico (más viejos primero).
    Esta función toma los últimos ``max_n`` y agrega counts + worst
    Mahalanobis + stamp más reciente.

    Pure: misma entrada → mismo output.

    Raises ``ValueError`` si ``max_n <= 0``.
    """
    if max_n <= 0:
        raise ValueError(f"max_n must be > 0; got {max_n}")
    materialized = list(outcomes)
    window = materialized[-max_n:] if materialized else []
    if not window:
        return CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )
    counts = {
        DivergenceVerdict.WITHIN_1_STD: 0,
        DivergenceVerdict.BEYOND_1_STD: 0,
        DivergenceVerdict.BEYOND_3_STD: 0,
        DivergenceVerdict.BEYOND_5_STD: 0,
    }
    worst_pos = 0.0
    worst_ori = 0.0
    most_recent_stamp = window[0].actual_belief_stamp_sim_ns
    for outcome in window:
        counts[outcome.verdict] += 1
        worst_pos = max(worst_pos, outcome.position_mahalanobis_max)
        worst_ori = max(worst_ori, outcome.orientation_mahalanobis_max)
        most_recent_stamp = max(most_recent_stamp, outcome.actual_belief_stamp_sim_ns)
    return CalibrationHistory(
        outcomes_considered=len(window),
        count_within_1_std=counts[DivergenceVerdict.WITHIN_1_STD],
        count_beyond_1_std=counts[DivergenceVerdict.BEYOND_1_STD],
        count_beyond_3_std=counts[DivergenceVerdict.BEYOND_3_STD],
        count_beyond_5_std=counts[DivergenceVerdict.BEYOND_5_STD],
        worst_position_mahalanobis=worst_pos,
        worst_orientation_mahalanobis=worst_ori,
        most_recent_observed_stamp_sim_ns=most_recent_stamp,
    )


def assess_with_feedback(
    raw: BeliefSelfAssessment,
    outcomes: Iterable[PredictionOutcome],
    adjustment_policy: CalibrationAdjustmentPolicy,
    max_history: int = _DEFAULT_MAX_HISTORY,
) -> CalibratedSelfAssessment:
    """Compose ``build_calibration_history`` + ``policy.adjust``.

    Pure. Devuelve el ``CalibratedSelfAssessment`` con el raw assessment
    y la history inline.
    """
    history = build_calibration_history(outcomes, max_n=max_history)
    return adjustment_policy.adjust(raw, history)


__all__ = [
    "assess_with_feedback",
    "build_calibration_history",
]
