"""Tests del ``CalibratedSelfAssessmentToTelemetryAdapter`` y round-trip
MCAP (ADR-0026).

Cubre:

- Adapter publica al canal correcto con stamp del belief crudo.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- MCAP round-trip: write calibrated → read → decoded matchea.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end: belief → assess → outcomes → calibrated → MCAP.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.feedback import (
    CalibratedSelfAssessment,
    MahalanobisDowngradePolicy,
    assess_with_feedback,
    build_calibration_history,
)
from project_ghost.core.prediction import (
    BeliefForwardPrediction,
    PoseStd,
    PredictionOutcome,
    compute_divergence,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    SelfAssessmentLevel,
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
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CalibratedSelfAssessmentToTelemetryAdapter,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(stamp: int = 1000, pos_var: float = 1e-4) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * pos_var
    pose = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q.copy(),
    )
    tw = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
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


def _make_outcome(source_stamp: int, error_x: float) -> PredictionOutcome:
    pred = BeliefForwardPrediction(
        source_belief_stamp_sim_ns=source_stamp,
        predicted_observation_stamp_sim_ns=source_stamp + 500,
        horizon_ns=500,
        predicted_pose=Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_Q.copy(),
        ),
        predicted_pose_std=PoseStd(
            position_std_enu_m=np.full(3, 0.2, dtype=np.float64),
            orientation_std_rad=np.full(3, 10.0, dtype=np.float64),
        ),
        associated_directive_hash=None,
        predictor_id="constant_velocity_v1",
    )
    actual = Pose(
        position_enu_m=np.array([error_x, 0.0, 0.0], dtype=np.float64),
        orientation_q=_Q.copy(),
    )
    return compute_divergence(pred, actual, pred.predicted_observation_stamp_sim_ns)


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
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
    raw = assess_belief(_make_state(), _make_thresholds())
    cal = MahalanobisDowngradePolicy().adjust(raw, build_calibration_history([], max_n=32))
    adapter.publish(cal)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_CALIBRATED_SELF_ASSESSMENT


def test_adapter_uses_raw_belief_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
    raw = assess_belief(_make_state(stamp=42_000), _make_thresholds())
    cal = MahalanobisDowngradePolicy().adjust(raw, build_calibration_history([], max_n=32))
    adapter.publish(cal)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_publishes_calibrated_as_message() -> None:
    sink = InMemorySink()
    adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink)
    raw = assess_belief(_make_state(), _make_thresholds())
    cal = MahalanobisDowngradePolicy().adjust(raw, build_calibration_history([], max_n=32))
    adapter.publish(cal)
    assert sink.captured[0].message is cal


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = CalibratedSelfAssessmentToTelemetryAdapter(sink, channel="/custom/calibrated")
    raw = assess_belief(_make_state(), _make_thresholds())
    cal = MahalanobisDowngradePolicy().adjust(raw, build_calibration_history([], max_n=32))
    adapter.publish(cal)
    assert sink.captured[0].channel == "/custom/calibrated"
    assert adapter.channel == "/custom/calibrated"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        CalibratedSelfAssessmentToTelemetryAdapter(sink, channel="no_slash")


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_calibrated_passthrough(tmp_path: Path) -> None:
    p = tmp_path / "cal.mcap"
    raw = assess_belief(_make_state(stamp=1000), _make_thresholds())
    original = MahalanobisDowngradePolicy().adjust(raw, build_calibration_history([], max_n=32))

    with MCAPFileSink(p) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_CALIBRATED_SELF_ASSESSMENT
    assert msgs[0].log_time_sim_ns == 1000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, CalibratedSelfAssessment)
    assert decoded.adjusted_overall_level == original.adjusted_overall_level
    assert decoded.adjustment_policy_id == original.adjustment_policy_id
    assert decoded.adjustment_reason == original.adjustment_reason
    assert decoded.calibration_history.outcomes_considered == 0


def test_mcap_round_trip_calibrated_with_downgrade(tmp_path: Path) -> None:
    p = tmp_path / "cal_down.mcap"
    raw = assess_belief(_make_state(pos_var=1e-4), _make_thresholds())
    assert raw.overall_level == SelfAssessmentLevel.KNOWN
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=2.0),
        _make_outcome(source_stamp=2000, error_x=2.0),
        _make_outcome(source_stamp=3000, error_x=0.0),
        _make_outcome(source_stamp=4000, error_x=0.0),
    ]
    original = assess_with_feedback(raw, outcomes, MahalanobisDowngradePolicy())
    assert original.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN

    with MCAPFileSink(p) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    decoded = decode_message(msgs[0])
    assert decoded.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    assert decoded.adjustment_reason == "downgrade_from_calibration"
    assert decoded.calibration_history.outcomes_considered == 4
    assert decoded.calibration_history.count_beyond_5_std == 2


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Mismo calibrated publicado en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        raw = assess_belief(_make_state(stamp=1000), _make_thresholds())
        outcomes = [
            _make_outcome(source_stamp=1000, error_x=2.0),
            _make_outcome(source_stamp=2000, error_x=2.0),
            _make_outcome(source_stamp=3000, error_x=0.0),
            _make_outcome(source_stamp=4000, error_x=0.0),
        ]
        cal = assess_with_feedback(raw, outcomes, MahalanobisDowngradePolicy())
        with MCAPFileSink(path) as sink:
            CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(cal)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline: belief → assess → outcomes → calibrated → MCAP
# ---------------------------------------------------------------------------


def test_pipeline_closed_loop_smoke(tmp_path: Path) -> None:
    """Pipeline canónico: belief → assess → outcomes → calibrated."""
    p = tmp_path / "closed_loop.mcap"
    state = _make_state(stamp=1000)
    raw = assess_belief(state, _make_thresholds())
    outcomes = [
        _make_outcome(source_stamp=500, error_x=2.0),
        _make_outcome(source_stamp=600, error_x=2.0),
        _make_outcome(source_stamp=700, error_x=2.0),
        _make_outcome(source_stamp=800, error_x=0.0),
        _make_outcome(source_stamp=900, error_x=0.0),
    ]
    policy = MahalanobisDowngradePolicy()
    calibrated = assess_with_feedback(raw, outcomes, policy)

    with MCAPFileSink(p) as sink:
        CalibratedSelfAssessmentToTelemetryAdapter(sink).publish(calibrated)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, CalibratedSelfAssessment)
    # 5 outcomes, 3 beyond_5 (above threshold 2) and outcomes >= 4 → downgrade
    assert decoded.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    assert decoded.adjustment_reason == "downgrade_from_calibration"
