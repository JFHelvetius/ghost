"""Replay verification from stored ``FusionResult`` records (ADR-0030).

Reads ``FusionResult`` records from the ``/fusion/results`` channel of a
source MCAP produced by ``run_closed_loop_smoke``, re-executes the
downstream pipeline with identical parameters, and verifies that the
downstream channel payloads are byte-for-byte identical between the
original run and the replay.

This is the end-to-end reproducibility guarantee: given the
``/fusion/results`` channel and the scenario parameters, every
downstream decision, actuation, prediction, and outcome can be
reconstructed without re-running the oracle or the fusion layer.

Downstream channels compared byte-for-byte:

- ``/self_assessment``
- ``/self_assessment/calibrated``
- ``/decisions``
- ``/actuations``
- ``/predictions/forward``
- ``/predictions/outcomes``

Channels NOT replayed (source-only):

- ``/fusion/results`` — the replay source; not re-generated.
- ``/state/nav``     — ``VehicleState`` lives inside ``FusionResult.belief``.

Scenario parameters (must match ``closed_loop_smoke.py``):

- ``_DT_NS = 100_000_000``  — 100 ms cycle
- ``_T0_NS = 1_000_000_000`` — sim start at t = 1 s
- ``_GROUND_TRUTH_DRIFT_X_MPS = 5.0`` — x drift in ground truth

Override ``ground_truth_fn`` when verifying a custom scenario.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
from project_ghost.core.prediction import (
    ConstantVelocityForwardPredictor,
    compute_divergence,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    assess_belief,
)
from project_ghost.state.messages import Pose
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_FORWARD_PREDICTIONS,
    CHANNEL_FUSION_RESULTS,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    ActuationToTelemetryAdapter,
    CalibratedSelfAssessmentToTelemetryAdapter,
    DecisionToTelemetryAdapter,
    ForwardPredictionToTelemetryAdapter,
    MCAPFileSink,
    MCAPReplayReader,
    PredictionOutcomeToTelemetryAdapter,
    SelfAssessmentToTelemetryAdapter,
    decode_message,
    encode_to_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_ghost.core.fusion.types import FusionResult
    from project_ghost.core.prediction.divergence import PredictionOutcome
    from project_ghost.core.prediction.types import BeliefForwardPrediction
    from project_ghost.state.messages import VehicleState


# Scenario constants — must be kept in sync with closed_loop_smoke.py.
_DT_NS: Final[int] = 100_000_000
_T0_NS: Final[int] = 1_000_000_000
_GROUND_TRUTH_DRIFT_X_MPS: Final[float] = 5.0

_DOWNSTREAM_CHANNELS: Final[frozenset[str]] = frozenset(
    {
        CHANNEL_SELF_ASSESSMENT,
        CHANNEL_CALIBRATED_SELF_ASSESSMENT,
        CHANNEL_DECISIONS,
        CHANNEL_ACTUATIONS,
        CHANNEL_FORWARD_PREDICTIONS,
        CHANNEL_PREDICTION_OUTCOMES,
    }
)


@dataclass(frozen=True)
class ChannelVerification:
    """Byte-equality result for one downstream channel."""

    channel: str
    source_count: int
    replay_count: int
    byte_equal: bool
    first_mismatch_index: int | None


@dataclass(frozen=True)
class ReplayVerificationSummary:
    """Aggregate result of a ``replay_downstream_from_fusion`` call."""

    source_path: Path
    replay_path: Path
    source_sha256: str
    replay_sha256: str
    channels: tuple[ChannelVerification, ...]
    all_channels_byte_equal: bool


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def _default_ground_truth(t_ns: int) -> Pose:
    """Default ground-truth pose: linear x-drift at 5 m/s from t=1 s."""
    dt_s = (t_ns - _T0_NS) / 1e9
    return Pose(
        position_enu_m=np.array(
            [_GROUND_TRUTH_DRIFT_X_MPS * dt_s, 0.0, 0.0],
            dtype=np.float64,
        ),
        orientation_q=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
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


# ---------------------------------------------------------------------------
# Source collection
# ---------------------------------------------------------------------------


def _collect_source_bytes(
    source_path: Path,
) -> tuple[list[FusionResult], dict[str, list[bytes]]]:
    """Read source MCAP: collect FusionResult objects and per-channel bytes."""
    fusion_results: list[FusionResult] = []
    source_bytes: dict[str, list[bytes]] = {ch: [] for ch in _DOWNSTREAM_CHANNELS}
    with MCAPReplayReader(source_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel == CHANNEL_FUSION_RESULTS:
                fusion_results.append(decode_message(msg))
            elif msg.channel in _DOWNSTREAM_CHANNELS:
                source_bytes[msg.channel].append(encode_to_bytes(decode_message(msg)))
    return fusion_results, source_bytes


# ---------------------------------------------------------------------------
# Replay execution
# ---------------------------------------------------------------------------


def _execute_replay(
    fusion_results: list[FusionResult],
    replay_path: Path,
    ground_truth_fn: Callable[[int], Pose],
) -> None:
    """Re-run downstream pipeline over stored beliefs; write to replay_path."""
    thresholds = _make_thresholds()
    decision_policy = UncertaintyAwareReferencePolicy()
    actuation_policy = AttitudeHoldReferencePolicy()
    feedback_policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    predictor = ConstantVelocityForwardPredictor()

    outcomes_so_far: list[PredictionOutcome] = []
    predictions: list[BeliefForwardPrediction] = []

    with MCAPFileSink(replay_path) as sink:
        sa_adapter = SelfAssessmentToTelemetryAdapter(sink)
        cal_adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
        dec_adapter = DecisionToTelemetryAdapter(sink)
        act_adapter = ActuationToTelemetryAdapter(sink)
        out_adapter = PredictionOutcomeToTelemetryAdapter(sink)
        pred_adapter = ForwardPredictionToTelemetryAdapter(sink)

        for k, fusion_result in enumerate(fusion_results):
            state: VehicleState = fusion_result.belief
            t_k = state.stamp_sim_ns

            if k > 0:
                actual_pose = ground_truth_fn(t_k)
                outcome = compute_divergence(predictions[k - 1], actual_pose, t_k)
                outcomes_so_far.append(outcome)
                out_adapter.publish(outcome)

            raw = assess_belief(state, thresholds)
            sa_adapter.publish(raw)

            calibrated = assess_with_feedback(raw, outcomes_so_far, feedback_policy, max_history=32)
            cal_adapter.publish(calibrated)

            ctx = DecisionContext(
                belief_stamp_sim_ns=state.stamp_sim_ns,
                self_assessment=raw,
                flight_status=state.flight,
                mission_status=state.mission,
                perception_mode=None,
                calibrated_self_assessment=calibrated,
            )
            decision, rationale = decide_with_rationale(decision_policy, ctx)
            dec_adapter.publish(decision, rationale)

            actuate_and_publish(actuation_policy, decision, act_adapter)

            prediction = predictor.predict(state, horizon_ns=_DT_NS)
            pred_adapter.publish(prediction)
            predictions.append(prediction)


# ---------------------------------------------------------------------------
# Replay collection
# ---------------------------------------------------------------------------


def _collect_replay_bytes(replay_path: Path) -> dict[str, list[bytes]]:
    """Read replay MCAP: collect per-channel encoded bytes."""
    replay_bytes: dict[str, list[bytes]] = {ch: [] for ch in _DOWNSTREAM_CHANNELS}
    with MCAPReplayReader(replay_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel in _DOWNSTREAM_CHANNELS:
                replay_bytes[msg.channel].append(encode_to_bytes(decode_message(msg)))
    return replay_bytes


# ---------------------------------------------------------------------------
# Channel comparison
# ---------------------------------------------------------------------------


def _verify_channels(
    source_bytes: dict[str, list[bytes]],
    replay_bytes: dict[str, list[bytes]],
) -> tuple[ChannelVerification, ...]:
    """Compare per-channel byte lists; return one ChannelVerification each."""
    results: list[ChannelVerification] = []
    for channel in sorted(_DOWNSTREAM_CHANNELS):
        src = source_bytes.get(channel, [])
        rpl = replay_bytes.get(channel, [])
        counts_match = len(src) == len(rpl)
        if counts_match and src == rpl:
            results.append(
                ChannelVerification(
                    channel=channel,
                    source_count=len(src),
                    replay_count=len(rpl),
                    byte_equal=True,
                    first_mismatch_index=None,
                )
            )
        else:
            first_mismatch: int | None = None
            if counts_match:
                for i, (a, b) in enumerate(zip(src, rpl, strict=True)):
                    if a != b:
                        first_mismatch = i
                        break
            results.append(
                ChannelVerification(
                    channel=channel,
                    source_count=len(src),
                    replay_count=len(rpl),
                    byte_equal=False,
                    first_mismatch_index=first_mismatch,
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def replay_downstream_from_fusion(
    source_path: Path,
    replay_path: Path,
    *,
    ground_truth_fn: Callable[[int], Pose] | None = None,
) -> ReplayVerificationSummary:
    """Replay downstream pipeline from stored ``FusionResult`` records.

    Reads ``/fusion/results`` from ``source_path``, re-executes the
    downstream pipeline (assessment → calibration → decision →
    actuation → prediction → divergence), writes the result to
    ``replay_path``, and compares downstream channel payloads
    byte-for-byte against the source.

    Parameters:

    - ``source_path``: MCAP produced by ``run_closed_loop_smoke``.
    - ``replay_path``: destination path for the replay MCAP.
    - ``ground_truth_fn``: ``(t_ns: int) -> Pose``; maps sim time to
      ground-truth pose for divergence computation. When ``None`` uses
      the default smoke scenario (5 m/s x-drift from t=1 s).

    Returns ``ReplayVerificationSummary`` with per-channel
    ``ChannelVerification`` records and ``all_channels_byte_equal``.
    """
    gt_fn = ground_truth_fn if ground_truth_fn is not None else _default_ground_truth

    fusion_results, source_bytes = _collect_source_bytes(source_path)
    _execute_replay(fusion_results, replay_path, gt_fn)
    replay_bytes = _collect_replay_bytes(replay_path)

    channels = _verify_channels(source_bytes, replay_bytes)
    all_equal = all(c.byte_equal for c in channels)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    replay_sha = hashlib.sha256(replay_path.read_bytes()).hexdigest()

    return ReplayVerificationSummary(
        source_path=source_path,
        replay_path=replay_path,
        source_sha256=source_sha,
        replay_sha256=replay_sha,
        channels=channels,
        all_channels_byte_equal=all_equal,
    )


__all__ = [
    "ChannelVerification",
    "ReplayVerificationSummary",
    "replay_downstream_from_fusion",
]
