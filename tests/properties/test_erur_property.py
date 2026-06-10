"""Hypothesis property test for ADR-0032 (ERUR-v1).

Symmetric counterpart of :mod:`tests.properties.test_baud_property`.

For many synthetic ``(M, K, CalibrationHistory)`` triples plus a fixed
KNOWN raw assessment, materialise the single-cycle MCAP produced by
the reference policy pair and verify that ``verify_erur`` returns
``holds = True``.

Test design notes:

- ERUR's precondition requires BOTH ``drift_clean`` (negation of BAUD)
  AND ``raw.overall_level == KNOWN``. Many Hypothesis examples will
  fall outside the precondition (e.g. when the generated history
  satisfies BAUD's condition instead); those examples are trivially
  satisfied by ``verify_erur`` (``cycles_precondition_held == 0`` ⇒
  no postcondition checks). The property still has work to do on the
  ~half of examples where precondition fires.
- The fixed raw assessment is the same KNOWN one used by the BAUD
  property test — both files share the fixture pattern.
- Adversarial cases nail the boundaries that the partition between
  BAUD and ERUR runs through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from project_ghost.core.actuation import AttitudeHoldReferencePolicy
from project_ghost.core.decisions import (
    DecisionContext,
    UncertaintyAwareReferencePolicy,
    decide_with_rationale,
)
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
from project_ghost.properties import verify_erur
from project_ghost.telemetry import (
    ActuationToTelemetryAdapter,
    CalibratedSelfAssessmentToTelemetryAdapter,
    MCAPFileSink,
)

if TYPE_CHECKING:
    from pathlib import Path

    from project_ghost.properties import ERURVerificationReport
    from project_ghost.state.messages import FlightStatus, MissionStatus


# ---------------------------------------------------------------------------
# Fixed pipeline scaffolding
# ---------------------------------------------------------------------------

_T0_NS = 1_000_000_000
_COVARIANCE_DIAG = 1e-4


@pytest.fixture(scope="module")
def fixed_raw_assessment() -> tuple[BeliefSelfAssessment, FlightStatus, MissionStatus]:
    """Canonical KNOWN raw self-assessment. Same construction as the
    BAUD property test — see that fixture for the rationale."""
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_DIAG,
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
    assert raw.overall_level is SelfAssessmentLevel.KNOWN
    return raw, state.flight, state.mission


# ---------------------------------------------------------------------------
# Calibration history strategy (reused shape from BAUD property test)
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


def _run_single_cycle(
    raw: BeliefSelfAssessment,
    flight: FlightStatus,
    mission: MissionStatus,
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
    decision_policy = UncertaintyAwareReferencePolicy()
    actuation_policy = AttitudeHoldReferencePolicy()

    calibrated = feedback.adjust(raw, history)

    ctx = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=flight,
        mission_status=mission,
        perception_mode=None,
        calibrated_self_assessment=calibrated,
    )
    decision, _rationale = decide_with_rationale(decision_policy, ctx)
    directive = actuation_policy.actuate(decision)

    with MCAPFileSink(mcap_path) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(calibrated)
        ActuationToTelemetryAdapter(sink).publish(directive)


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


def _verify_one(
    raw: BeliefSelfAssessment,
    flight: FlightStatus,
    mission: MissionStatus,
    history: CalibrationHistory,
    tmp_path: Path,
    *,
    min_outcomes: int = 4,
    downgrade_threshold: int = 2,
) -> ERURVerificationReport:
    mcap_path = tmp_path / "scenario.mcap"
    _run_single_cycle(
        raw,
        flight,
        mission,
        history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )
    return verify_erur(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


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
def test_erur_v1_holds_for_synthetic_single_cycle_runs(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path_factory: pytest.TempPathFactory,
    min_outcomes: int,
    downgrade_threshold: int,
    history: CalibrationHistory,
) -> None:
    """Canonical ERUR-v1 property test — single-cycle MCAP per example."""
    raw, flight, mission = fixed_raw_assessment

    mcap_path = tmp_path_factory.mktemp("erur_property") / "synthetic.mcap"
    _run_single_cycle(
        raw,
        flight,
        mission,
        history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )

    report = verify_erur(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    assert report.holds, (
        f"ERUR-v1 violated by synthetic run.\n"
        f"  params: M={min_outcomes}, K={downgrade_threshold}\n"
        f"  history: outcomes_considered={history.outcomes_considered}, "
        f"counts=({history.count_within_1_std}, "
        f"{history.count_beyond_1_std}, "
        f"{history.count_beyond_3_std}, "
        f"{history.count_beyond_5_std})\n"
        f"  violations: {report.violations}"
    )


# ---------------------------------------------------------------------------
# Adversarial scenarios
# ---------------------------------------------------------------------------


def test_adversarial_empty_history_fires_erur(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """No outcomes yet (cold start). Drift is trivially clean (both
    disjuncts true). raw is KNOWN. ERUR must fire and hold.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history()  # outcomes_considered = 0
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1


def test_adversarial_within_m_guard_fires_erur(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """``count_beyond_3+5 >= K`` but ``outcomes_considered < M`` — the
    semantic gap that the corrected precondition fixes. Calibrator
    passes through (no downgrade), so ERUR must fire.
    """
    raw, flight, mission = fixed_raw_assessment
    # M=4 default; only 3 outcomes total, all beyond_5 (K=2 reached
    # but sample too small to act on).
    history = _history(b5=3, worst_pos=42.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1


def test_adversarial_below_k_threshold_fires_erur(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """``outcomes_considered >= M`` but ``count_beyond_3+5 < K`` —
    classical drift-clean. ERUR must fire.
    """
    raw, flight, mission = fixed_raw_assessment
    # M=4 default; 6 within_1 outcomes, no beyond_3/5.
    history = _history(within=6, worst_pos=0.5, worst_ori=0.2)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1


def test_adversarial_drift_storm_does_not_fire_erur(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """``outcomes_considered >= M`` AND ``count_beyond_3+5 >= K`` —
    calibrator downgrades. ERUR's precondition does NOT fire; BAUD's
    territory. Report holds trivially.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(b5=10, worst_pos=42.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0


def test_adversarial_interleaved_only_3_and_5_count_against_k(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """Many beyond_1 outcomes count against neither the K threshold
    nor the M guard's effective denominator (they DO count toward
    ``outcomes_considered``, but the beyond_1 band is irrelevant to
    the downgrade condition). Drift-clean. ERUR fires.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(b1=15, within=5, worst_pos=2.5, worst_ori=1.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1
