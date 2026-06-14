"""Policy-agnostic verifier demonstration (paper §8.5; Action F).

Runs the reference closed-loop smoke under three structurally distinct
calibration policies and verifies that the property verifier produces
a meaningful verdict for each. The verifier itself is unchanged across
the three runs — only the calibration policy varies.

Policies compared:

- ``MahalanobisDowngradePolicy(M=4, K=2)`` — the reference. Counts
  dirty outcomes in a sliding window; downgrades when ``count >= K``.
  the recovery latency bound's recovery latency bound (paper §6) applies to this
  family specifically.
- ``EWMADowngradePolicy(alpha=0.5, min_outcomes=3, threshold=0.3)`` —
  exponentially-weighted-moving-average over the dirty indicator.
  Downgrades when the EWMA exceeds the threshold. Structurally
  different mechanism; the recovery latency bound does NOT apply.
- ``PerAxisHysteresisDowngradePolicy(upper=3.0)`` — examines the
  worst per-axis Mahalanobis distance; downgrades when either axis
  exceeds the upper threshold. A third structurally distinct
  mechanism.

The script demonstrates that:

1. All three policies satisfy the ``CalibrationAdjustmentPolicy``
   Protocol and can be plugged into ``assess_with_feedback``
   transparently.
2. The verifier (``ghost verify-properties``) is **policy-agnostic**:
   the same five property reports are produced for each run.
3. The verdict for each property is policy-dependent in a meaningful
   way (e.g., EWMA with a low threshold fires BAUD on different
   cycles than the reference).

Reproducible via:

    .venv\\Scripts\\python.exe docs\\paper\\scripts\\compare_policies.py

Writes a JSON summary to ``docs/paper/outputs/policy_comparison.json``
that the paper §8.5 table is generated from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

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
    EWMADowngradePolicy,
    MahalanobisDowngradePolicy,
    PerAxisHysteresisDowngradePolicy,
    assess_with_feedback,
)
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


@dataclass(frozen=True)
class PolicyComparisonRow:
    policy_label: str
    policy_id: str
    mcap_sha256: str
    n_cycles: int
    decisions_by_kind: dict[str, int]
    calibrated_levels_observed: list[str]
    baud_holds: bool
    baud_fire_fraction: float
    erur_holds: bool
    md_holds: bool
    rlb_holds: bool
    fpb_holds: bool


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


def _run_smoke_with_policy(
    output_path: Path,
    feedback_policy: Any,
) -> tuple[dict[str, int], list[str]]:
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

    predictions: list = []
    outcomes: list = []
    calibrated_levels: list[str] = []
    decisions_by_kind: dict[str, int] = {}

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
                outcome = compute_divergence(
                    predictions[k - 1], _ground_truth_pose(t_k), t_k
                )
                outcomes.append(outcome)
                o_adp.publish(outcome)

            prior_stamp = _T0_NS + (k - 1) * _DT_NS if k > 0 else None
            fusion_result = fuse_and_publish(
                oracle,
                FusionInput(
                    sensor_samples=(),
                    prior_belief_stamp_sim_ns=prior_stamp,
                    target_stamp_sim_ns=t_k,
                ),
                f_adp,
            )
            state = fusion_result.belief
            _publish_state(sink, state)

            raw = assess_belief(state, thresholds)
            sa_adp.publish(raw)

            calibrated = assess_with_feedback(
                raw, outcomes, feedback_policy, max_history=_FEEDBACK_MAX_HISTORY
            )
            calibrated_levels.append(calibrated.adjusted_overall_level.value)
            cal_adp.publish(calibrated)

            ctx = DecisionContext(
                belief_stamp_sim_ns=state.stamp_sim_ns,
                self_assessment=raw,
                flight_status=state.flight,
                mission_status=state.mission,
                perception_mode=None,
                calibrated_self_assessment=calibrated,
            )
            decision, rationale = decide_with_rationale(decision_policy, ctx)
            d_adp.publish(decision, rationale)
            decisions_by_kind[decision.kind.value] = (
                decisions_by_kind.get(decision.kind.value, 0) + 1
            )

            actuate_and_publish(actuation_policy, decision, a_adp)

            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            p_adp.publish(prediction)
            predictions.append(prediction)

    return decisions_by_kind, calibrated_levels


def _verify_all_with_baud_params(
    mcap_path: Path,
    *,
    baud_min_outcomes: int,
    baud_downgrade_threshold: int,
) -> tuple[bool, bool, bool, bool, bool, float]:
    """Verify the property set with parameters matching the reference's
    BAUD precondition. EWMA and PerAxis have different internal
    parameters but the BAUD property statement itself is the
    reference's M=4, K=2 — that is what third parties will check.
    """
    baud = verify_baud(
        mcap_path,
        min_outcomes=baud_min_outcomes,
        downgrade_threshold=baud_downgrade_threshold,
    )
    erur = verify_erur(
        mcap_path,
        min_outcomes=baud_min_outcomes,
        downgrade_threshold=baud_downgrade_threshold,
    )
    md = verify_md(mcap_path)
    rlb = verify_rlb(mcap_path, max_history=_FEEDBACK_MAX_HISTORY)
    fpb = verify_fpb(
        mcap_path,
        min_outcomes=baud_min_outcomes,
        downgrade_threshold=baud_downgrade_threshold,
    )
    return baud.holds, erur.holds, md.holds, rlb.holds, fpb.holds, fpb.fire_fraction


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = repo_root / "docs" / "paper" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases: list[tuple[str, Any]] = [
        (
            "MahalanobisDowngradePolicy (reference)",
            MahalanobisDowngradePolicy(
                min_outcomes=_FEEDBACK_MIN_OUTCOMES,
                downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
            ),
        ),
        (
            "EWMADowngradePolicy",
            EWMADowngradePolicy(
                alpha=0.5, min_outcomes=3, downgrade_ewma_threshold=0.3
            ),
        ),
        (
            "PerAxisHysteresisDowngradePolicy",
            PerAxisHysteresisDowngradePolicy(
                min_outcomes=2, upper_mahalanobis=3.0, lower_mahalanobis=1.0
            ),
        ),
    ]

    rows: list[PolicyComparisonRow] = []
    for label, policy in cases:
        slug = policy.policy_id
        mcap_path = (out_dir / f"compare_policy_{slug}.mcap").resolve()
        decisions, levels = _run_smoke_with_policy(mcap_path, policy)
        sha = hashlib.sha256(mcap_path.read_bytes()).hexdigest()
        baud_h, erur_h, md_h, rlb_h, fpb_h, fire_frac = _verify_all_with_baud_params(
            mcap_path,
            baud_min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            baud_downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        )
        rows.append(
            PolicyComparisonRow(
                policy_label=label,
                policy_id=policy.policy_id,
                mcap_sha256=sha,
                n_cycles=_N_CYCLES,
                decisions_by_kind=decisions,
                calibrated_levels_observed=levels,
                baud_holds=baud_h,
                baud_fire_fraction=round(fire_frac, 4),
                erur_holds=erur_h,
                md_holds=md_h,
                rlb_holds=rlb_h,
                fpb_holds=fpb_h,
            )
        )

    payload = {
        "n_cycles": _N_CYCLES,
        "baud_min_outcomes": _FEEDBACK_MIN_OUTCOMES,
        "baud_downgrade_threshold": _FEEDBACK_DOWNGRADE_THRESHOLD,
        "max_history_W": _FEEDBACK_MAX_HISTORY,
        "rows": [
            {
                "policy_label": r.policy_label,
                "policy_id": r.policy_id,
                "mcap_sha256": r.mcap_sha256,
                "n_cycles": r.n_cycles,
                "decisions_by_kind": r.decisions_by_kind,
                "calibrated_levels_observed": r.calibrated_levels_observed,
                "baud_holds": r.baud_holds,
                "baud_fire_fraction": r.baud_fire_fraction,
                "erur_holds": r.erur_holds,
                "md_holds": r.md_holds,
                "rlb_holds": r.rlb_holds,
                "fpb_holds": r.fpb_holds,
            }
            for r in rows
        ],
    }

    json_path = out_dir / "policy_comparison.json"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {json_path}")
    print()
    print(
        f"{'Policy':40s} {'BAUD':>6s} {'ERUR':>6s} {'MD':>4s} {'RLB':>4s} {'FPB':>4s} "
        f"{'fire_frac':>10s}"
    )
    for r in rows:
        print(
            f"{r.policy_label:40s} "
            f"{'OK' if r.baud_holds else 'VIOL':>6s} "
            f"{'OK' if r.erur_holds else 'VIOL':>6s} "
            f"{'OK' if r.md_holds else 'VIOL':>4s} "
            f"{'OK' if r.rlb_holds else 'VIOL':>4s} "
            f"{'OK' if r.fpb_holds else 'VIOL':>4s} "
            f"{r.baud_fire_fraction:>10.4f}"
        )


if __name__ == "__main__":
    main()
