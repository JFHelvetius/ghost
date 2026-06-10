"""Hypothesis property test for ADR-0033 (MD-v1).

Where the BAUD/ERUR property tests fix the raw assessment to KNOWN
(the binding worst-case for the *behavioural* properties), MD's
interesting variation is across the **raw level itself**. We construct
three KNOWN/UNCERTAIN/UNKNOWN raw fixtures by parametrising the fusion
oracle's ``covariance_diag`` against the ADR-0020 thresholds, then let
Hypothesis pick which raw to use for each example.

For each (raw_level, M, K, CalibrationHistory):

- materialise a single-cycle MCAP through the real calibration policy
- run ``verify_md``
- assert ``holds``

The reference policy can either passthrough (adj == raw) or downgrade
(adj > raw in the lattice). Both branches satisfy MD-v1; the test
sweeps the full 3x3 raw x adjusted product so every legal transition
is witnessed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from project_ghost.core.feedback import MahalanobisDowngradePolicy
from project_ghost.core.feedback.types import CalibrationHistory
from project_ghost.core.fusion import (
    FusionInput,
    LinearMotionOracleFusionPolicy,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    BeliefSelfAssessment,
    SelfAssessmentLevel,
    assess_belief,
)
from project_ghost.properties import verify_md
from project_ghost.telemetry import (
    CalibratedSelfAssessmentToTelemetryAdapter,
    MCAPFileSink,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixed pipeline scaffolding — one raw assessment per level
# ---------------------------------------------------------------------------

_T0_NS = 1_000_000_000

# Covariance values chosen against ADR-0020 thresholds
# (position_known_std_m=0.05, position_unknown_std_m=0.5):
# - 1e-4   -> std=0.01  -> KNOWN
# - 0.04   -> std=0.20  -> UNCERTAIN (between known and unknown stds)
# - 1.0    -> std=1.00  -> UNKNOWN
_COVARIANCE_FOR_LEVEL: dict[SelfAssessmentLevel, float] = {
    SelfAssessmentLevel.KNOWN: 1e-4,
    SelfAssessmentLevel.UNCERTAIN: 0.04,
    SelfAssessmentLevel.UNKNOWN: 1.0,
}


def _build_raw_at_level(
    level: SelfAssessmentLevel,
) -> BeliefSelfAssessment:
    """Build a ``BeliefSelfAssessment`` whose ``overall_level`` is
    exactly ``level`` by picking the covariance against ADR-0020
    thresholds.
    """
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_FOR_LEVEL[level],
    )
    state = oracle.fuse(
        FusionInput(
            sensor_samples=(),
            prior_belief_stamp_sim_ns=None,
            target_stamp_sim_ns=_T0_NS,
        )
    ).belief
    thresholds = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    raw = assess_belief(state, thresholds)
    assert raw.overall_level is level, (
        f"covariance {_COVARIANCE_FOR_LEVEL[level]} did not produce "
        f"the expected level {level}; got {raw.overall_level}"
    )
    return raw


@pytest.fixture(scope="module")
def raws_by_level() -> dict[SelfAssessmentLevel, BeliefSelfAssessment]:
    """Three canonical raw assessments, one per level. Module-scoped so
    Hypothesis examples reuse without rebuilding 1500 times."""
    return {level: _build_raw_at_level(level) for level in _LEVELS}


_LEVELS: tuple[SelfAssessmentLevel, ...] = (
    SelfAssessmentLevel.KNOWN,
    SelfAssessmentLevel.UNCERTAIN,
    SelfAssessmentLevel.UNKNOWN,
)


# ---------------------------------------------------------------------------
# Calibration history strategy (same shape as BAUD/ERUR property tests)
# ---------------------------------------------------------------------------

_MAX_COUNT_PER_BAND = 20
_MAX_MAHALANOBIS = 50.0


@st.composite
def _calibration_histories(draw: st.DrawFn) -> CalibrationHistory:
    c_within = draw(st.integers(0, _MAX_COUNT_PER_BAND))
    c_b1 = draw(st.integers(0, _MAX_COUNT_PER_BAND))
    c_b3 = draw(st.integers(0, _MAX_COUNT_PER_BAND))
    c_b5 = draw(st.integers(0, _MAX_COUNT_PER_BAND))
    total = c_within + c_b1 + c_b3 + c_b5

    if total == 0:
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
    worst_pos = draw(
        st.floats(
            min_value=0.0,
            max_value=_MAX_MAHALANOBIS,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    worst_ori = draw(
        st.floats(
            min_value=0.0,
            max_value=_MAX_MAHALANOBIS,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    stamp = draw(st.integers(min_value=0, max_value=10**15))
    return CalibrationHistory(
        outcomes_considered=total,
        count_within_1_std=c_within,
        count_beyond_1_std=c_b1,
        count_beyond_3_std=c_b3,
        count_beyond_5_std=c_b5,
        worst_position_mahalanobis=worst_pos,
        worst_orientation_mahalanobis=worst_ori,
        most_recent_observed_stamp_sim_ns=stamp,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_single_cycle_calibration_only(
    raw: BeliefSelfAssessment,
    history: CalibrationHistory,
    *,
    min_outcomes: int,
    downgrade_threshold: int,
    mcap_path: Path,
) -> None:
    """Run only the calibration step and publish the result. MD-v1
    needs nothing else from the pipeline — no decision, no actuation.
    """
    feedback = MahalanobisDowngradePolicy(
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    calibrated = feedback.adjust(raw, history)

    with MCAPFileSink(mcap_path) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(calibrated)


def _history(
    *,
    within: int = 0,
    b1: int = 0,
    b3: int = 0,
    b5: int = 0,
    worst_pos: float = 0.0,
    worst_ori: float = 0.0,
    stamp: int | None = None,
) -> CalibrationHistory:
    total = within + b1 + b3 + b5
    if total == 0:
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
    return CalibrationHistory(
        outcomes_considered=total,
        count_within_1_std=within,
        count_beyond_1_std=b1,
        count_beyond_3_std=b3,
        count_beyond_5_std=b5,
        worst_position_mahalanobis=worst_pos,
        worst_orientation_mahalanobis=worst_ori,
        most_recent_observed_stamp_sim_ns=stamp if stamp is not None else _T0_NS,
    )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(
    raw_level=st.sampled_from(_LEVELS),
    min_outcomes=st.integers(min_value=0, max_value=8),
    downgrade_threshold=st.integers(min_value=1, max_value=8),
    history=_calibration_histories(),
)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_md_v1_holds_across_all_raw_levels(
    raws_by_level: dict[SelfAssessmentLevel, BeliefSelfAssessment],
    tmp_path_factory: pytest.TempPathFactory,
    raw_level: SelfAssessmentLevel,
    min_outcomes: int,
    downgrade_threshold: int,
    history: CalibrationHistory,
) -> None:
    """Canonical MD-v1 property test, swept across all three raw
    levels and the full (M, K, history) space."""
    raw = raws_by_level[raw_level]

    mcap_path = tmp_path_factory.mktemp("md_property") / "synthetic.mcap"
    _run_single_cycle_calibration_only(
        raw,
        history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )

    report = verify_md(mcap_path)
    assert report.holds, (
        f"MD-v1 violated by synthetic run.\n"
        f"  raw_level: {raw_level.value}\n"
        f"  params: M={min_outcomes}, K={downgrade_threshold}\n"
        f"  history: outcomes_considered={history.outcomes_considered}, "
        f"counts=({history.count_within_1_std}, "
        f"{history.count_beyond_1_std}, "
        f"{history.count_beyond_3_std}, "
        f"{history.count_beyond_5_std})\n"
        f"  violations: {report.violations}"
    )


# ---------------------------------------------------------------------------
# Adversarial scenarios — named transitions in the 3x3 matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_level", _LEVELS)
def test_adversarial_passthrough_at_all_raw_levels_holds(
    raws_by_level: dict[SelfAssessmentLevel, BeliefSelfAssessment],
    tmp_path: Path,
    raw_level: SelfAssessmentLevel,
) -> None:
    """Empty history → passthrough at every raw level. adj == raw, MD
    holds (equality at lattice). Witnesses three of the nine cells
    in the raw-x-adjusted matrix."""
    raw = raws_by_level[raw_level]
    mcap_path = tmp_path / f"passthrough_{raw_level.value}.mcap"
    _run_single_cycle_calibration_only(
        raw,
        _history(),
        min_outcomes=4,
        downgrade_threshold=2,
        mcap_path=mcap_path,
    )
    report = verify_md(mcap_path)
    assert report.holds


@pytest.mark.parametrize("raw_level", _LEVELS)
def test_adversarial_downgrade_storm_at_all_raw_levels_holds(
    raws_by_level: dict[SelfAssessmentLevel, BeliefSelfAssessment],
    tmp_path: Path,
    raw_level: SelfAssessmentLevel,
) -> None:
    """K threshold reached with M-guard satisfied → downgrade at every
    raw level. Witnesses the three diagonal downgrade transitions in
    the raw-x-adjusted matrix:

    - KNOWN → UNCERTAIN
    - UNCERTAIN → UNKNOWN
    - UNKNOWN → UNKNOWN (idempotent; downgrade map stays at lattice top)

    All three satisfy MD (adj_num >= raw_num).
    """
    raw = raws_by_level[raw_level]
    history = _history(b5=10, worst_pos=42.0)
    mcap_path = tmp_path / f"downgrade_{raw_level.value}.mcap"
    _run_single_cycle_calibration_only(
        raw,
        history,
        min_outcomes=4,
        downgrade_threshold=2,
        mcap_path=mcap_path,
    )
    report = verify_md(mcap_path)
    assert report.holds
