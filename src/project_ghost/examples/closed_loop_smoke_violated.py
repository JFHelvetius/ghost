"""Violation showcase smoke: demonstrates that the property verifiers
*detect bugs*, not just rubber-stamp green runs (paper §8.2, contribution C3).

This module is the deliberate anti-pattern companion to
``closed_loop_smoke.py``: same pipeline shape, but with a calibration
policy that is **provably buggy by design**. The bug — a passthrough
that never downgrades regardless of evidence — causes the agent to
keep emitting ``PROCEED`` decisions while ground truth diverges.

Expected outcome:

- ``BAUD-v1: VIOLATED`` — during sustained drift, the precondition
  fires (M outcomes observed, K dirty), but the postcondition (no
  PROCEED, no non-conservative action) is violated because the buggy
  calibrator never downgrades the KNOWN level to UNCERTAIN.
- The CLI ``ghost verify-properties --mcap`` returns exit code 1 on
  this MCAP.
- The JSON output's ``all_properties_hold`` field is ``false``, and
  the ``BAUD-v1.violations`` array contains one entry per offending
  cycle with the cycle index, the raw level, the adjusted level, the
  decision kind, and the actuator reason that broke the property.

This is the artifact paper §8.2 cites to demonstrate **C3's
detection capacity** (the reproducibility primitive), which the
reference smoke cannot demonstrate alone (it always reports HOLDS by
construction).

Run it directly:

    $ python -m project_ghost.examples.closed_loop_smoke_violated
    $ ghost verify-properties --mcap closed_loop_smoke_violated.mcap
    $ echo $?  # 1

The buggy policy is contained in this module and never re-exported as
part of the public API. The reference smoke remains untouched.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np

from project_ghost.core.actuation import (
    AttitudeHoldReferencePolicy,
    actuate_and_publish,
)
from project_ghost.core.decisions import (
    DecisionContext,
    UncertaintyAwareReferencePolicy,
    decide_with_rationale,
)
from project_ghost.core.feedback import (
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
    assess_belief,
)
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

    _PredictionType = BeliefForwardPrediction
    _OutcomeType = PredictionOutcome
    _CalibratedType = CalibratedSelfAssessment


# Same scenario parameters as the reference smoke — only the policy
# differs. Keeping the rest identical ensures the BAUD precondition
# fires on the same cycles, making the violation directly comparable
# to the HOLDS baseline.
_DT_NS: Final[int] = 100_000_000
_T0_NS: Final[int] = 1_000_000_000
_GROUND_TRUTH_DRIFT_X_MPS: Final[float] = 5.0
_COVARIANCE_DIAG: Final[float] = 1e-4
_MIN_CYCLES: Final[int] = 2
_FEEDBACK_MIN_OUTCOMES: Final[int] = 4
_FEEDBACK_DOWNGRADE_THRESHOLD: Final[int] = 2
_FEEDBACK_MAX_HISTORY: Final[int] = 32


class _BuggyPassthroughCalibrator:
    """Deliberately broken calibration policy used by the violation
    showcase. Always returns ``adjusted = raw``, regardless of how many
    dirty outcomes accumulated.

    This violates the reference calibrator's purpose (downgrading on
    sustained drift) and causes ``BAUD-v1`` to report ``VIOLATED`` on
    the resulting MCAP. ``MD-v1`` still ``HOLDS`` (passthrough never
    inflates confidence — adjusted equals raw — which is degenerate
    but not invented), highlighting that BAUD and MD detect different
    failure modes.

    Not exported. Not for operational use. Marker name prefixed with
    ``buggy_`` so any reader of the MCAP can see the offending
    ``adjustment_policy_id`` in the calibrated channel and reproduce
    the cause.
    """

    POLICY_ID_BASE: ClassVar[str] = "buggy_passthrough_for_violation_showcase_v1"

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


@dataclass(frozen=True)
class ViolationSmokeSummary:
    """Aggregate observations from the violation-showcase smoke.

    Differs from ``SmokeSummary`` only in name and in the expected
    invariants: tests assert ``baud_report.holds is False`` here.
    """

    n_cycles: int
    n_outcomes: int
    n_decisions: int
    decisions_by_kind: dict[str, int]
    calibrated_levels_observed: list[str]
    final_verdict: str | None
    mcap_path: Path
    mcap_sha256: str
    baud_report: BAUDVerificationReport
    erur_report: ERURVerificationReport
    md_report: MDVerificationReport
    rlb_report: RLBVerificationReport
    fpb_report: FPBVerificationReport

    @property
    def any_property_violated(self) -> bool:
        return not (
            self.baud_report.holds
            and self.erur_report.holds
            and self.md_report.holds
            and self.rlb_report.holds
            and self.fpb_report.holds
        )


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


def _publish_vehicle_state(sink: TelemetrySink, state: VehicleState) -> None:
    sink.publish(CHANNEL_STATE_NAV, state.stamp_sim_ns, state)


def run_violated_smoke(
    output_path: Path,
    *,
    n_cycles: int = 10,
) -> ViolationSmokeSummary:
    """Run the violation-showcase smoke and write the MCAP to ``output_path``.

    Returns ``ViolationSmokeSummary`` with the five inline property
    reports. By construction (buggy calibrator), ``baud_report.holds``
    is ``False`` whenever ``n_cycles >= 6`` (enough drift cycles to
    accumulate M=4 outcomes with K=2 dirty).
    """
    if n_cycles < _MIN_CYCLES:
        raise ValueError(
            f"n_cycles must be >= {_MIN_CYCLES} (need at least one outcome); got {n_cycles}"
        )

    thresholds = _make_thresholds()
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=np.zeros(3, dtype=np.float64),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_DIAG,
    )
    predictor = ConstantVelocityForwardPredictor()
    decision_policy = UncertaintyAwareReferencePolicy()
    actuation_policy = AttitudeHoldReferencePolicy()
    feedback_policy = _BuggyPassthroughCalibrator()

    predictions_by_cycle: list[_PredictionType] = []
    outcomes_so_far: list[_OutcomeType] = []
    calibrated_records: list[_CalibratedType] = []
    decisions_by_kind: dict[str, int] = {}

    with MCAPFileSink(output_path) as sink:
        fusion_adapter = FusionResultToTelemetryAdapter(sink)
        sa_adapter = SelfAssessmentToTelemetryAdapter(sink)
        cal_adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        dec_adapter = DecisionToTelemetryAdapter(sink)
        act_adapter = ActuationToTelemetryAdapter(sink)
        out_adapter = PredictionOutcomeToTelemetryAdapter(sink)
        pred_adapter = ForwardPredictionToTelemetryAdapter(sink)

        for k in range(n_cycles):
            t_k = _T0_NS + k * _DT_NS

            if k > 0:
                prior_prediction = predictions_by_cycle[k - 1]
                actual_pose = _ground_truth_pose(t_k)
                outcome = compute_divergence(prior_prediction, actual_pose, t_k)
                outcomes_so_far.append(outcome)
                out_adapter.publish(outcome)

            prior_stamp = _T0_NS + (k - 1) * _DT_NS if k > 0 else None
            fusion_input = FusionInput(
                sensor_samples=(),
                prior_belief_stamp_sim_ns=prior_stamp,
                target_stamp_sim_ns=t_k,
            )
            fusion_result = fuse_and_publish(oracle, fusion_input, fusion_adapter)
            state = fusion_result.belief
            _publish_vehicle_state(sink, state)

            raw_assessment = assess_belief(state, thresholds)
            sa_adapter.publish(raw_assessment)

            calibrated = assess_with_feedback(
                raw_assessment,
                outcomes_so_far,
                feedback_policy,
                max_history=_FEEDBACK_MAX_HISTORY,
            )
            calibrated_records.append(calibrated)
            cal_adapter.publish(calibrated)

            ctx = DecisionContext(
                belief_stamp_sim_ns=state.stamp_sim_ns,
                self_assessment=raw_assessment,
                flight_status=state.flight,
                mission_status=state.mission,
                perception_mode=None,
                calibrated_self_assessment=calibrated,
            )
            decision, rationale = decide_with_rationale(decision_policy, ctx)
            dec_adapter.publish(decision, rationale)
            decisions_by_kind[decision.kind.value] = (
                decisions_by_kind.get(decision.kind.value, 0) + 1
            )

            actuate_and_publish(actuation_policy, decision, act_adapter)

            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            pred_adapter.publish(prediction)
            predictions_by_cycle.append(prediction)

    final_verdict = outcomes_so_far[-1].verdict.value if outcomes_so_far else None
    calibrated_levels_observed = [c.adjusted_overall_level.value for c in calibrated_records]

    mcap_bytes = output_path.read_bytes()
    mcap_sha = hashlib.sha256(mcap_bytes).hexdigest()

    return ViolationSmokeSummary(
        n_cycles=n_cycles,
        n_outcomes=len(outcomes_so_far),
        n_decisions=n_cycles,
        decisions_by_kind=decisions_by_kind,
        calibrated_levels_observed=calibrated_levels_observed,
        final_verdict=final_verdict,
        mcap_path=output_path,
        mcap_sha256=mcap_sha,
        baud_report=verify_baud(
            output_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
        erur_report=verify_erur(
            output_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
        md_report=verify_md(output_path),
        rlb_report=verify_rlb(
            output_path,
            max_history=_FEEDBACK_MAX_HISTORY,
        ),
        fpb_report=verify_fpb(
            output_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        ),
    )


def main() -> None:
    """CLI entry: write to ``./closed_loop_smoke_violated.mcap`` and print
    the violation summary. Returns exit code 1 if any property violates,
    which is the expected behaviour for this showcase.
    """
    out = Path("closed_loop_smoke_violated.mcap").resolve()
    summary = run_violated_smoke(out, n_cycles=10)
    print(f"MCAP:               {summary.mcap_path}")
    print(f"SHA-256:            {summary.mcap_sha256}")
    print(f"Cycles:             {summary.n_cycles}")
    print(f"Outcomes:           {summary.n_outcomes}")
    print(f"Final verdict:      {summary.final_verdict}")
    print(f"Decisions by kind:  {summary.decisions_by_kind}")
    print("Calibrated levels:  " + " -> ".join(summary.calibrated_levels_observed))
    for tag, report, params_str in (
        (
            "BAUD-v1",
            summary.baud_report,
            f"M={summary.baud_report.min_outcomes}, K={summary.baud_report.downgrade_threshold}, ",
        ),
        (
            "ERUR-v1",
            summary.erur_report,
            f"M={summary.erur_report.min_outcomes}, K={summary.erur_report.downgrade_threshold}, ",
        ),
        ("MD-v1", summary.md_report, ""),
        ("RLB-v1", summary.rlb_report, f"W={summary.rlb_report.max_history}, "),
        ("FPB-v1", summary.fpb_report, f"fire_fraction={summary.fpb_report.fire_fraction:.2f}, "),
    ):
        verdict = "HOLDS" if report.holds else "VIOLATED"
        print(
            f"{tag}:           {verdict}  "
            f"({params_str}"
            f"{report.cycles_precondition_held}/{report.cycles_total} "
            "cycles evaluated)"
        )
    sys.exit(1 if summary.any_property_violated else 0)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["ViolationSmokeSummary", "run_violated_smoke"]
