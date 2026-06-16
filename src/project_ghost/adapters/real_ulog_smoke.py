"""End-to-end orchestrator: real PX4 ULog → Ghost closed-loop pipeline → MCAP → verifier.

This closes the v0.3.0 commitment from paper §8.7 earlier than planned:
``run_real_ulog_smoke`` reads a real PX4 ULog via
``project_ghost.adapters.px4_ulog``, subsamples its
``vehicle_local_position`` + ``vehicle_attitude`` to the Ghost cycle
rate, and pipes the resulting pose stream through the **unmodified**
Ghost closed-loop pipeline (same fusion → assessment → calibration →
decision → actuation → forward prediction → divergence flow as the
synthetic smoke). The output MCAP is then verifiable byte-exact with
``ghost verify-properties --mcap <out.mcap>``.

**Honest scope of the ground-truth source.** This orchestrator uses
a stationary fusion oracle as the agent's belief and the ULog's own
EKF2 estimate as the (vacuous) ground truth. With the reference
policies, every cycle in which the real flight has moved measurably
from the initial position registers a divergence event; the policy
responds conservatively and every property HOLDS. The verdict bundle
is reproducible from the same ULog input (verified by the
``mcap_is_deterministic`` test).

The companion module ``real_ulog_discrimination`` (paper §8.8)
re-runs this exact pipeline on the same real ULog with one buggy
policy substituted and demonstrates that the verifier flips its
verdict — i.e., Ghost **discriminates** real flight telemetry
against a known regression, which is the non-vacuous part of the
real-data validation story.

Paper §8.7 + §8.8 report the full provenance:

- ULog source: PX4/pyulog ``test/sample_log_small.ulg`` (~921 KB,
  PX4 v1.10-era SITL log).
- Adapter: ``project_ghost.adapters.px4_ulog.parse_ulog_pose_samples``,
  636 pose samples on the bundled sample.
- Verifier: ``ghost verify-properties --mcap`` from
  ``pip install project-ghost==0.2.3``.
- Nominal verdict (§8.7): all five properties HOLD.
- Discrimination verdict (§8.8): with one buggy decision policy
  substituted, BAUD-v1 flips to VIOLATED on the same real ULog.

Stdlib + numpy + project_ghost internals + pyulog (via adapter).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING, Any, Final

import numpy as np

from project_ghost.adapters.px4_ulog import (
    GroundTruthSource,
    ULogGroundTruthSample,
    ULogPoseSample,
    detect_groundtruth_source,
    parse_ulog_groundtruth_samples,
    parse_ulog_pose_samples,
)
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
    SelfAssessmentLevel,
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
    from pathlib import Path

    from project_ghost.core.prediction import BeliefForwardPrediction, PredictionOutcome
    from project_ghost.state.messages import VehicleState
    from project_ghost.telemetry import TelemetrySink


_DT_NS: Final[int] = 100_000_000  # 100 ms cycle, matches reference smoke
_T0_NS: Final[int] = 1_000_000_000
_COVARIANCE_DIAG: Final[float] = 1e-4

_FEEDBACK_MIN_OUTCOMES: Final[int] = 4
_FEEDBACK_DOWNGRADE_THRESHOLD: Final[int] = 2
_FEEDBACK_MAX_HISTORY: Final[int] = 32

_MAX_REAL_CYCLES: Final[int] = 200  # cap for tractability; real flight may be longer
_MIN_CYCLES_FOR_PIPELINE: Final[int] = 2  # need >= 2 cycles to compute divergence


@dataclass(frozen=True)
class RealULogSmokeSummary:
    """Verdict bundle for a real-ULog end-to-end run.

    ``groundtruth_source`` (v0.2.5, ADR-0037): records whether the
    run sourced GT from an independent SITL track or from the same
    EKF2 estimate the agent fused (circular). Reviewers and CI must
    inspect this field; a HOLDS verdict under ``EKF2_FALLBACK`` on a
    stationary segment is operationally weak (see paper §8.8.1).
    """

    n_pose_samples_in_ulog: int
    n_cycles_run: int
    mcap_path: Path
    mcap_sha256: str
    ulog_sha256: str

    baud_holds: bool
    erur_holds: bool
    md_holds: bool
    rlb_holds: bool
    fpb_holds: bool
    fpb_fire_fraction: float

    groundtruth_source: GroundTruthSource = GroundTruthSource.EKF2_FALLBACK


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _publish_state(sink: TelemetrySink, state: VehicleState) -> None:
    sink.publish(CHANNEL_STATE_NAV, state.stamp_sim_ns, state)


def _samples_to_ground_truth_fn(
    samples: list[ULogPoseSample] | list[ULogGroundTruthSample],
) -> Callable[[int], Pose]:
    """Build a ground-truth function over Ghost sim-time stamps from
    the supplied ULog samples.

    The mapping interpolates linearly in position between the two
    nearest ULog samples; orientation is set to the nearest sample's
    quaternion (no slerp — that would be over-engineering for a
    vacuous-verdict demonstration). The function is agnostic to
    whether the samples are EKF2 estimates (legacy, circular) or
    independent SITL GT (v0.2.5, ADR-0037); both share the same
    ``stamp_us`` / ``position_m`` / ``quaternion_wxyz`` shape.
    """
    if not samples:
        raise ValueError("no ULog samples")

    # Pre-extract for fast lookup.
    sample_stamps_us = np.array([s.stamp_us for s in samples], dtype=np.int64)
    positions = np.array([s.position_m for s in samples], dtype=np.float64)
    quaternions = np.array([s.quaternion_wxyz for s in samples], dtype=np.float64)

    # Sim-time t_ns starts at _T0_NS; ULog stamps are in micros and start
    # at sample_stamps_us[0]. We shift ULog stamps so the first one maps
    # to _T0_NS. Cycle k (sim) of duration _DT_NS maps to ULog us
    # ``sample_stamps_us[0] + k * _DT_NS / 1000``.
    ulog_t0_us = sample_stamps_us[0]

    def gt_fn(t_ns: int) -> Pose:
        delta_ns = max(t_ns - _T0_NS, 0)
        target_us = int(ulog_t0_us + delta_ns // 1_000)
        idx = int(np.searchsorted(sample_stamps_us, target_us, side="left"))
        if idx <= 0:
            pos = positions[0]
            quat = quaternions[0]
        elif idx >= len(sample_stamps_us):
            pos = positions[-1]
            quat = quaternions[-1]
        else:
            t_before = sample_stamps_us[idx - 1]
            t_after = sample_stamps_us[idx]
            span = t_after - t_before
            w = 0.0 if span <= 0 else float(target_us - t_before) / float(span)
            pos = positions[idx - 1] * (1.0 - w) + positions[idx] * w
            # Closer-quaternion (no slerp).
            quat = (
                quaternions[idx - 1]
                if (target_us - t_before) <= (t_after - target_us)
                else quaternions[idx]
            )
        return Pose(
            position_enu_m=np.array(pos, dtype=np.float64),
            orientation_q=np.array(quat, dtype=np.float64),
        )

    return gt_fn


def _subsample_to_cycle_rate(
    samples: list[ULogPoseSample], max_cycles: int
) -> list[ULogPoseSample]:
    """Subsample real ULog samples to Ghost's 10 Hz cycle rate.

    PX4 ``vehicle_local_position`` is typically 100 Hz; Ghost runs at
    10 Hz. Take every n-th sample where n keeps us close to one cycle
    per sample. Caps at ``max_cycles`` for tractability.
    """
    ulog_dt_us = max(
        1,
        (samples[-1].stamp_us - samples[0].stamp_us) // max(1, len(samples) - 1),
    )
    cycles_dt_us = _DT_NS // 1000  # 100_000 us
    stride = max(1, cycles_dt_us // ulog_dt_us)
    return samples[::stride][:max_cycles]


def _run_real_ulog_pipeline(
    sub_samples: list[ULogPoseSample],
    output_mcap_path: Path,
    *,
    feedback_policy: Any,
    decision_policy: Any,
    actuation_policy: Any,
    fake_uncertain_raw: bool = False,
    gt_samples: list[ULogGroundTruthSample] | None = None,
) -> int:
    """Run the Ghost closed-loop pipeline over real ULog pose samples
    with caller-supplied policies. Materialises the MCAP at
    ``output_mcap_path`` and returns the number of cycles run.

    Used by ``run_real_ulog_smoke`` (reference policies — paper §8.7)
    and by ``real_ulog_discrimination`` (one buggy policy — §8.8).
    The MCAP byte layout is identical when the same policies are
    passed; that is what makes the discrimination experiment a
    controlled A/B.

    When ``gt_samples`` is provided (v0.2.5, ADR-0037), the
    divergence comparison sources its GT from those samples instead
    of the agent's own EKF2 estimate. This is what makes BAUD-v1's
    drift precondition fire on stationary segments where the EKF2
    estimate hid sub-cm oscillation in the true pose.
    """
    n_cycles = len(sub_samples)
    if n_cycles < _MIN_CYCLES_FOR_PIPELINE:
        raise ValueError(
            f"After subsampling, only {n_cycles} cycles remain; need "
            f">= {_MIN_CYCLES_FOR_PIPELINE} to run the closed-loop "
            "pipeline."
        )

    gt_fn = _samples_to_ground_truth_fn(
        gt_samples if gt_samples is not None else sub_samples,
    )
    thresholds = _make_thresholds()

    # Oracle fusion seeded from the first real sample. This is a
    # stationary belief by design — the prediction-vs-truth gap is
    # therefore non-zero on any real flight, which is what makes the
    # nominal verdict non-trivially produced (drift is detected; the
    # reference policy responds conservatively; the property HOLDS).
    first_pose = gt_fn(_T0_NS)
    oracle = LinearMotionOracleFusionPolicy(
        initial_position_enu_m=first_pose.position_enu_m.copy(),
        velocity_world_mps=np.zeros(3, dtype=np.float64),
        start_stamp_sim_ns=_T0_NS,
        covariance_diag=_COVARIANCE_DIAG,
    )
    predictor = ConstantVelocityForwardPredictor()

    predictions: list[BeliefForwardPrediction] = []
    outcomes: list[PredictionOutcome] = []

    with MCAPFileSink(output_mcap_path) as sink:
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
                outcome = compute_divergence(predictions[k - 1], gt_fn(t_k), t_k)
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
                # CALIBRATOR_INVENTS_CONFIDENCE category requires a raw
                # assessment that is *not* KNOWN so the buggy calibrator
                # (which always returns KNOWN) visibly inflates
                # confidence and violates MD-v1. The reference real-ULog
                # pipeline normally produces KNOWN raw (tight stationary
                # belief covariance), so we forcibly override the level
                # for this category. The override is private to the
                # buggy run; the nominal MCAP is unaffected.
                raw = _dc_replace(raw, overall_level=SelfAssessmentLevel.UNCERTAIN)
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
            decision, rationale = decide_with_rationale(decision_policy, ctx)
            d_adp.publish(decision, rationale)
            actuate_and_publish(actuation_policy, decision, a_adp)

            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            p_adp.publish(prediction)
            predictions.append(prediction)

    return n_cycles


def _verify_all_and_bundle(
    output_mcap_path: Path,
    *,
    n_pose_samples_in_ulog: int,
    n_cycles: int,
    ulog_sha256: str,
    groundtruth_source: GroundTruthSource = GroundTruthSource.EKF2_FALLBACK,
) -> RealULogSmokeSummary:
    """Run the five property verifiers against ``output_mcap_path``
    and assemble the verdict bundle.
    """
    mcap_bytes = output_mcap_path.read_bytes()
    mcap_sha = hashlib.sha256(mcap_bytes).hexdigest()

    baud = verify_baud(
        output_mcap_path,
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )
    erur = verify_erur(
        output_mcap_path,
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )
    md = verify_md(output_mcap_path)
    rlb = verify_rlb(output_mcap_path, max_history=_FEEDBACK_MAX_HISTORY)
    fpb = verify_fpb(
        output_mcap_path,
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )

    return RealULogSmokeSummary(
        n_pose_samples_in_ulog=n_pose_samples_in_ulog,
        n_cycles_run=n_cycles,
        mcap_path=output_mcap_path,
        mcap_sha256=mcap_sha,
        ulog_sha256=ulog_sha256,
        baud_holds=baud.holds,
        erur_holds=erur.holds,
        md_holds=md.holds,
        rlb_holds=rlb.holds,
        fpb_holds=fpb.holds,
        fpb_fire_fraction=fpb.fire_fraction,
        groundtruth_source=groundtruth_source,
    )


def run_real_ulog_smoke(
    ulog_path: Path,
    output_mcap_path: Path,
    *,
    max_cycles: int = _MAX_REAL_CYCLES,
    groundtruth_source: GroundTruthSource | None = None,
) -> RealULogSmokeSummary:
    """End-to-end: real ULog → Ghost MCAP → property verdicts (reference policies).

    Reads ``ulog_path``, parses real pose samples via the PX4 adapter,
    drives the Ghost closed-loop pipeline with the reference
    feedback, decision and actuation policies, materialises the
    resulting MCAP to ``output_mcap_path``, and runs the five
    property verifiers. Returns the verdict bundle.

    The number of cycles is the lesser of ``max_cycles`` and the
    number of ULog samples (one per cycle, after subsampling to
    Ghost's 10 Hz rate). The MCAP SHA-256 is deterministic given the
    same ULog input.

    ``groundtruth_source`` (v0.2.5, ADR-0037):

    - ``None`` (default): auto-detect via
      :func:`detect_groundtruth_source`. PX4 SITL logs with the GT
      logger enabled are upgraded to ``SITL_SIMULATOR``; everything
      else falls back to ``EKF2_FALLBACK`` with a recorded marker
      in the summary.
    - ``GroundTruthSource.EKF2_FALLBACK``: force the legacy
      circular path even if SITL GT is available (used by paper
      §8.8.2 to A/B the two GT sources on the same ULog).
    - ``GroundTruthSource.SITL_SIMULATOR``: force SITL GT; raises
      ``ULogParseError`` if the ULog has no GT topics.
    """
    samples = parse_ulog_pose_samples(ulog_path)
    if not samples:
        raise ValueError(f"ULog produced 0 pose samples: {ulog_path}")
    sub_samples = _subsample_to_cycle_rate(samples, max_cycles)

    resolved_source = (
        groundtruth_source
        if groundtruth_source is not None
        else detect_groundtruth_source(ulog_path)
    )
    gt_samples: list[ULogGroundTruthSample] | None = None
    if resolved_source is GroundTruthSource.SITL_SIMULATOR:
        gt_samples = parse_ulog_groundtruth_samples(ulog_path)

    feedback_policy = MahalanobisDowngradePolicy(
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )
    decision_policy = UncertaintyAwareReferencePolicy()
    actuation_policy = AttitudeHoldReferencePolicy()

    n_cycles = _run_real_ulog_pipeline(
        sub_samples,
        output_mcap_path,
        feedback_policy=feedback_policy,
        decision_policy=decision_policy,
        actuation_policy=actuation_policy,
        gt_samples=gt_samples,
    )

    ulog_sha = hashlib.sha256(ulog_path.read_bytes()).hexdigest()
    return _verify_all_and_bundle(
        output_mcap_path,
        n_pose_samples_in_ulog=len(samples),
        n_cycles=n_cycles,
        ulog_sha256=ulog_sha,
        groundtruth_source=resolved_source,
    )


__all__ = [
    "RealULogSmokeSummary",
    "run_real_ulog_smoke",
]
