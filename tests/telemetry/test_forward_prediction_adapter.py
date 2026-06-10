"""Tests del ``ForwardPredictionToTelemetryAdapter`` y round-trip MCAP
(ADR-0024).

Cubre:

- Adapter publica al canal correcto con stamp del belief origen.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- Adapter satisface ``ForwardPredictionSink`` estructuralmente.
- MCAP round-trip: write predicción → read → decoded matchea.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end belief → predict → MCAP → decode.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.prediction import (
    BeliefForwardPrediction,
    ConstantVelocityForwardPredictor,
    ForwardPredictionSink,
    forward_predict_and_publish,
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
    CHANNEL_FORWARD_PREDICTIONS,
    ForwardPredictionToTelemetryAdapter,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
_VALID_HASH = "a" * 64


def _make_state(
    stamp: int = 1000, velocity: tuple[float, float, float] = (1.0, 0.0, 0.0)
) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * 1e-4
    pose = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q.copy(),
    )
    tw = Twist(
        linear_mps=np.array(velocity, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )
    tb = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="body",
    )
    biases = IMUBiases(
        accel_bias_mps2=np.zeros(3, dtype=np.float64),
        gyro_bias_rps=np.zeros(3, dtype=np.float64),
    )
    nav = NavigationState(
        pose=pose,
        twist_world=tw,
        twist_body=tb,
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=biases,
        covariance_15x15=cov,
    )
    return VehicleState(
        stamp_sim_ns=stamp,
        stamp_wall_ns=0,
        nav=nav,
        sensors=SensorHealthMap(by_id=MappingProxyType({"imu0": SensorHealth.OK})),
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


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = ForwardPredictionToTelemetryAdapter(sink)
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    prediction = predictor.predict(state, horizon_ns=500)
    adapter.publish(prediction)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_FORWARD_PREDICTIONS


def test_adapter_uses_source_belief_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = ForwardPredictionToTelemetryAdapter(sink)
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=42_000)
    prediction = predictor.predict(state, horizon_ns=500)
    adapter.publish(prediction)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_publishes_prediction_as_message() -> None:
    sink = InMemorySink()
    adapter = ForwardPredictionToTelemetryAdapter(sink)
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    prediction = predictor.predict(state, horizon_ns=500)
    adapter.publish(prediction)
    assert sink.captured[0].message is prediction


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = ForwardPredictionToTelemetryAdapter(sink, channel="/custom/predictions")
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    prediction = predictor.predict(state, horizon_ns=500)
    adapter.publish(prediction)
    assert sink.captured[0].channel == "/custom/predictions"
    assert adapter.channel == "/custom/predictions"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        ForwardPredictionToTelemetryAdapter(sink, channel="no_slash")


def test_adapter_satisfies_forward_prediction_sink_protocol() -> None:
    sink = InMemorySink()
    adapter = ForwardPredictionToTelemetryAdapter(sink)
    assert isinstance(adapter, ForwardPredictionSink)


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_prediction(tmp_path: Path) -> None:
    p = tmp_path / "pred.mcap"
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, velocity=(2.0, 0.0, 0.0))
    original = predictor.predict(state, horizon_ns=500_000_000)

    with MCAPFileSink(p) as sink:
        ForwardPredictionToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_FORWARD_PREDICTIONS
    assert msgs[0].log_time_sim_ns == 1000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, BeliefForwardPrediction)
    assert decoded.source_belief_stamp_sim_ns == 1000
    assert decoded.predicted_observation_stamp_sim_ns == 1000 + 500_000_000
    assert decoded.horizon_ns == 500_000_000
    assert decoded.predictor_id == "constant_velocity_v1"
    assert decoded.associated_directive_hash is None
    np.testing.assert_array_equal(
        decoded.predicted_pose.position_enu_m,
        original.predicted_pose.position_enu_m,
    )
    np.testing.assert_array_equal(
        decoded.predicted_pose.orientation_q,
        original.predicted_pose.orientation_q,
    )
    np.testing.assert_array_equal(
        decoded.predicted_pose_std.position_std_enu_m,
        original.predicted_pose_std.position_std_enu_m,
    )


def test_mcap_round_trip_prediction_with_directive_hash(
    tmp_path: Path,
) -> None:
    p = tmp_path / "linked.mcap"
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=2000)
    original = predictor.predict(state, horizon_ns=1000, directive_hash=_VALID_HASH)

    with MCAPFileSink(p) as sink:
        ForwardPredictionToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    decoded = decode_message(msgs[0])
    assert decoded.associated_directive_hash == _VALID_HASH


def test_mcap_round_trip_multiple_predictions(tmp_path: Path) -> None:
    p = tmp_path / "multi.mcap"
    predictor = ConstantVelocityForwardPredictor()
    stamps = [100, 200, 300, 400]
    originals: list[BeliefForwardPrediction] = []
    with MCAPFileSink(p) as sink:
        adapter = ForwardPredictionToTelemetryAdapter(sink)
        for stamp in stamps:
            state = _make_state(stamp=stamp)
            prediction = predictor.predict(state, horizon_ns=50)
            adapter.publish(prediction)
            originals.append(prediction)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == len(stamps)
    for original, msg in zip(originals, msgs, strict=True):
        decoded = decode_message(msg)
        assert decoded.source_belief_stamp_sim_ns == original.source_belief_stamp_sim_ns
        assert decoded.horizon_ns == original.horizon_ns


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Misma predicción publicada en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        predictor = ConstantVelocityForwardPredictor()
        state = _make_state(stamp=1000, velocity=(1.0, 2.0, 3.0))
        prediction = predictor.predict(state, horizon_ns=500_000_000)
        with MCAPFileSink(path) as sink:
            ForwardPredictionToTelemetryAdapter(sink).publish(prediction)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline end-to-end: belief → forward-predict → MCAP → decode
# ---------------------------------------------------------------------------


def test_pipeline_belief_through_forward_prediction_smoke(
    tmp_path: Path,
) -> None:
    """Pipeline canónico: belief → forward-predict → MCAP."""
    p = tmp_path / "pipeline.mcap"
    state = _make_state(stamp=1000, velocity=(1.0, 0.0, 0.0))
    predictor = ConstantVelocityForwardPredictor()
    with MCAPFileSink(p) as sink:
        adapter = ForwardPredictionToTelemetryAdapter(sink)
        forward_predict_and_publish(predictor, state, 1_000_000_000, adapter)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, BeliefForwardPrediction)
    # 1s con velocidad x=1 → posición x ≈ 1
    np.testing.assert_allclose(
        decoded.predicted_pose.position_enu_m,
        np.array([1.0, 0.0, 0.0], dtype=np.float64),
    )
    assert decoded.predictor_id == "constant_velocity_v1"
