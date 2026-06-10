"""Tests del ``SelfAssessmentToTelemetryAdapter`` y round-trip MCAP (ADR-0020).

Cubre:

- Adapter publica en canal correcto con timestamp del assessment.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- MCAP round-trip: write N assessments → read → decode → == originales.
- Determinismo bytes-equal en MCAP capture.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    BeliefSelfAssessment,
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
    CHANNEL_SELF_ASSESSMENT,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    SelfAssessmentToTelemetryAdapter,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(stamp_sim_ns: int) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * 1e-4
    pose = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q_IDENTITY.copy(),
    )
    twist_w = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )
    twist_b = Twist(
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
        twist_world=twist_w,
        twist_body=twist_b,
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=biases,
        covariance_15x15=cov,
    )
    return VehicleState(
        stamp_sim_ns=stamp_sim_ns,
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
    adapter = SelfAssessmentToTelemetryAdapter(sink)
    a = assess_belief(_make_state(stamp_sim_ns=1000), _make_thresholds())
    adapter.publish(a)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_SELF_ASSESSMENT


def test_adapter_uses_belief_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = SelfAssessmentToTelemetryAdapter(sink)
    a = assess_belief(_make_state(stamp_sim_ns=42_000), _make_thresholds())
    adapter.publish(a)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = SelfAssessmentToTelemetryAdapter(sink, channel="/custom/sa")
    a = assess_belief(_make_state(stamp_sim_ns=0), _make_thresholds())
    adapter.publish(a)
    assert sink.captured[0].channel == "/custom/sa"
    assert adapter.channel == "/custom/sa"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        SelfAssessmentToTelemetryAdapter(sink, channel="no_slash")


def test_adapter_forwards_assessment_object_identity() -> None:
    """El adapter pasa el mismo objeto al sink (no copia)."""
    sink = InMemorySink()
    adapter = SelfAssessmentToTelemetryAdapter(sink)
    a = assess_belief(_make_state(stamp_sim_ns=0), _make_thresholds())
    adapter.publish(a)
    assert sink.captured[0].message is a


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_assessment(tmp_path: Path) -> None:
    p = tmp_path / "sa.mcap"
    state = _make_state(stamp_sim_ns=1000)
    thresholds = _make_thresholds()
    original = assess_belief(state, thresholds)

    with MCAPFileSink(p) as sink:
        SelfAssessmentToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_SELF_ASSESSMENT
    assert msgs[0].log_time_sim_ns == 1000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, BeliefSelfAssessment)
    assert decoded == original


def test_mcap_round_trip_multiple_assessments(tmp_path: Path) -> None:
    p = tmp_path / "sa.mcap"
    thresholds = _make_thresholds()
    originals = [assess_belief(_make_state(stamp_sim_ns=i * 1000), thresholds) for i in range(5)]

    with MCAPFileSink(p) as sink:
        adapter = SelfAssessmentToTelemetryAdapter(sink)
        for a in originals:
            adapter.publish(a)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 5
    for original, msg in zip(originals, msgs, strict=True):
        decoded = decode_message(msg)
        assert decoded == original


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Mismo assessment publicado en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        state = _make_state(stamp_sim_ns=1000)
        thresholds = _make_thresholds()
        a = assess_belief(state, thresholds)
        with MCAPFileSink(path) as sink:
            SelfAssessmentToTelemetryAdapter(sink).publish(a)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()
