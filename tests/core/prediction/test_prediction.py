"""Tests del contrato de forward-prediction (ADR-0024).

Cubre:

- ``PoseStd`` validación de shape/dtype/non-negativity.
- ``BeliefForwardPrediction`` validación de stamps, horizon, taxonomy
  y hash format.
- ``ForwardPredictor`` y ``ForwardPredictionSink`` Protocol estructural.
- ``NullForwardPredictionSink`` y
  ``RecordingForwardPredictionSink`` semántica.
- ``ConstantVelocityForwardPredictor``: pure function, propagación
  posicional, std derivado de covariance, fallback sin covariance,
  link a directive_hash.
- ``forward_predict_and_publish`` orquestación.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.core.prediction import (
    PREDICTION_PROTOCOL_VERSION,
    BeliefForwardPrediction,
    ConstantVelocityForwardPredictor,
    ForwardPredictionSink,
    ForwardPredictor,
    NullForwardPredictionSink,
    PoseStd,
    RecordingForwardPredictionSink,
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
from project_ghost.telemetry import encode_to_bytes

_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
_VALID_HASH = "a" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pose(x: float = 0.0) -> Pose:
    return Pose(
        position_enu_m=np.array([x, 0.0, 0.0], dtype=np.float64),
        orientation_q=_Q.copy(),
    )


def _make_pose_std() -> PoseStd:
    return PoseStd(
        position_std_enu_m=np.zeros(3, dtype=np.float64),
        orientation_std_rad=np.zeros(3, dtype=np.float64),
    )


def _make_state(
    *,
    stamp: int = 1000,
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
    cov: np.ndarray | None = None,
) -> VehicleState:
    pose = _make_pose()
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


def _make_prediction(
    *,
    source_stamp: int = 1000,
    horizon: int = 500,
    directive_hash: str | None = None,
) -> BeliefForwardPrediction:
    return BeliefForwardPrediction(
        source_belief_stamp_sim_ns=source_stamp,
        predicted_observation_stamp_sim_ns=source_stamp + horizon,
        horizon_ns=horizon,
        predicted_pose=_make_pose(),
        predicted_pose_std=_make_pose_std(),
        associated_directive_hash=directive_hash,
        predictor_id="constant_velocity_v1",
    )


# ---------------------------------------------------------------------------
# PoseStd
# ---------------------------------------------------------------------------


def test_pose_std_accepts_zero_components() -> None:
    s = PoseStd(
        position_std_enu_m=np.zeros(3, dtype=np.float64),
        orientation_std_rad=np.zeros(3, dtype=np.float64),
    )
    assert s.position_std_enu_m.shape == (3,)


def test_pose_std_accepts_positive_components() -> None:
    s = PoseStd(
        position_std_enu_m=np.array([0.1, 0.2, 0.3], dtype=np.float64),
        orientation_std_rad=np.array([0.05, 0.05, 0.05], dtype=np.float64),
    )
    assert float(s.position_std_enu_m[0]) == pytest.approx(0.1)


def test_pose_std_rejects_negative_position() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        PoseStd(
            position_std_enu_m=np.array([-0.1, 0.0, 0.0], dtype=np.float64),
            orientation_std_rad=np.zeros(3, dtype=np.float64),
        )


def test_pose_std_rejects_negative_orientation() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        PoseStd(
            position_std_enu_m=np.zeros(3, dtype=np.float64),
            orientation_std_rad=np.array([0.0, -0.1, 0.0], dtype=np.float64),
        )


def test_pose_std_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match=r"must have shape \(3,\)"):
        PoseStd(
            position_std_enu_m=np.zeros(4, dtype=np.float64),
            orientation_std_rad=np.zeros(3, dtype=np.float64),
        )


def test_pose_std_rejects_wrong_dtype() -> None:
    with pytest.raises(ValueError, match="must have dtype float64"):
        PoseStd(
            position_std_enu_m=np.zeros(3, dtype=np.float32),
            orientation_std_rad=np.zeros(3, dtype=np.float64),
        )


def test_pose_std_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        PoseStd(
            position_std_enu_m=np.array([np.inf, 0.0, 0.0], dtype=np.float64),
            orientation_std_rad=np.zeros(3, dtype=np.float64),
        )


def test_pose_std_rejects_non_ndarray() -> None:
    with pytest.raises(TypeError, match=r"must be np\.ndarray"):
        PoseStd(
            position_std_enu_m=[0.0, 0.0, 0.0],  # type: ignore[arg-type]
            orientation_std_rad=np.zeros(3, dtype=np.float64),
        )


def test_pose_std_arrays_are_read_only() -> None:
    s = _make_pose_std()
    with pytest.raises(ValueError, match=r"read-only|assignment destination"):
        s.position_std_enu_m[0] = 1.0


# ---------------------------------------------------------------------------
# BeliefForwardPrediction
# ---------------------------------------------------------------------------


def test_prediction_accepts_minimal_fields() -> None:
    p = _make_prediction()
    assert p.source_belief_stamp_sim_ns == 1000
    assert p.predicted_observation_stamp_sim_ns == 1500
    assert p.horizon_ns == 500
    assert p.predictor_id == "constant_velocity_v1"
    assert p.schema_version == PREDICTION_PROTOCOL_VERSION
    assert p.associated_directive_hash is None


def test_prediction_accepts_directive_hash() -> None:
    p = _make_prediction(directive_hash=_VALID_HASH)
    assert p.associated_directive_hash == _VALID_HASH


def test_prediction_rejects_negative_source_stamp() -> None:
    with pytest.raises(ValueError, match="source_belief_stamp_sim_ns must be >= 0"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=-1,
            predicted_observation_stamp_sim_ns=499,
            horizon_ns=500,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_zero_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_ns must be > 0"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=1000,
            horizon_ns=0,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_negative_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_ns must be > 0"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=900,
            horizon_ns=-100,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_inconsistent_observation_stamp() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"predicted_observation_stamp_sim_ns .* must equal "
            r"source_belief_stamp_sim_ns \+ horizon_ns"
        ),
    ):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=2000,
            horizon_ns=500,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_wrong_predicted_pose_type() -> None:
    with pytest.raises(TypeError, match="predicted_pose must be Pose"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=1500,
            horizon_ns=500,
            predicted_pose="not a pose",  # type: ignore[arg-type]
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_wrong_predicted_std_type() -> None:
    with pytest.raises(TypeError, match="predicted_pose_std must be PoseStd"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=1500,
            horizon_ns=500,
            predicted_pose=_make_pose(),
            predicted_pose_std="not a std",  # type: ignore[arg-type]
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
        )


def test_prediction_rejects_short_directive_hash() -> None:
    with pytest.raises(ValueError, match="associated_directive_hash must be 64 hex chars"):
        _make_prediction(directive_hash="abc")


def test_prediction_rejects_uppercase_directive_hash() -> None:
    with pytest.raises(ValueError, match="associated_directive_hash must be lowercase hex"):
        _make_prediction(directive_hash="A" * 64)


def test_prediction_rejects_non_hex_directive_hash() -> None:
    with pytest.raises(ValueError, match="associated_directive_hash must be lowercase hex"):
        _make_prediction(directive_hash="g" * 64)


@pytest.mark.parametrize(
    "bad_id",
    ["", "Constant", "1bad", "has space", "a" * 65, "with-dash"],
)
def test_prediction_rejects_bad_predictor_id(bad_id: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=1500,
            horizon_ns=500,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id=bad_id,
        )


def test_prediction_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be 1"):
        BeliefForwardPrediction(
            source_belief_stamp_sim_ns=1000,
            predicted_observation_stamp_sim_ns=1500,
            horizon_ns=500,
            predicted_pose=_make_pose(),
            predicted_pose_std=_make_pose_std(),
            associated_directive_hash=None,
            predictor_id="constant_velocity_v1",
            schema_version=99,
        )


def test_prediction_is_frozen() -> None:
    p = _make_prediction()
    with pytest.raises(AttributeError):
        p.horizon_ns = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


def test_constant_velocity_predictor_satisfies_protocol() -> None:
    assert isinstance(ConstantVelocityForwardPredictor(), ForwardPredictor)


def test_null_sink_satisfies_protocol() -> None:
    assert isinstance(NullForwardPredictionSink(), ForwardPredictionSink)


def test_recording_sink_satisfies_protocol() -> None:
    assert isinstance(RecordingForwardPredictionSink(), ForwardPredictionSink)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


def test_null_sink_swallows_publish() -> None:
    NullForwardPredictionSink().publish(_make_prediction())


def test_recording_sink_captures_in_order() -> None:
    sink = RecordingForwardPredictionSink()
    p1 = _make_prediction(source_stamp=1000)
    p2 = _make_prediction(source_stamp=2000)
    sink.publish(p1)
    sink.publish(p2)
    assert sink.records == (p1, p2)


def test_recording_sink_records_is_tuple_snapshot() -> None:
    sink = RecordingForwardPredictionSink()
    sink.publish(_make_prediction())
    snap = sink.records
    sink.publish(_make_prediction(source_stamp=2000))
    assert len(snap) == 1


def test_recording_sink_clear_empties() -> None:
    sink = RecordingForwardPredictionSink()
    sink.publish(_make_prediction())
    sink.clear()
    assert sink.records == ()


# ---------------------------------------------------------------------------
# ConstantVelocityForwardPredictor
# ---------------------------------------------------------------------------


def test_constant_velocity_predictor_id() -> None:
    assert ConstantVelocityForwardPredictor().predictor_id == "constant_velocity_v1"


def test_constant_velocity_predicts_stationary_from_zero_velocity() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, velocity=(0.0, 0.0, 0.0))
    p = predictor.predict(state, horizon_ns=1_000_000_000)
    np.testing.assert_array_equal(p.predicted_pose.position_enu_m, np.zeros(3, dtype=np.float64))


def test_constant_velocity_propagates_position_with_velocity() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, velocity=(2.0, 0.0, 0.0))
    # horizon 1s → expect 2m displacement in x
    p = predictor.predict(state, horizon_ns=1_000_000_000)
    np.testing.assert_allclose(
        p.predicted_pose.position_enu_m,
        np.array([2.0, 0.0, 0.0], dtype=np.float64),
    )


def test_constant_velocity_keeps_orientation_constant() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, velocity=(5.0, 0.0, 0.0))
    p = predictor.predict(state, horizon_ns=500_000_000)
    np.testing.assert_array_equal(
        p.predicted_pose.orientation_q,
        state.nav.pose.orientation_q,
    )


def test_constant_velocity_stamps_are_consistent() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=12_345)
    p = predictor.predict(state, horizon_ns=999)
    assert p.source_belief_stamp_sim_ns == 12_345
    assert p.predicted_observation_stamp_sim_ns == 12_345 + 999
    assert p.horizon_ns == 999


def test_constant_velocity_uses_covariance_for_std_when_present() -> None:
    predictor = ConstantVelocityForwardPredictor()
    cov = np.zeros((15, 15), dtype=np.float64)
    # Position block diag: vars (0.04, 0.09, 0.16) → std (0.2, 0.3, 0.4)
    cov[0, 0] = 0.04
    cov[1, 1] = 0.09
    cov[2, 2] = 0.16
    # Orientation tangent block diag (6:9, 6:9): vars (0.01, 0.04, 0.09)
    cov[6, 6] = 0.01
    cov[7, 7] = 0.04
    cov[8, 8] = 0.09
    state = _make_state(stamp=1000, cov=cov)
    p = predictor.predict(state, horizon_ns=1_000_000_000)
    np.testing.assert_allclose(
        p.predicted_pose_std.position_std_enu_m,
        np.array([0.2, 0.3, 0.4], dtype=np.float64),
    )
    np.testing.assert_allclose(
        p.predicted_pose_std.orientation_std_rad,
        np.array([0.1, 0.2, 0.3], dtype=np.float64),
    )


def test_constant_velocity_falls_back_when_no_covariance() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, cov=None)
    p = predictor.predict(state, horizon_ns=1_000_000_000)
    np.testing.assert_array_equal(
        p.predicted_pose_std.position_std_enu_m,
        np.full(3, 1.0, dtype=np.float64),
    )
    np.testing.assert_array_equal(
        p.predicted_pose_std.orientation_std_rad,
        np.full(3, 1.0, dtype=np.float64),
    )


def test_constant_velocity_carries_directive_hash() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    p = predictor.predict(state, horizon_ns=500, directive_hash=_VALID_HASH)
    assert p.associated_directive_hash == _VALID_HASH


def test_constant_velocity_pure_function() -> None:
    """Same input → same output (byte-equal via to_json_safe)."""
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000, velocity=(1.0, 2.0, 3.0))
    p1 = predictor.predict(state, horizon_ns=500_000_000)
    p2 = predictor.predict(state, horizon_ns=500_000_000)
    assert encode_to_bytes(p1) == encode_to_bytes(p2)


def test_constant_velocity_rejects_zero_horizon() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    with pytest.raises(ValueError, match="horizon_ns must be > 0"):
        predictor.predict(state, horizon_ns=0)


def test_constant_velocity_rejects_negative_horizon() -> None:
    predictor = ConstantVelocityForwardPredictor()
    state = _make_state(stamp=1000)
    with pytest.raises(ValueError, match="horizon_ns must be > 0"):
        predictor.predict(state, horizon_ns=-100)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_forward_predict_and_publish_records_to_sink() -> None:
    predictor = ConstantVelocityForwardPredictor()
    sink = RecordingForwardPredictionSink()
    state = _make_state(stamp=1000)
    p = forward_predict_and_publish(predictor, state, 500, sink)
    assert sink.records == (p,)


def test_forward_predict_and_publish_returns_record() -> None:
    predictor = ConstantVelocityForwardPredictor()
    sink = NullForwardPredictionSink()
    state = _make_state(stamp=2000)
    p = forward_predict_and_publish(predictor, state, 1000, sink)
    assert isinstance(p, BeliefForwardPrediction)
    assert p.source_belief_stamp_sim_ns == 2000


def test_forward_predict_and_publish_forwards_directive_hash() -> None:
    predictor = ConstantVelocityForwardPredictor()
    sink = RecordingForwardPredictionSink()
    state = _make_state(stamp=1000)
    p = forward_predict_and_publish(predictor, state, 500, sink, directive_hash=_VALID_HASH)
    assert p.associated_directive_hash == _VALID_HASH
