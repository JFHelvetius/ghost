"""Reproducible measurement script for the paper §7 Evaluation tables.

Runs the closed-loop reference smoke under three calibrator parameter
combinations (the reference (M=4, K=2), a more sensitive (M=3, K=1),
and a less sensitive (M=5, K=3)) and reports:

- MCAP size in bytes
- End-to-end smoke runtime in seconds
- Per-property verifier runtime in milliseconds (mean of 5 runs)
- Property holds verdict per (M, K) combination
- BAUD precondition fire fraction per (M, K)

Writes JSON to ``docs/paper/outputs/metrics.json`` so the paper can
cite numerically reproducible values. Run from repo root:

    .venv\\Scripts\\python.exe docs\\paper\\scripts\\measure_metrics.py

Reuses the reference smoke building blocks and calls
``MahalanobisDowngradePolicy`` directly to avoid touching
``examples/closed_loop_smoke.py``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

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
    MahalanobisDowngradePolicy,
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
    from collections.abc import Callable

    from project_ghost.core.feedback import CalibratedSelfAssessment
    from project_ghost.core.prediction import (
        BeliefForwardPrediction,
        PredictionOutcome,
    )
    from project_ghost.state.messages import VehicleState
    from project_ghost.telemetry import TelemetrySink

_DT_NS: Final[int] = 100_000_000
_T0_NS: Final[int] = 1_000_000_000
_GROUND_TRUTH_DRIFT_X_MPS: Final[float] = 5.0
_COVARIANCE_DIAG: Final[float] = 1e-4
_FEEDBACK_MAX_HISTORY: Final[int] = 32

_VERIFIER_TIMING_REPLICAS: Final[int] = 5
_VERIFIER_TIMING_WARMUP: Final[int] = 1
_BENCH_N_CYCLES: Final[tuple[int, ...]] = (10, 50, 200)
_POLICY_GRID: Final[tuple[tuple[int, int], ...]] = (
    (4, 2),  # reference
    (3, 1),  # more sensitive
    (5, 3),  # less sensitive
)


@dataclass(frozen=True)
class RunMetrics:
    label: str
    M: int
    K: int
    n_cycles: int
    smoke_runtime_s: float
    mcap_size_bytes: int
    mcap_sha256: str
    verifier_ms_per_property_mean: dict[str, float]
    verifier_ms_total_mean: float
    holds_per_property: dict[str, bool]
    baud_fire_fraction: float
    decisions_by_kind: dict[str, int]
    calibrated_levels_observed: list[str]


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


def _run_smoke(
    output_path: Path,
    *,
    n_cycles: int,
    M: int,
    K: int,
) -> dict[str, object]:
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
    feedback_policy = MahalanobisDowngradePolicy(min_outcomes=M, downgrade_threshold=K)

    predictions: list[BeliefForwardPrediction] = []
    outcomes: list[PredictionOutcome] = []
    calibrated_records: list[CalibratedSelfAssessment] = []
    decisions_by_kind: dict[str, int] = {}

    with MCAPFileSink(output_path) as sink:
        f_adp = FusionResultToTelemetryAdapter(sink)
        sa_adp = SelfAssessmentToTelemetryAdapter(sink)
        cal_adp = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        d_adp = DecisionToTelemetryAdapter(sink)
        a_adp = ActuationToTelemetryAdapter(sink)
        o_adp = PredictionOutcomeToTelemetryAdapter(sink)
        p_adp = ForwardPredictionToTelemetryAdapter(sink)

        for k in range(n_cycles):
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
            sa_adp.publish(raw)

            calibrated = assess_with_feedback(
                raw, outcomes, feedback_policy, max_history=_FEEDBACK_MAX_HISTORY
            )
            calibrated_records.append(calibrated)
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

    return {
        "decisions_by_kind": decisions_by_kind,
        "calibrated_levels_observed": [c.adjusted_overall_level.value for c in calibrated_records],
    }


def _time_verifier(
    fn: Callable[..., object], output_path: Path, **kwargs: object
) -> float:
    for _ in range(_VERIFIER_TIMING_WARMUP):
        fn(output_path, **kwargs)
    timings: list[float] = []
    for _ in range(_VERIFIER_TIMING_REPLICAS):
        t = time.perf_counter()
        fn(output_path, **kwargs)
        timings.append((time.perf_counter() - t) * 1000.0)
    return sum(timings) / len(timings)


def measure_one(label: str, M: int, K: int, n_cycles: int, out_dir: Path) -> RunMetrics:
    out = (out_dir / f"smoke_{label}_n{n_cycles}.mcap").resolve()
    t0 = time.perf_counter()
    extras = _run_smoke(out, n_cycles=n_cycles, M=M, K=K)
    smoke_runtime = time.perf_counter() - t0

    mcap_bytes = out.read_bytes()
    sha = hashlib.sha256(mcap_bytes).hexdigest()

    verifier_times = {
        "BAUD-v1": _time_verifier(verify_baud, out, min_outcomes=M, downgrade_threshold=K),
        "ERUR-v1": _time_verifier(verify_erur, out, min_outcomes=M, downgrade_threshold=K),
        "MD-v1": _time_verifier(verify_md, out),
        "RLB-v1": _time_verifier(verify_rlb, out, max_history=_FEEDBACK_MAX_HISTORY),
        "FPB-v1": _time_verifier(verify_fpb, out, min_outcomes=M, downgrade_threshold=K),
    }
    verifier_times = {k: round(v, 3) for k, v in verifier_times.items()}

    baud = verify_baud(out, min_outcomes=M, downgrade_threshold=K)
    erur = verify_erur(out, min_outcomes=M, downgrade_threshold=K)
    md = verify_md(out)
    rlb = verify_rlb(out, max_history=_FEEDBACK_MAX_HISTORY)
    fpb = verify_fpb(out, min_outcomes=M, downgrade_threshold=K)

    return RunMetrics(
        label=label,
        M=M,
        K=K,
        n_cycles=n_cycles,
        smoke_runtime_s=round(smoke_runtime, 4),
        mcap_size_bytes=len(mcap_bytes),
        mcap_sha256=sha,
        verifier_ms_per_property_mean=verifier_times,
        verifier_ms_total_mean=round(sum(verifier_times.values()), 3),
        holds_per_property={
            "BAUD-v1": baud.holds,
            "ERUR-v1": erur.holds,
            "MD-v1": md.holds,
            "RLB-v1": rlb.holds,
            "FPB-v1": fpb.holds,
        },
        baud_fire_fraction=round(fpb.fire_fraction, 4),
        decisions_by_kind=extras["decisions_by_kind"],  # type: ignore[arg-type]
        calibrated_levels_observed=extras["calibrated_levels_observed"],  # type: ignore[arg-type]
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = repo_root / "docs" / "paper" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_runs: list[RunMetrics] = []
    for M, K in _POLICY_GRID:
        for n_cycles in _BENCH_N_CYCLES:
            label = f"M{M}K{K}"
            print(f"[bench] {label} n={n_cycles}...", flush=True)
            metrics = measure_one(label, M, K, n_cycles, out_dir)
            all_runs.append(metrics)

    payload = {
        "policy_grid": [{"M": M, "K": K} for (M, K) in _POLICY_GRID],
        "n_cycles_grid": list(_BENCH_N_CYCLES),
        "verifier_timing_replicas": _VERIFIER_TIMING_REPLICAS,
        "verifier_timing_warmup": _VERIFIER_TIMING_WARMUP,
        "runs": [
            {
                "label": r.label,
                "M": r.M,
                "K": r.K,
                "n_cycles": r.n_cycles,
                "smoke_runtime_s": r.smoke_runtime_s,
                "mcap_size_bytes": r.mcap_size_bytes,
                "mcap_sha256": r.mcap_sha256,
                "verifier_ms_per_property_mean": r.verifier_ms_per_property_mean,
                "verifier_ms_total_mean": r.verifier_ms_total_mean,
                "holds_per_property": r.holds_per_property,
                "baud_fire_fraction": r.baud_fire_fraction,
                "decisions_by_kind": r.decisions_by_kind,
                "calibrated_levels_observed": r.calibrated_levels_observed,
            }
            for r in all_runs
        ],
    }

    json_path = out_dir / "metrics.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nWrote {json_path}")
    print(
        f"\nSummary: {len(all_runs)} runs across "
        f"{len(_POLICY_GRID)} policies × {len(_BENCH_N_CYCLES)} cycle counts."
    )


if __name__ == "__main__":
    main()
