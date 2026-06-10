"""Hypothesis property test for ADR-0031 (BAUD-v1).

This is the canonical evidence the ADR's roadmap §3.1 demands: for many
synthetic ``(M, K, CalibrationHistory)`` triples, materialise the
single-cycle MCAP produced by the reference policy pair and verify that
``verify_baud`` returns ``holds = True``.

Test design:

- BAUD-v1 is a *per-cycle* property — each cycle is independent of the
  others. A one-cycle MCAP per Hypothesis example is therefore the
  minimal witness shape. Many more examples per second than a multi-
  cycle generator, broader coverage of the precondition boundary.
- The raw ``BeliefSelfAssessment`` is held fixed at KNOWN (the
  "worst case" for the property: the precondition's job is precisely
  to demote KNOWN → not-KNOWN, so testing against a KNOWN raw exercises
  the downgrade arm of the policy on every fired precondition).
- The full policy chain is exercised: ``MahalanobisDowngradePolicy``
  → ``UncertaintyAwareReferencePolicy`` → ``AttitudeHoldReferencePolicy``,
  identical wiring to the smoke (ADR-0027). Whatever the reference
  pipeline emits is what the verifier sees.
- The verifier reads exactly the channels written here
  (``/self_assessment/calibrated`` and ``/actuations``) — no other
  channel is required for BAUD-v1.
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
from project_ghost.properties import verify_baud
from project_ghost.telemetry import (
    ActuationToTelemetryAdapter,
    CalibratedSelfAssessmentToTelemetryAdapter,
    MCAPFileSink,
)

if TYPE_CHECKING:
    from pathlib import Path

    from project_ghost.properties import BAUDVerificationReport
    from project_ghost.state.messages import FlightStatus, MissionStatus

# ---------------------------------------------------------------------------
# Fixed pipeline scaffolding — not Hypothesis-varied
# ---------------------------------------------------------------------------

_T0_NS = 1_000_000_000
_COVARIANCE_DIAG = 1e-4


@pytest.fixture(scope="module")
def fixed_raw_assessment() -> tuple[BeliefSelfAssessment, FlightStatus, MissionStatus]:
    """Build the canonical KNOWN raw self-assessment used by every
    property-test example.

    Uses the same fusion scaffolding as the reference smoke (ADR-0028
    ``LinearMotionOracleFusionPolicy`` + ADR-0020 ``assess_belief``)
    so the produced ``BeliefSelfAssessment`` is bit-identical to what
    the production pipeline emits. The ``flight_status`` and
    ``mission_status`` are extracted from the same ``VehicleState`` to
    feed back into ``DecisionContext`` per ADR-0021.
    """
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_DIAG,
    )
    fusion_result = oracle.fuse(
        FusionInput(
            sensor_samples=(),
            prior_belief_stamp_sim_ns=None,
            target_stamp_sim_ns=_T0_NS,
        )
    )
    state = fusion_result.belief
    thresholds = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    raw = assess_belief(state, thresholds)
    assert raw.overall_level is SelfAssessmentLevel.KNOWN, (
        "fixture invariant: small covariance must yield KNOWN raw "
        "assessment; the property test depends on this baseline"
    )
    return raw, state.flight, state.mission


# ---------------------------------------------------------------------------
# Calibration history strategy
# ---------------------------------------------------------------------------

# Bounded so individual examples remain fast; the boundary cases that
# matter (precondition just-met / just-missed) all live well below these
# limits.
_MAX_COUNT_PER_BAND = 20
_MAX_MAHALANOBIS = 50.0


@st.composite
def _calibration_histories(draw: st.DrawFn) -> CalibrationHistory:
    """Generate any ``CalibrationHistory`` that satisfies the
    dataclass's ``__post_init__`` invariants (ADR-0026).

    The invariants partition into two cases:

    - ``outcomes_considered == 0``: worsts must be ``0.0`` and the
      stamp must be ``None``.
    - ``outcomes_considered > 0``: the per-band counts must sum to it,
      worsts are non-negative non-NaN floats, and the stamp is
      ``>= 0``.

    The strategy draws the four band counts independently and derives
    ``outcomes_considered`` from their sum, which is the only legal
    way to construct the dataclass.
    """
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
# Helpers — build a single-cycle MCAP for one Hypothesis example
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
    """Run one cycle through the reference policy chain and write the
    two channels BAUD-v1 needs to ``mcap_path``.

    The decision channel is *not* written: ``verify_baud`` reads only
    ``/self_assessment/calibrated`` (for the precondition) and
    ``/actuations`` (which carries the decision inline per ADR-0023).
    """
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
def test_baud_v1_holds_for_synthetic_single_cycle_runs(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path_factory: pytest.TempPathFactory,
    min_outcomes: int,
    downgrade_threshold: int,
    history: CalibrationHistory,
) -> None:
    """Canonical BAUD-v1 property test.

    For any legal ``(min_outcomes, downgrade_threshold,
    CalibrationHistory)``, the single-cycle MCAP produced by the
    reference policy pair must pass ``verify_baud``.

    If this test ever finds a falsifying example Hypothesis will
    minimise it to a tiny ``CalibrationHistory`` + the offending
    parameters — that minimised triple is the bug report.
    """
    raw, flight, mission = fixed_raw_assessment

    mcap_path = tmp_path_factory.mktemp("baud_property") / "synthetic.mcap"
    _run_single_cycle(
        raw,
        flight,
        mission,
        history,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        mcap_path=mcap_path,
    )

    report = verify_baud(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )
    assert report.holds, (
        f"BAUD-v1 violated by synthetic run.\n"
        f"  params: M={min_outcomes}, K={downgrade_threshold}\n"
        f"  history: outcomes_considered={history.outcomes_considered}, "
        f"counts=({history.count_within_1_std}, "
        f"{history.count_beyond_1_std}, "
        f"{history.count_beyond_3_std}, "
        f"{history.count_beyond_5_std})\n"
        f"  violations: {report.violations}"
    )


# ---------------------------------------------------------------------------
# Adversarial scenarios — fixed, named edge cases
# ---------------------------------------------------------------------------


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
    """Compact constructor for adversarial-case histories."""
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
) -> BAUDVerificationReport:
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
    return verify_baud(
        mcap_path,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
    )


def test_adversarial_outcome_storm_holds(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """All outcomes BEYOND_5_STD, enough to fire the precondition. The
    property must fire and hold.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(b5=10, worst_pos=42.0, worst_ori=12.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1


def test_adversarial_border_just_below_threshold_holds(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """K=2 with only one beyond_3 outcome — precondition does NOT fire.
    BAUD-v1 is trivially held (no cycles to evaluate).
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(within=10, b3=1, worst_pos=3.5, worst_ori=0.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0


def test_adversarial_border_exactly_at_threshold_holds(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """K=2 with exactly 2 beyond_3 outcomes — precondition fires. The
    boundary case that the calibration policy must downgrade on.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(within=10, b3=2, worst_pos=4.0, worst_ori=0.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 1


def test_adversarial_interleaved_sigma_bands_only_3_and_5_count(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """Many beyond_1 outcomes but zero beyond_3/5 — precondition must
    NOT fire because beyond_1 doesn't count toward the threshold. This
    is the spec literal of MahalanobisDowngradePolicy.
    """
    raw, flight, mission = fixed_raw_assessment
    history = _history(b1=15, within=5, worst_pos=2.5, worst_ori=1.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0


def test_adversarial_below_min_outcomes_holds(
    fixed_raw_assessment: tuple[BeliefSelfAssessment, FlightStatus, MissionStatus],
    tmp_path: Path,
) -> None:
    """K threshold met but ``outcomes_considered < M`` — precondition
    must NOT fire because BAUD respects the sample-size guard.
    """
    raw, flight, mission = fixed_raw_assessment
    # M=4 default; only 3 outcomes total, even though both are beyond_5
    history = _history(b5=3, worst_pos=42.0, worst_ori=0.0)
    report = _verify_one(raw, flight, mission, history, tmp_path)
    assert report.holds
    assert report.cycles_precondition_held == 0
