"""Tests del ``PredictionOutcomeToTelemetryAdapter`` y round-trip MCAP
(ADR-0025).

Cubre:

- Adapter publica al canal correcto con ``actual_belief_stamp`` como
  ``log_time``.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- MCAP round-trip: write outcome → read → decoded matchea.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end: predict → observe → compute_divergence → MCAP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.prediction import (
    BeliefForwardPrediction,
    DivergenceVerdict,
    PoseStd,
    PredictionOutcome,
    compute_divergence,
)
from project_ghost.state.messages import Pose
from project_ghost.telemetry import (
    CHANNEL_PREDICTION_OUTCOMES,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    PredictionOutcomeToTelemetryAdapter,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _pose(x: float = 0.0) -> Pose:
    return Pose(
        position_enu_m=np.array([x, 0.0, 0.0], dtype=np.float64),
        orientation_q=_Q_IDENTITY.copy(),
    )


def _prediction(stamp: int = 1000, horizon: int = 500) -> BeliefForwardPrediction:
    return BeliefForwardPrediction(
        source_belief_stamp_sim_ns=stamp,
        predicted_observation_stamp_sim_ns=stamp + horizon,
        horizon_ns=horizon,
        predicted_pose=_pose(),
        predicted_pose_std=PoseStd(
            position_std_enu_m=np.full(3, 0.2, dtype=np.float64),
            orientation_std_rad=np.full(3, 0.1, dtype=np.float64),
        ),
        associated_directive_hash=None,
        predictor_id="constant_velocity_v1",
    )


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = PredictionOutcomeToTelemetryAdapter(sink)
    pred = _prediction(stamp=1000, horizon=500)
    outcome = compute_divergence(
        pred, _pose(x=0.05), pred.predicted_observation_stamp_sim_ns
    )
    adapter.publish(outcome)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_PREDICTION_OUTCOMES


def test_adapter_uses_actual_belief_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = PredictionOutcomeToTelemetryAdapter(sink)
    pred = _prediction(stamp=1000, horizon=500)
    actual_stamp = pred.predicted_observation_stamp_sim_ns
    outcome = compute_divergence(pred, _pose(), actual_stamp)
    adapter.publish(outcome)
    assert sink.captured[0].stamp_sim_ns == actual_stamp


def test_adapter_publishes_outcome_as_message() -> None:
    sink = InMemorySink()
    adapter = PredictionOutcomeToTelemetryAdapter(sink)
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    adapter.publish(outcome)
    assert sink.captured[0].message is outcome


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = PredictionOutcomeToTelemetryAdapter(
        sink, channel="/custom/outcomes"
    )
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    adapter.publish(outcome)
    assert sink.captured[0].channel == "/custom/outcomes"
    assert adapter.channel == "/custom/outcomes"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        PredictionOutcomeToTelemetryAdapter(sink, channel="no_slash")


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_outcome(tmp_path: Path) -> None:
    p = tmp_path / "outcome.mcap"
    pred = _prediction(stamp=1000, horizon=500)
    original = compute_divergence(
        pred, _pose(x=0.05), pred.predicted_observation_stamp_sim_ns
    )

    with MCAPFileSink(p) as sink:
        PredictionOutcomeToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_PREDICTION_OUTCOMES
    assert msgs[0].log_time_sim_ns == 1500
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, PredictionOutcome)
    assert decoded.verdict == original.verdict
    assert (
        decoded.actual_belief_stamp_sim_ns
        == original.actual_belief_stamp_sim_ns
    )
    assert decoded.position_error_norm_m == pytest.approx(
        original.position_error_norm_m
    )
    assert decoded.position_mahalanobis_max == pytest.approx(
        original.position_mahalanobis_max
    )
    np.testing.assert_array_equal(
        decoded.position_error_enu_m, original.position_error_enu_m
    )


def test_mcap_round_trip_outcome_with_inf_mahalanobis(
    tmp_path: Path,
) -> None:
    """Outcome con Mahalanobis +inf debe round-trip correctamente."""
    p = tmp_path / "inf.mcap"
    pred = BeliefForwardPrediction(
        source_belief_stamp_sim_ns=1000,
        predicted_observation_stamp_sim_ns=1500,
        horizon_ns=500,
        predicted_pose=_pose(),
        predicted_pose_std=PoseStd(
            position_std_enu_m=np.zeros(3, dtype=np.float64),
            orientation_std_rad=np.full(3, 0.1, dtype=np.float64),
        ),
        associated_directive_hash=None,
        predictor_id="constant_velocity_v1",
    )
    original = compute_divergence(
        pred, _pose(x=1.0), pred.predicted_observation_stamp_sim_ns
    )
    assert original.position_mahalanobis_max == float("inf")
    assert original.verdict == DivergenceVerdict.BEYOND_5_STD

    with MCAPFileSink(p) as sink:
        PredictionOutcomeToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    decoded = decode_message(msgs[0])
    assert decoded.position_mahalanobis_max == float("inf")
    assert decoded.verdict == DivergenceVerdict.BEYOND_5_STD


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Mismo outcome publicado en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        pred = _prediction(stamp=1000, horizon=500)
        outcome = compute_divergence(
            pred, _pose(x=0.05), pred.predicted_observation_stamp_sim_ns
        )
        with MCAPFileSink(path) as sink:
            PredictionOutcomeToTelemetryAdapter(sink).publish(outcome)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline: predict → observe → compute_divergence → MCAP
# ---------------------------------------------------------------------------


def test_pipeline_predict_observe_divergence_smoke(
    tmp_path: Path,
) -> None:
    """Pipeline canónico: predicción → observación → outcome → MCAP."""
    p = tmp_path / "pipeline.mcap"
    # 1. Commitment forward
    pred = _prediction(stamp=1000, horizon=500_000_000)
    # 2. Observación llega en el stamp predicho
    actual = _pose(x=0.03)  # 0.15 std x 1 -> within_1_std
    outcome = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    # 3. Persistir
    with MCAPFileSink(p) as sink:
        PredictionOutcomeToTelemetryAdapter(sink).publish(outcome)

    # 4. Read back
    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())
    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, PredictionOutcome)
    assert decoded.verdict == DivergenceVerdict.WITHIN_1_STD
    assert decoded.position_error_norm_m == pytest.approx(0.03)
