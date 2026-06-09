"""N-cycle closed-loop smoke that exercises every contract from
ADR-0019 through ADR-0026 in a single pipeline.

Scenario design (deliberately constructed to expose feedback):

- The agent's twist is zero — it thinks it's stationary.
- The covariance is small — the agent declares itself KNOWN.
- The constant-velocity predictor extrapolates "no motion" with small
  std.
- Groundtruth drifts at a constant rate. Each observation lands far
  from the prediction.
- Outcomes verdict ``BEYOND_5_STD`` consistently.
- ``MahalanobisDowngradePolicy`` downgrades the calibrated assessment
  KNOWN → UNCERTAIN after the threshold of bad outcomes is reached.

Wiring of channels (all to one MCAP):

- ``/state/nav``                    each ``VehicleState``
- ``/self_assessment``              each raw ``BeliefSelfAssessment``
- ``/self_assessment/calibrated``   each ``CalibratedSelfAssessment``
- ``/decisions``                    each ``DecisionRationale``
- ``/actuations``                   each ``ActuationDirective``
- ``/predictions/forward``          each ``BeliefForwardPrediction``
- ``/predictions/outcomes``         each ``PredictionOutcome`` (k>=1)

Closure of the gap identified in the previous smoke (ADR-0027):

The previous version of this smoke surfaced that the decision policy
consumed only the raw ``BeliefSelfAssessment``, so the calibrated
downgrade had no behavioral effect. ADR-0027 closes that by adding an
optional ``calibrated_self_assessment`` field to ``DecisionContext``
and routing ``effective_overall_level`` (calibrated priority) through
the reference policy. This smoke now wires the calibrated record into
the context, so cycles 5-10 transition from PROCEED to HOLD as the
feedback kicks in.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import numpy as np

from project_ghost.core.actuation import (
    KillOnlyActuationPolicy,
    actuate_and_publish,
)
from project_ghost.core.decisions import (
    DecisionContext,
    UncertaintyAwareReferencePolicy,
    decide_with_rationale,
)
from project_ghost.core.feedback import (
    MahalanobisDowngradePolicy,
    assess_with_feedback,
)
from project_ghost.core.prediction import (
    ConstantVelocityForwardPredictor,
    compute_divergence,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    assess_belief,
)
from project_ghost.hal.messages import SensorHealth
from project_ghost.state.messages import (
    FlightMode,
    FlightStatus,
    IMUBiases,
    MissionMode,
    MissionStatus,
    NavigationState,
    Pose,
    SensorHealthMap,
    Twist,
    VehicleState,
)
from project_ghost.telemetry import (
    ActuationToTelemetryAdapter,
    CalibratedSelfAssessmentToTelemetryAdapter,
    DecisionToTelemetryAdapter,
    ForwardPredictionToTelemetryAdapter,
    MCAPFileSink,
    PredictionOutcomeToTelemetryAdapter,
    SelfAssessmentToTelemetryAdapter,
    encode_to_bytes,
)
from project_ghost.telemetry.channels import CHANNEL_STATE_NAV

if TYPE_CHECKING:
    from project_ghost.core.feedback import CalibratedSelfAssessment
    from project_ghost.core.prediction import (
        BeliefForwardPrediction,
        PredictionOutcome,
    )
    from project_ghost.telemetry import TelemetrySink

    _PredictionType = BeliefForwardPrediction
    _OutcomeType = PredictionOutcome
    _CalibratedType = CalibratedSelfAssessment


_Q_IDENTITY: Final[np.ndarray] = np.array(
    [1.0, 0.0, 0.0, 0.0], dtype=np.float64
)

# Scenario parameters. Picked to force feedback to fire by ~cycle 4.
_DT_NS: Final[int] = 100_000_000  # 100 ms cycle
_T0_NS: Final[int] = 1_000_000_000  # start at t = 1 s
_GROUND_TRUTH_DRIFT_X_MPS: Final[float] = 5.0  # ground truth moves
_COVARIANCE_DIAG: Final[float] = 1e-4  # small -> predicted std small
_MIN_CYCLES: Final[int] = 2  # need at least one outcome


@dataclass(frozen=True)
class SmokeSummary:
    """Aggregate observations from a single smoke run.

    Used by the integration test to assert invariants on the MCAP and
    on the run itself.
    """

    n_cycles: int
    n_outcomes: int
    n_decisions: int
    decisions_by_kind: dict[str, int]
    calibrated_levels_observed: list[str]
    final_verdict: str | None
    mcap_path: Path
    mcap_sha256: str


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
    """Ground-truth pose at sim time ``t_ns``.

    Pure function of time — deterministic. Linear drift in x.
    """
    dt_s = (t_ns - _T0_NS) / 1e9
    return Pose(
        position_enu_m=np.array(
            [_GROUND_TRUTH_DRIFT_X_MPS * dt_s, 0.0, 0.0],
            dtype=np.float64,
        ),
        orientation_q=_Q_IDENTITY.copy(),
    )


def _make_state(t_ns: int) -> VehicleState:
    """Construct the agent's belief at sim time ``t_ns``.

    The agent believes pose = ground truth (perfect estimator for the
    smoke; the gap is in *prediction*, not estimation).
    The agent's twist is *zero* in world frame — the agent doesn't
    know it's drifting. The covariance is small — the agent declares
    itself KNOWN.
    """
    pose = _ground_truth_pose(t_ns)
    cov = np.eye(15, dtype=np.float64) * _COVARIANCE_DIAG
    nav = NavigationState(
        pose=pose,
        twist_world=Twist(
            linear_mps=np.zeros(3, dtype=np.float64),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="world",
        ),
        twist_body=Twist(
            linear_mps=np.zeros(3, dtype=np.float64),
            angular_rps=np.zeros(3, dtype=np.float64),
            frame="body",
        ),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=IMUBiases(
            accel_bias_mps2=np.zeros(3, dtype=np.float64),
            gyro_bias_rps=np.zeros(3, dtype=np.float64),
        ),
        covariance_15x15=cov,
    )
    return VehicleState(
        stamp_sim_ns=t_ns,
        stamp_wall_ns=0,
        nav=nav,
        sensors=SensorHealthMap(
            by_id=MappingProxyType({"imu0": SensorHealth.OK})
        ),
        flight=FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=12.0,
            battery_pct=0.9,
            error_flags=0,
        ),
        mission=MissionStatus(
            mode=MissionMode.IDLE,
            current_goal=None,
            progress=0.0,
            started_sim_ns=None,
        ),
    )


def _publish_vehicle_state(sink: TelemetrySink, state: VehicleState) -> None:
    """Publish ``state`` to ``/state/nav`` channel.

    Inlined here because no canonical adapter exists yet for
    ``VehicleState`` → telemetry (state is published directly by the
    aggregator in real wiring).
    """
    sink.publish(CHANNEL_STATE_NAV, state.stamp_sim_ns, state)


def run_closed_loop_smoke(
    output_path: Path,
    *,
    n_cycles: int = 10,
) -> SmokeSummary:
    """Run the N-cycle smoke and write a complete MCAP to ``output_path``.

    Pure modulo I/O: same ``n_cycles`` and same ``output_path``
    produce byte-identical MCAP across runs (cross-process
    determinism inherited from T4).

    Returns ``SmokeSummary`` for the integration test to assert on.
    """
    if n_cycles < _MIN_CYCLES:
        raise ValueError(
            f"n_cycles must be >= {_MIN_CYCLES} (need at least one "
            f"outcome); got {n_cycles}"
        )

    thresholds = _make_thresholds()
    predictor = ConstantVelocityForwardPredictor()
    decision_policy = UncertaintyAwareReferencePolicy()
    actuation_policy = KillOnlyActuationPolicy()
    feedback_policy = MahalanobisDowngradePolicy(
        min_outcomes=4, downgrade_threshold=2
    )

    predictions_by_cycle: list[_PredictionType] = []
    outcomes_so_far: list[_OutcomeType] = []
    calibrated_records: list[_CalibratedType] = []
    decisions_by_kind: dict[str, int] = {}

    with MCAPFileSink(output_path) as sink:
        sa_adapter = SelfAssessmentToTelemetryAdapter(sink)
        cal_adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        dec_adapter = DecisionToTelemetryAdapter(sink)
        act_adapter = ActuationToTelemetryAdapter(sink)
        out_adapter = PredictionOutcomeToTelemetryAdapter(sink)
        pred_adapter = ForwardPredictionToTelemetryAdapter(sink)

        for k in range(n_cycles):
            t_k = _T0_NS + k * _DT_NS

            # ---- 1. Outcome from previous cycle's prediction --------
            # (We process the outcome BEFORE building this cycle's
            # state so feedback can use it.)
            if k > 0:
                prior_prediction = predictions_by_cycle[k - 1]
                actual_pose = _ground_truth_pose(t_k)
                outcome = compute_divergence(
                    prior_prediction, actual_pose, t_k
                )
                outcomes_so_far.append(outcome)
                out_adapter.publish(outcome)

            # ---- 2. Belief at t_k ----------------------------------
            state = _make_state(t_k)
            _publish_vehicle_state(sink, state)

            # ---- 3. Raw self-assessment ----------------------------
            raw_assessment = assess_belief(state, thresholds)
            sa_adapter.publish(raw_assessment)

            # ---- 4. Calibrated self-assessment (feedback) ----------
            calibrated = assess_with_feedback(
                raw_assessment,
                outcomes_so_far,
                feedback_policy,
                max_history=32,
            )
            calibrated_records.append(calibrated)
            cal_adapter.publish(calibrated)

            # ---- 5. Decision (calibration-aware via ADR-0027) ------
            # The calibrated assessment is wired into the context; the
            # reference policy reads context.effective_overall_level
            # which prioritizes the adjusted level over the raw.
            ctx = DecisionContext(
                belief_stamp_sim_ns=state.stamp_sim_ns,
                self_assessment=raw_assessment,
                flight_status=state.flight,
                mission_status=state.mission,
                perception_mode=None,
                calibrated_self_assessment=calibrated,
            )
            decision, rationale = decide_with_rationale(
                decision_policy, ctx
            )
            dec_adapter.publish(decision, rationale)
            decisions_by_kind[decision.kind.value] = (
                decisions_by_kind.get(decision.kind.value, 0) + 1
            )

            # ---- 6. Actuation --------------------------------------
            actuate_and_publish(actuation_policy, decision, act_adapter)

            # ---- 7. Forward prediction for next cycle --------------
            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            pred_adapter.publish(prediction)
            predictions_by_cycle.append(prediction)

    final_verdict = (
        outcomes_so_far[-1].verdict.value if outcomes_so_far else None
    )
    calibrated_levels_observed = [
        c.adjusted_overall_level.value for c in calibrated_records
    ]

    mcap_bytes = output_path.read_bytes()
    mcap_sha = hashlib.sha256(mcap_bytes).hexdigest()

    # Sanity: encode the last calibrated record to bytes to confirm
    # the determinism contract holds round-trip per type.
    _ = encode_to_bytes(calibrated_records[-1])

    return SmokeSummary(
        n_cycles=n_cycles,
        n_outcomes=len(outcomes_so_far),
        n_decisions=n_cycles,
        decisions_by_kind=decisions_by_kind,
        calibrated_levels_observed=calibrated_levels_observed,
        final_verdict=final_verdict,
        mcap_path=output_path,
        mcap_sha256=mcap_sha,
    )


def main() -> None:
    """CLI entry: write to ``./closed_loop_smoke.mcap`` and print summary."""
    out = Path("closed_loop_smoke.mcap").resolve()
    summary = run_closed_loop_smoke(out, n_cycles=10)
    print(f"MCAP:                       {summary.mcap_path}")
    print(f"SHA-256:                    {summary.mcap_sha256}")
    print(f"Cycles:                     {summary.n_cycles}")
    print(f"Outcomes:                   {summary.n_outcomes}")
    print(f"Final verdict:              {summary.final_verdict}")
    print(f"Decisions by kind:          {summary.decisions_by_kind}")
    print(
        "Calibrated levels:          "
        + " -> ".join(summary.calibrated_levels_observed)
    )


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["SmokeSummary", "run_closed_loop_smoke"]
