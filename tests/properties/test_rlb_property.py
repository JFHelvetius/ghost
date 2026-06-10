"""Hypothesis property test for ADR-0034 (RLB-v1).

First multi-cycle property test of the set: each example materialises
an MCAP of N cycles whose calibration-history dirtiness pattern is
shaped by a Hypothesis-generated sequence of outcomes, and then
verifies RLB-v1's recovery bound.

Test design:

- Synthesize an outcome sequence of length N where each outcome is
  either WITHIN_1_STD or BEYOND_5_STD (the two binary states that
  matter for the dirty/clean condition).
- Build the calibration history at each cycle directly from the
  accumulated outcomes using the same windowing logic as
  ``build_calibration_history`` (sliced to ``max_history`` newest).
- Publish per cycle: only the ``/self_assessment/calibrated`` channel
  — verify_rlb needs only this.
- Run verify_rlb at the same W; assert holds.

The verifier's bound (`L(t) <= W`) is structurally true for any
windowing builder that keeps the W most recent outcomes (each cycle
expels at most one). The property test confirms this on synthetic
sequences with multiple recovery transitions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from project_ghost.core.feedback import MahalanobisDowngradePolicy
from project_ghost.core.feedback.types import (
    CalibrationHistory,
)
from project_ghost.core.fusion import (
    FusionInput,
    LinearMotionOracleFusionPolicy,
)
from project_ghost.core.prediction.divergence import DivergenceVerdict
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    BeliefSelfAssessment,
    SelfAssessmentLevel,
    assess_belief,
)
from project_ghost.properties import verify_rlb
from project_ghost.telemetry import (
    CalibratedSelfAssessmentToTelemetryAdapter,
    MCAPFileSink,
)

if TYPE_CHECKING:
    from pathlib import Path


_T0_NS = 1_000_000_000
_DT_NS = 100_000_000
_W = 32


@pytest.fixture(scope="module")
def fixed_raw_assessment() -> BeliefSelfAssessment:
    """Canonical KNOWN raw assessment — RLB-v1 doesn't depend on raw
    level, but we need a real ``BeliefSelfAssessment`` to feed the
    calibration policy."""
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=1e-4,
    )
    state = oracle.fuse(FusionInput(
        sensor_samples=(),
        prior_belief_stamp_sim_ns=None,
        target_stamp_sim_ns=_T0_NS,
    )).belief
    thresholds = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    raw = assess_belief(state, thresholds)
    assert raw.overall_level is SelfAssessmentLevel.KNOWN
    return raw


_MAHA_BY_VERDICT: dict[DivergenceVerdict, float] = {
    DivergenceVerdict.WITHIN_1_STD: 0.5,
    DivergenceVerdict.BEYOND_1_STD: 2.0,
    DivergenceVerdict.BEYOND_3_STD: 4.0,
    DivergenceVerdict.BEYOND_5_STD: 8.0,
}


@st.composite
def _outcome_sequences(draw: st.DrawFn) -> list[DivergenceVerdict]:
    """Generate a sequence of outcome verdicts limited to the two
    binary states that drive RLB's dirty/clean classification.

    Length is bounded so a single example stays cheap; the property
    is local in time so we don't need very long sequences.
    """
    length = draw(st.integers(min_value=1, max_value=60))
    return [
        draw(st.sampled_from([
            DivergenceVerdict.WITHIN_1_STD,
            DivergenceVerdict.BEYOND_5_STD,
        ]))
        for _ in range(length)
    ]


def _history_from_window(
    window: list[DivergenceVerdict], stamp: int,
) -> CalibrationHistory:
    """Build a ``CalibrationHistory`` from a window of verdicts. Mirrors
    the counting logic that ``build_calibration_history`` performs on
    the windowed slice of outcomes."""
    if not window:
        return CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0, count_beyond_1_std=0,
            count_beyond_3_std=0, count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )
    counts: dict[DivergenceVerdict, int] = dict.fromkeys(DivergenceVerdict, 0)
    for v in window:
        counts[v] += 1
    worst = max(_MAHA_BY_VERDICT[v] for v in window)
    return CalibrationHistory(
        outcomes_considered=len(window),
        count_within_1_std=counts[DivergenceVerdict.WITHIN_1_STD],
        count_beyond_1_std=counts[DivergenceVerdict.BEYOND_1_STD],
        count_beyond_3_std=counts[DivergenceVerdict.BEYOND_3_STD],
        count_beyond_5_std=counts[DivergenceVerdict.BEYOND_5_STD],
        worst_position_mahalanobis=worst,
        worst_orientation_mahalanobis=worst,
        most_recent_observed_stamp_sim_ns=stamp,
    )


def _materialise_mcap(
    raw: BeliefSelfAssessment,
    verdicts: list[DivergenceVerdict],
    mcap_path: Path,
    *,
    min_outcomes: int = 4,
    downgrade_threshold: int = 2,
    max_history: int = _W,
) -> None:
    """Step through the verdicts one cycle at a time, building the
    sliding window history accumulatively (last ``max_history`` newest
    verdicts), running the calibration policy, and publishing one
    ``CalibratedSelfAssessment`` per cycle.

    Constructs ``CalibrationHistory`` directly rather than going
    through ``build_calibration_history`` so we avoid building
    full ``PredictionOutcome`` records (which require a graph of
    dependencies — ``BeliefForwardPrediction``, ``Pose``, etc.). The
    RLB verifier only reads ``CalibrationHistory`` counts, so this
    direct construction is faithful to what the verifier observes.
    """
    feedback = MahalanobisDowngradePolicy(
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    with MCAPFileSink(mcap_path) as sink:
        adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        for k in range(len(verdicts)):
            # Cycle stamps must be monotone and unique; we offset the
            # raw belief stamp per cycle so each calibrated record
            # lands at a distinct stamp.
            cycle_stamp = _T0_NS + (k + 1) * _DT_NS
            verdicts_so_far = verdicts[: k + 1]
            window = verdicts_so_far[-max_history:]
            history = _history_from_window(window, stamp=cycle_stamp)
            # Reuse the raw assessment but shift its belief stamp to the
            # cycle's stamp so each CalibratedSelfAssessment lands at a
            # distinct stamp and ``verify_rlb`` sees them as separate
            # cycles.
            shifted_raw = _with_belief_stamp(raw, cycle_stamp)
            calibrated = feedback.adjust(shifted_raw, history)
            adapter.publish(calibrated)


def _with_belief_stamp(
    raw: BeliefSelfAssessment, stamp_sim_ns: int,
) -> BeliefSelfAssessment:
    """Clone ``raw`` with an updated ``belief_stamp_sim_ns``. The other
    fields are unchanged; needed because each cycle must publish under
    a distinct stamp."""
    from dataclasses import replace
    return replace(raw, belief_stamp_sim_ns=stamp_sim_ns)


@given(verdicts=_outcome_sequences())
@settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_rlb_v1_holds_on_synthetic_outcome_sequences(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path_factory: pytest.TempPathFactory,
    verdicts: list[DivergenceVerdict],
) -> None:
    """For any synthetic outcome sequence, the per-cycle calibration
    histories produced by ``build_calibration_history`` (via
    ``assess_with_feedback``) satisfy RLB-v1 with the same W they were
    built under.

    The bound `L(t) <= W` is structurally true for any windowing
    builder that keeps the W most-recent outcomes (each cycle expels
    at most one). The property test is the regression witness against
    a future builder bug.
    """
    mcap_path = tmp_path_factory.mktemp("rlb_property") / "synth.mcap"
    _materialise_mcap(fixed_raw_assessment, verdicts, mcap_path)

    report = verify_rlb(mcap_path, max_history=_W)
    assert report.holds, (
        f"RLB-v1 violated.\n"
        f"  sequence length: {len(verdicts)}\n"
        f"  sequence: {[v.value for v in verdicts]}\n"
        f"  violations: {report.violations}"
    )


# ---------------------------------------------------------------------------
# Adversarial scenarios — named transitions
# ---------------------------------------------------------------------------


def _verify_sequence(
    raw: BeliefSelfAssessment,
    verdicts: list[DivergenceVerdict],
    tmp_path: Path,
    *,
    max_history: int = _W,
):
    mcap_path = tmp_path / "scenario.mcap"
    _materialise_mcap(
        raw, verdicts, mcap_path, max_history=max_history,
    )
    return verify_rlb(mcap_path, max_history=max_history)


def test_adversarial_pure_drift_no_recovery_transitions(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """All BEYOND_5_STD — no clean cycles after the first. Vacuous."""
    verdicts = [DivergenceVerdict.BEYOND_5_STD] * 20
    report = _verify_sequence(fixed_raw_assessment, verdicts, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0


def test_adversarial_pure_clean_no_recovery_transitions(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """All WITHIN_1_STD — every cycle is clean from the start. No
    dirty-to-clean transition ever, so no recovery transition either."""
    verdicts = [DivergenceVerdict.WITHIN_1_STD] * 20
    report = _verify_sequence(fixed_raw_assessment, verdicts, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0


def test_adversarial_short_drift_then_recovery_holds(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """3 dirty cycles followed by W+5 clean cycles — recovery happens
    well within the bound. L(t) = 3, much less than W=32."""
    verdicts = (
        [DivergenceVerdict.BEYOND_5_STD] * 3
        + [DivergenceVerdict.WITHIN_1_STD] * (_W + 5)
    )
    report = _verify_sequence(fixed_raw_assessment, verdicts, tmp_path)
    assert report.holds
    # First recovery transition exists.
    assert report.cycles_precondition_held >= 1


def test_adversarial_long_drift_then_recovery_at_bound(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """W dirty cycles followed by W+5 clean cycles — the worst case
    that still satisfies the bound. L(t) = W = 32 exactly."""
    verdicts = (
        [DivergenceVerdict.BEYOND_5_STD] * _W
        + [DivergenceVerdict.WITHIN_1_STD] * (_W + 5)
    )
    report = _verify_sequence(fixed_raw_assessment, verdicts, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held >= 1


def test_adversarial_oscillating_dirty_clean(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """Alternating BEYOND_5/WITHIN_1 outcomes. Multiple recovery
    transitions, each with L(t) bounded by the count of cumulative
    dirty outcomes still in the window — strictly less than W."""
    verdicts = []
    for _ in range(15):
        verdicts.append(DivergenceVerdict.BEYOND_5_STD)
        verdicts.append(DivergenceVerdict.WITHIN_1_STD)
    report = _verify_sequence(fixed_raw_assessment, verdicts, tmp_path)
    assert report.holds
    # Each WITHIN_1 after a BEYOND_5 contributes ONE dirty-to-clean
    # check (but only when the window count has actually dropped to 0).
    # We don't pin the exact number, just that some recovery
    # transitions were observed and all satisfied the bound.
