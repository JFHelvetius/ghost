"""Tests del ``DecisionToTelemetryAdapter`` y round-trip MCAP (ADR-0021).

Cubre:

- Adapter publica al canal correcto con timestamp del decision.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- Adapter rechaza (decision, rationale) inconsistentes.
- Adapter satisface DecisionSink Protocol estructural.
- MCAP round-trip: write N rationales → read → decode == originales.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end belief → assessment → policy → MCAP.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.decisions import (
    Decision,
    DecisionContext,
    DecisionKind,
    DecisionRationale,
    DecisionSink,
    UncertaintyAwareReferencePolicy,
    decide_and_publish,
    decide_with_rationale,
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
    CHANNEL_DECISIONS,
    DecisionToTelemetryAdapter,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(*, stamp_sim_ns: int = 1000) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * 1e-4
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


def _make_context(stamp_sim_ns: int = 1000) -> DecisionContext:
    state = _make_state(stamp_sim_ns=stamp_sim_ns)
    thresh = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    return DecisionContext(
        belief_stamp_sim_ns=stamp_sim_ns,
        self_assessment=assess_belief(state, thresh),
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink)
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    decision, rationale = decide_with_rationale(policy, ctx)
    adapter.publish(decision, rationale)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_DECISIONS


def test_adapter_uses_decision_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink)
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(stamp_sim_ns=42_000)
    decision, rationale = decide_with_rationale(policy, ctx)
    adapter.publish(decision, rationale)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_publishes_rationale_as_record() -> None:
    """El record publicado es el ``DecisionRationale`` completo
    (contiene el decision dentro)."""
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink)
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    decision, rationale = decide_with_rationale(policy, ctx)
    adapter.publish(decision, rationale)
    assert sink.captured[0].message is rationale


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink, channel="/custom/decisions")
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    decision, rationale = decide_with_rationale(policy, ctx)
    adapter.publish(decision, rationale)
    assert sink.captured[0].channel == "/custom/decisions"
    assert adapter.channel == "/custom/decisions"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        DecisionToTelemetryAdapter(sink, channel="no_slash")


def test_adapter_rejects_mismatched_decision_in_rationale() -> None:
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink)
    d_a = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    d_b = Decision(
        kind=DecisionKind.HOLD,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    r_for_b = DecisionRationale(
        decision=d_b,
        belief_stamp_sim_ns=0,
        self_assessment_sha256=None,
        policy_id="p",
    )
    with pytest.raises(ValueError, match="must equal decision"):
        adapter.publish(d_a, r_for_b)


def test_adapter_satisfies_decision_sink_protocol() -> None:
    sink = InMemorySink()
    adapter = DecisionToTelemetryAdapter(sink)
    assert isinstance(adapter, DecisionSink)


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_decision(tmp_path: Path) -> None:
    p = tmp_path / "d.mcap"
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(stamp_sim_ns=1000)
    decision, rationale = decide_with_rationale(policy, ctx)

    with MCAPFileSink(p) as sink:
        DecisionToTelemetryAdapter(sink).publish(decision, rationale)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_DECISIONS
    assert msgs[0].log_time_sim_ns == 1000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, DecisionRationale)
    assert decoded == rationale


def test_mcap_round_trip_multiple_decisions(tmp_path: Path) -> None:
    p = tmp_path / "d.mcap"
    policy = UncertaintyAwareReferencePolicy()
    originals = []

    with MCAPFileSink(p) as sink:
        adapter = DecisionToTelemetryAdapter(sink)
        for i in range(5):
            ctx = _make_context(stamp_sim_ns=i * 1000)
            decision, rationale = decide_with_rationale(policy, ctx)
            adapter.publish(decision, rationale)
            originals.append(rationale)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 5
    for original, msg in zip(originals, msgs, strict=True):
        decoded = decode_message(msg)
        assert decoded == original


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Misma decision publicada en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        policy = UncertaintyAwareReferencePolicy()
        ctx = _make_context(stamp_sim_ns=1000)
        decision, rationale = decide_with_rationale(policy, ctx)
        with MCAPFileSink(path) as sink:
            DecisionToTelemetryAdapter(sink).publish(decision, rationale)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline end-to-end
# ---------------------------------------------------------------------------


def test_pipeline_belief_to_decision_via_mcap(tmp_path: Path) -> None:
    """Cadena completa: belief → assessment → policy → decision → MCAP →
    decode. Cierra el ciclo de provenance content-addressed."""
    p = tmp_path / "pipeline.mcap"
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(stamp_sim_ns=2024)

    with MCAPFileSink(p) as sink:
        adapter = DecisionToTelemetryAdapter(sink)
        decide_and_publish(policy, ctx, adapter)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, DecisionRationale)
    # Audit chain verifiable:
    assert decoded.policy_id == policy.policy_id
    assert decoded.belief_stamp_sim_ns == 2024
    assert decoded.decision.decision_stamp_sim_ns == 2024
    # The sha references the assessment we know:
    from project_ghost.core.decisions import self_assessment_sha256

    assert ctx.self_assessment is not None
    expected_sha = self_assessment_sha256(ctx.self_assessment)
    assert decoded.self_assessment_sha256 == expected_sha
