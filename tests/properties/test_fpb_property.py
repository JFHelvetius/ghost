"""Hypothesis property test for ADR-0035 (FPB-v1).

FPB-v1 is observational. The property test confirms two structural
invariants:

1. With default ``max_fire_fraction=1.0``, every synthetic MCAP holds
   trivially (observer mode).
2. For single-cycle MCAPs, the observed ``fire_fraction`` is either
   ``0.0`` (precondition didn't fire) or ``1.0`` (precondition fired),
   and matches the BAUD precondition evaluated directly on the
   history.
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
from project_ghost.properties import verify_fpb
from project_ghost.telemetry import (
    CalibratedSelfAssessmentToTelemetryAdapter,
    MCAPFileSink,
)

if TYPE_CHECKING:
    from pathlib import Path


_T0_NS = 1_000_000_000


@pytest.fixture(scope="module")
def fixed_raw_assessment() -> BeliefSelfAssessment:
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
            count_within_1_std=0, count_beyond_1_std=0,
            count_beyond_3_std=0, count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )
    return CalibrationHistory(
        outcomes_considered=total,
        count_within_1_std=c_within,
        count_beyond_1_std=c_b1,
        count_beyond_3_std=c_b3,
        count_beyond_5_std=c_b5,
        worst_position_mahalanobis=draw(st.floats(
            0.0, _MAX_MAHALANOBIS, allow_nan=False, allow_infinity=False,
        )),
        worst_orientation_mahalanobis=draw(st.floats(
            0.0, _MAX_MAHALANOBIS, allow_nan=False, allow_infinity=False,
        )),
        most_recent_observed_stamp_sim_ns=draw(
            st.integers(0, 10**15),
        ),
    )


def _materialise_single_cycle(
    raw: BeliefSelfAssessment,
    history: CalibrationHistory,
    *,
    min_outcomes: int,
    downgrade_threshold: int,
    mcap_path: Path,
) -> None:
    feedback = MahalanobisDowngradePolicy(
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    calibrated = feedback.adjust(raw, history)
    with MCAPFileSink(mcap_path) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(calibrated)


@given(
    min_outcomes=st.integers(min_value=0, max_value=8),
    downgrade_threshold=st.integers(min_value=1, max_value=8),
    history=_calibration_histories(),
)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_default_observer_never_fails(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path_factory: pytest.TempPathFactory,
    min_outcomes: int,
    downgrade_threshold: int,
    history: CalibrationHistory,
) -> None:
    """With default ``max_fire_fraction=1.0``, FPB is a pure observer."""
    mcap_path = tmp_path_factory.mktemp("fpb_obs") / "synth.mcap"
    _materialise_single_cycle(
        fixed_raw_assessment, history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )
    report = verify_fpb(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    assert report.holds
    # Single-cycle MCAP: fire_fraction is either 0.0 or 1.0 exactly.
    assert report.fire_fraction in (0.0, 1.0)


@given(
    min_outcomes=st.integers(min_value=0, max_value=8),
    downgrade_threshold=st.integers(min_value=1, max_value=8),
    history=_calibration_histories(),
)
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fire_fraction_matches_baud_precondition(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path_factory: pytest.TempPathFactory,
    min_outcomes: int,
    downgrade_threshold: int,
    history: CalibrationHistory,
) -> None:
    """The observed fire_fraction (single-cycle) matches the literal
    BAUD precondition evaluated directly on the history."""
    mcap_path = tmp_path_factory.mktemp("fpb_match") / "synth.mcap"
    _materialise_single_cycle(
        fixed_raw_assessment, history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )
    report = verify_fpb(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    # Direct evaluation of the precondition.
    beyond_3_or_worse = (
        history.count_beyond_3_std + history.count_beyond_5_std
    )
    expected_fires = (
        history.outcomes_considered >= min_outcomes
        and beyond_3_or_worse >= downgrade_threshold
    )
    assert report.fire_fraction == (1.0 if expected_fires else 0.0)


# ---------------------------------------------------------------------------
# Adversarial scenarios
# ---------------------------------------------------------------------------


def test_adversarial_strict_zero_bound_fails_on_any_fire(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """``max_fire_fraction=0.0`` only holds if BAUD never fires."""
    # History that triggers BAUD precondition.
    history = CalibrationHistory(
        outcomes_considered=10,
        count_within_1_std=0, count_beyond_1_std=0,
        count_beyond_3_std=0, count_beyond_5_std=10,
        worst_position_mahalanobis=42.0,
        worst_orientation_mahalanobis=12.0,
        most_recent_observed_stamp_sim_ns=_T0_NS,
    )
    mcap_path = tmp_path / "fire.mcap"
    _materialise_single_cycle(
        fixed_raw_assessment, history,
        min_outcomes=4, downgrade_threshold=2,
        mcap_path=mcap_path,
    )
    report = verify_fpb(mcap_path, max_fire_fraction=0.0)
    assert not report.holds
    assert report.fire_fraction == 1.0
    assert len(report.violations) == 1


def test_adversarial_empty_mcap_returns_zero_fraction(
    fixed_raw_assessment: BeliefSelfAssessment,
    tmp_path: Path,
) -> None:
    """If the MCAP has no calibrated records, fire_fraction = 0.0."""
    mcap_path = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap_path) as sink:
        # Open the sink but publish nothing — empty MCAP.
        _ = sink
    report = verify_fpb(mcap_path)
    assert report.holds  # 0.0 <= 1.0
    assert report.fire_fraction == 0.0
    assert report.cycles_total == 0
    assert report.first_precondition_cycle_stamp_sim_ns is None
