"""Violation matrix smokes — systematic demonstration that the property
verifier detects six distinct bug categories, not just one (paper §8.2
extension; contribution C3).

The single-bug ``closed_loop_smoke_violated.py`` proves the verifier
can detect *a* bug. This module extends that to a **taxonomy of
six bug categories**, one mini-smoke per category, each engineered to
break exactly one property. The matrix demonstrates that detection
capacity is systematic, not anecdotal.

Categories and detection map:

  ============================  =========================  ==================
  Category                      Buggy component            Property violated
  ============================  =========================  ==================
  calibrator_no_downgrade       calibration policy         BAUD-v1
  calibrator_invents_confidence calibration policy         MD-v1
  decision_proceeds_anyway      decision policy            BAUD-v1
  decision_never_proceeds       decision policy            ERUR-v1
  actuation_non_safe_reason     actuation policy           BAUD-v1
  fpb_threshold_exceeded        verifier param (max_ff)    FPB-v1
  ============================  =========================  ==================

All six smokes share the same drift scenario as the reference smoke
(linear motion oracle, sustained drift, M=4 K=2 W=32). Only the named
component is replaced by a deliberately broken variant. Every other
choice is held constant so the matrix is comparable.

The buggy variants are all named with prefix ``_Buggy`` and ID prefix
``buggy_`` so that any reader of the resulting MCAP sees the offending
component explicitly in the ``policy_id`` / ``reason`` fields.

Run directly to produce all six MCAPs and a markdown summary table:

    $ python -m project_ghost.examples.violation_matrix

Exit code is 1 iff any category fails to be detected (i.e., if the
matrix has a false negative). On a correctly functioning verifier
every category should produce the expected violation.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

import numpy as np

from project_ghost.core.actuation import (
    AttitudeHoldReferencePolicy,
    actuate_and_publish,
)
from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.decisions import (
    DecisionContext,
    UncertaintyAwareReferencePolicy,
    decide_with_rationale,
)
from project_ghost.core.decisions.types import Decision, DecisionKind
from project_ghost.core.feedback import (
    MahalanobisDowngradePolicy,
    assess_with_feedback,
)
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.fusion import (
    FusionInput,
    LinearMotionOracleFusionPolicy,
    fuse_and_publish,
)
from project_ghost.core.prediction import (
    ConstantVelocityForwardPredictor,
    compute_divergence,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    SelfAssessmentLevel,
    assess_belief,
)
from project_ghost.hal.messages.actuators import AttitudeCommand
from project_ghost.properties import (
    BAUDVerificationReport,
    ERURVerificationReport,
    FPBVerificationReport,
    MDVerificationReport,
    RLBVerificationReport,
    verify_baud,
    verify_erur,
    verify_fpb,
    verify_md,
    verify_rlb,
)
from project_ghost.state.messages import Pose
from project_ghost.telemetry import (
    ActuationToTelemetryAdapter,
    CalibratedSelfAssessmentToTelemetryAdapter,
    DecisionToTelemetryAdapter,
    ForwardPredictionToTelemetryAdapter,
    FusionResultToTelemetryAdapter,
    MCAPFileSink,
    PredictionOutcomeToTelemetryAdapter,
    SelfAssessmentToTelemetryAdapter,
)
from project_ghost.telemetry.channels import CHANNEL_STATE_NAV

if TYPE_CHECKING:
    from project_ghost.core.feedback.types import CalibrationHistory
    from project_ghost.core.prediction import (
        BeliefForwardPrediction,
        PredictionOutcome,
    )
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )
    from project_ghost.state.messages import VehicleState
    from project_ghost.telemetry import TelemetrySink


_DT_NS: Final[int] = 100_000_000
_T0_NS: Final[int] = 1_000_000_000
_GROUND_TRUTH_DRIFT_X_MPS: Final[float] = 5.0
_COVARIANCE_DIAG: Final[float] = 1e-4
_FEEDBACK_MIN_OUTCOMES: Final[int] = 4
_FEEDBACK_DOWNGRADE_THRESHOLD: Final[int] = 2
_FEEDBACK_MAX_HISTORY: Final[int] = 32
_N_CYCLES: Final[int] = 10


# ---------------------------------------------------------------------------
# Buggy components — each named explicitly so MCAP readers can see the bug
# ---------------------------------------------------------------------------


class _BuggyPassthroughCalibrator:
    """C1: never downgrades. Violates BAUD-v1 (adjusted stays KNOWN
    during drift; decision stays PROCEED).
    """

    POLICY_ID_BASE: ClassVar[str] = "buggy_passthrough_calibrator_v1"

    def __init__(self) -> None:
        self._policy_id: str = self.POLICY_ID_BASE

    @property
    def policy_id(self) -> str:
        return self._policy_id

    def adjust(
        self,
        raw: BeliefSelfAssessment,
        history: CalibrationHistory,
    ) -> CalibratedSelfAssessment:
        reason = "no_outcomes_yet" if history.outcomes_considered == 0 else "buggy_no_downgrade"
        return CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id=self._policy_id,
            adjustment_reason=reason,
        )


class _BuggyConfidenceInventerCalibrator:
    """C2: inflates confidence (returns KNOWN regardless of raw level).
    Violates MD-v1 the moment raw assessment drops below KNOWN — in this
    smoke the raw is always KNOWN by construction (small covariance), so
    this calibrator alone does not break MD-v1; to expose the bug we
    also feed it a fabricated raw level via a wrapping step in the
    smoke driver below.
    """

    POLICY_ID_BASE: ClassVar[str] = "buggy_confidence_inventer_calibrator_v1"

    def __init__(self) -> None:
        self._policy_id: str = self.POLICY_ID_BASE

    @property
    def policy_id(self) -> str:
        return self._policy_id

    def adjust(
        self,
        raw: BeliefSelfAssessment,
        history: CalibrationHistory,
    ) -> CalibratedSelfAssessment:
        # Always returns KNOWN regardless of raw. When the driver feeds
        # a raw with overall_level != KNOWN the result violates MD-v1
        # (``adjusted`` strictly more confident than ``raw``).
        return CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=SelfAssessmentLevel.KNOWN,
            adjustment_policy_id=self._policy_id,
            adjustment_reason="buggy_invented_known",
        )


class _BuggyProceedOnlyDecisionPolicy:
    """C3: always emits PROCEED regardless of calibrated level.
    Violates BAUD-v1 the same way the no-downgrade calibrator does, but
    isolates the bug on the decision layer.
    """

    POLICY_ID: ClassVar[str] = "buggy_proceed_only_decision_v1"

    @property
    def policy_id(self) -> str:
        return self.POLICY_ID

    def decide(self, context: DecisionContext) -> Decision:
        return Decision(
            decision_stamp_sim_ns=context.belief_stamp_sim_ns,
            kind=DecisionKind.PROCEED,
            reason="buggy_proceed_always",
        )


class _BuggyHoldOnlyDecisionPolicy:
    """C4: always emits HOLD regardless of calibrated level. Violates
    ERUR-v1 on cycles where drift is absent and raw is KNOWN (the
    policy never emits PROCEED).
    """

    POLICY_ID: ClassVar[str] = "buggy_hold_only_decision_v1"

    @property
    def policy_id(self) -> str:
        return self.POLICY_ID

    def decide(self, context: DecisionContext) -> Decision:
        return Decision(
            decision_stamp_sim_ns=context.belief_stamp_sim_ns,
            kind=DecisionKind.HOLD,
            reason="buggy_hold_always",
        )


class _BuggyNonSafeReasonActuationPolicy:
    """C5: emits ``HOLD`` decisions as ``AttitudeCommand`` (a
    non-conservative actuator command) with a reason
    ``buggy_dangerous_command_during_hold`` that is NOT in the
    BAUD-v1 safe-reason set S_BAUD = {attitude_hold_hold,
    kill_zero_throttle}. Violates BAUD-v1 postcondition 3.
    """

    POLICY_ID: ClassVar[str] = "buggy_non_safe_reason_actuator_v1"

    @property
    def policy_id(self) -> str:
        return self.POLICY_ID

    def actuate(self, decision: Decision) -> ActuationDirective:
        command = AttitudeCommand(
            q_target=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
            thrust_normalized=0.5,
        )
        return ActuationDirective(
            decision=decision,
            actuator_command=command,
            directive_stamp_sim_ns=decision.decision_stamp_sim_ns,
            policy_id=self.POLICY_ID,
            reason="buggy_dangerous_command_during_hold",
        )


# ---------------------------------------------------------------------------
# Categories enumerated
# ---------------------------------------------------------------------------


class BugCategory(StrEnum):
    CALIBRATOR_NO_DOWNGRADE = "calibrator_no_downgrade"
    CALIBRATOR_INVENTS_CONFIDENCE = "calibrator_invents_confidence"
    DECISION_PROCEEDS_ANYWAY = "decision_proceeds_anyway"
    DECISION_NEVER_PROCEEDS = "decision_never_proceeds"
    ACTUATION_NON_SAFE_REASON = "actuation_non_safe_reason"
    FPB_THRESHOLD_EXCEEDED = "fpb_threshold_exceeded"


@dataclass(frozen=True)
class MatrixCellResult:
    """One row of the violation matrix."""

    category: BugCategory
    expected_violator: str  # the property that *should* report VIOLATED
    mcap_path: Path
    mcap_sha256: str
    baud_holds: bool
    erur_holds: bool
    md_holds: bool
    rlb_holds: bool
    fpb_holds: bool
    bug_detected: bool  # the expected property actually reported VIOLATED


# ---------------------------------------------------------------------------
# Internal shared helpers
# ---------------------------------------------------------------------------


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _ground_truth_pose(t_ns: int) -> Pose:
    dt_s = (t_ns - _T0_NS) / 1e9
    return Pose(
        position_enu_m=np.array(
            [_GROUND_TRUTH_DRIFT_X_MPS * dt_s, 0.0, 0.0],
            dtype=np.float64,
        ),
        orientation_q=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
    )


def _publish_state(sink: TelemetrySink, state: VehicleState) -> None:
    sink.publish(CHANNEL_STATE_NAV, state.stamp_sim_ns, state)


def _run_smoke_with_components(
    output_path: Path,
    *,
    feedback_policy: Any,
    decision_policy: Any,
    actuation_policy: Any,
    fake_uncertain_raw: bool = False,
) -> None:
    """Run the standard 8-step smoke with the components passed in.

    ``fake_uncertain_raw``: when True, the raw self-assessment is forced
    to ``UNCERTAIN`` before being passed to the calibrator. Used by
    category C2 to expose the confidence-inventer bug; the calibrator
    then returns KNOWN, which violates MD-v1.
    """
    thresholds = _make_thresholds()
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_DIAG,
    )
    predictor = ConstantVelocityForwardPredictor()

    predictions: list[BeliefForwardPrediction] = []
    outcomes: list[PredictionOutcome] = []

    with MCAPFileSink(output_path) as sink:
        f_adp = FusionResultToTelemetryAdapter(sink)
        sa_adp = SelfAssessmentToTelemetryAdapter(sink)
        cal_adp = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        d_adp = DecisionToTelemetryAdapter(sink)
        a_adp = ActuationToTelemetryAdapter(sink)
        o_adp = PredictionOutcomeToTelemetryAdapter(sink)
        p_adp = ForwardPredictionToTelemetryAdapter(sink)

        for k in range(_N_CYCLES):
            t_k = _T0_NS + k * _DT_NS

            if k > 0:
                outcome = compute_divergence(predictions[k - 1], _ground_truth_pose(t_k), t_k)
                outcomes.append(outcome)
                o_adp.publish(outcome)

            prior_stamp = _T0_NS + (k - 1) * _DT_NS if k > 0 else None
            fusion_input = FusionInput(
                sensor_samples=(),
                prior_belief_stamp_sim_ns=prior_stamp,
                target_stamp_sim_ns=t_k,
            )
            fusion_result = fuse_and_publish(oracle, fusion_input, f_adp)
            state = fusion_result.belief
            _publish_state(sink, state)

            raw = assess_belief(state, thresholds)
            if fake_uncertain_raw:
                # Force raw level to UNCERTAIN so the inventer calibrator
                # (which always returns KNOWN) violates MD-v1 visibly.
                raw = replace_raw_level(raw, SelfAssessmentLevel.UNCERTAIN)
            sa_adp.publish(raw)

            calibrated = assess_with_feedback(
                raw, outcomes, feedback_policy, max_history=_FEEDBACK_MAX_HISTORY
            )
            cal_adp.publish(calibrated)

            ctx = DecisionContext(
                belief_stamp_sim_ns=state.stamp_sim_ns,
                self_assessment=raw,
                flight_status=state.flight,
                mission_status=state.mission,
                perception_mode=None,
                calibrated_self_assessment=calibrated,
            )

            # Decision: every buggy policy implements the same
            # structural Policy protocol as the reference, so the
            # orchestration helper handles both uniformly.
            decision, rationale = decide_with_rationale(decision_policy, ctx)
            d_adp.publish(decision, rationale)

            # Actuation: reference and buggy actuators share the actuate(decision)
            # interface; the orchestration helper handles both.
            actuate_and_publish(actuation_policy, decision, a_adp)

            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            p_adp.publish(prediction)
            predictions.append(prediction)


def replace_raw_level(
    raw: BeliefSelfAssessment, new_level: SelfAssessmentLevel
) -> BeliefSelfAssessment:
    """Return a copy of ``raw`` with ``overall_level`` swapped.

    Used by category C2 only; production code never tampers with raw
    assessments downstream of the assessor.
    """
    return replace(raw, overall_level=new_level)


# ---------------------------------------------------------------------------
# Per-category runners
# ---------------------------------------------------------------------------


def _verify_all(
    mcap_path: Path,
) -> tuple[
    BAUDVerificationReport,
    ERURVerificationReport,
    MDVerificationReport,
    RLBVerificationReport,
    FPBVerificationReport,
]:
    return (
        verify_baud(
            mcap_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
        verify_erur(
            mcap_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
        verify_md(mcap_path),
        verify_rlb(mcap_path, max_history=_FEEDBACK_MAX_HISTORY),
        verify_fpb(
            mcap_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
    )


def _run_category(category: BugCategory, out_dir: Path) -> MatrixCellResult:
    out = (out_dir / f"violation_{category.value}.mcap").resolve()

    if category is BugCategory.CALIBRATOR_NO_DOWNGRADE:
        _run_smoke_with_components(
            out,
            feedback_policy=_BuggyPassthroughCalibrator(),
            decision_policy=UncertaintyAwareReferencePolicy(),
            actuation_policy=AttitudeHoldReferencePolicy(),
        )
        expected = "BAUD-v1"
    elif category is BugCategory.CALIBRATOR_INVENTS_CONFIDENCE:
        _run_smoke_with_components(
            out,
            feedback_policy=_BuggyConfidenceInventerCalibrator(),
            decision_policy=UncertaintyAwareReferencePolicy(),
            actuation_policy=AttitudeHoldReferencePolicy(),
            fake_uncertain_raw=True,
        )
        expected = "MD-v1"
    elif category is BugCategory.DECISION_PROCEEDS_ANYWAY:
        _run_smoke_with_components(
            out,
            feedback_policy=MahalanobisDowngradePolicy(
                min_outcomes=_FEEDBACK_MIN_OUTCOMES,
                downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            ),
            decision_policy=_BuggyProceedOnlyDecisionPolicy(),
            actuation_policy=AttitudeHoldReferencePolicy(),
        )
        expected = "BAUD-v1"
    elif category is BugCategory.DECISION_NEVER_PROCEEDS:
        _run_smoke_with_components(
            out,
            feedback_policy=MahalanobisDowngradePolicy(
                min_outcomes=_FEEDBACK_MIN_OUTCOMES,
                downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            ),
            decision_policy=_BuggyHoldOnlyDecisionPolicy(),
            actuation_policy=AttitudeHoldReferencePolicy(),
        )
        expected = "ERUR-v1"
    elif category is BugCategory.ACTUATION_NON_SAFE_REASON:
        _run_smoke_with_components(
            out,
            feedback_policy=MahalanobisDowngradePolicy(
                min_outcomes=_FEEDBACK_MIN_OUTCOMES,
                downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            ),
            decision_policy=UncertaintyAwareReferencePolicy(),
            actuation_policy=_BuggyNonSafeReasonActuationPolicy(),
        )
        expected = "BAUD-v1"
    elif category is BugCategory.FPB_THRESHOLD_EXCEEDED:
        # Reference policies, but verify with a tight threshold the
        # sustained-drift smoke is guaranteed to exceed.
        _run_smoke_with_components(
            out,
            feedback_policy=MahalanobisDowngradePolicy(
                min_outcomes=_FEEDBACK_MIN_OUTCOMES,
                downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            ),
            decision_policy=UncertaintyAwareReferencePolicy(),
            actuation_policy=AttitudeHoldReferencePolicy(),
        )
        expected = "FPB-v1"
    else:
        raise ValueError(f"unhandled category: {category}")

    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    baud, erur, md, rlb, _fpb_default = _verify_all(out)

    # For FPB category, verify with a tight threshold; for others, use
    # the default observational threshold.
    if category is BugCategory.FPB_THRESHOLD_EXCEEDED:
        fpb = verify_fpb(
            out,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            max_fire_fraction=0.1,
        )
    else:
        fpb = _fpb_default

    holds_by_id = {
        "BAUD-v1": baud.holds,
        "ERUR-v1": erur.holds,
        "MD-v1": md.holds,
        "RLB-v1": rlb.holds,
        "FPB-v1": fpb.holds,
    }
    bug_detected = not holds_by_id[expected]

    return MatrixCellResult(
        category=category,
        expected_violator=expected,
        mcap_path=out,
        mcap_sha256=sha,
        baud_holds=baud.holds,
        erur_holds=erur.holds,
        md_holds=md.holds,
        rlb_holds=rlb.holds,
        fpb_holds=fpb.holds,
        bug_detected=bug_detected,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_violation_matrix(out_dir: Path) -> list[MatrixCellResult]:
    """Run all six categories and return the matrix rows.

    Side effect: writes one MCAP per category to ``out_dir``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    return [_run_category(cat, out_dir) for cat in BugCategory]


def _format_matrix_markdown(results: list[MatrixCellResult]) -> str:
    rows = ["| Category | Expected | BAUD | ERUR | MD | RLB | FPB | Detected |"]
    rows.append("|---|---|:---:|:---:|:---:|:---:|:---:|:---:|")
    for r in results:
        rows.append(
            f"| `{r.category.value}` | **{r.expected_violator}** | "
            f"{'OK' if r.baud_holds else 'VIOL'} | "
            f"{'OK' if r.erur_holds else 'VIOL'} | "
            f"{'OK' if r.md_holds else 'VIOL'} | "
            f"{'OK' if r.rlb_holds else 'VIOL'} | "
            f"{'OK' if r.fpb_holds else 'VIOL'} | "
            f"{'YES' if r.bug_detected else 'NO'} |"
        )
    return "\n".join(rows)


def main() -> None:
    """CLI entry: run all six categories, print the matrix, exit 1 if
    any bug fails to be detected (false negative).
    """
    out_dir = Path("violation_matrix_out").resolve()
    results = run_violation_matrix(out_dir)
    print(_format_matrix_markdown(results))
    print()
    if all(r.bug_detected for r in results):
        print(f"All {len(results)} bug categories correctly detected.")
        sys.exit(0)
    else:
        missed = [r.category.value for r in results if not r.bug_detected]
        print(f"FALSE NEGATIVE on categories: {missed}")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["BugCategory", "MatrixCellResult", "run_violation_matrix"]
