"""Tests del ``ActuationToTelemetryAdapter`` y round-trip MCAP
(ADR-0023).

Cubre:

- Adapter publica al canal correcto con timestamp del directive.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- Adapter satisface ``ActuationSink`` estructuralmente.
- MCAP round-trip: write N directives → read → decoded matchea.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end belief → decide → actuate → MCAP.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.actuation import (
    ActuationDirective,
    ActuationSink,
    KillOnlyActuationPolicy,
    actuate_and_publish,
)
from project_ghost.core.decisions import (
    Decision,
    DecisionContext,
    DecisionKind,
    UncertaintyAwareReferencePolicy,
    decide_with_rationale,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    assess_belief,
)
from project_ghost.hal.messages import SensorHealth
from project_ghost.hal.messages.actuators import DirectMotorCommand
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
    CHANNEL_ACTUATIONS,
    ActuationToTelemetryAdapter,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_decision(
    kind: DecisionKind = DecisionKind.ENGAGE_KILL,
    stamp: int = 1000,
    reason: str = "kill_now",
) -> Decision:
    return Decision(
        kind=kind,
        decision_stamp_sim_ns=stamp,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = ActuationToTelemetryAdapter(sink)
    policy = KillOnlyActuationPolicy()
    d = _make_decision()
    directive = policy.actuate(d)
    adapter.publish(directive)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_ACTUATIONS


def test_adapter_uses_directive_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = ActuationToTelemetryAdapter(sink)
    policy = KillOnlyActuationPolicy()
    d = _make_decision(stamp=42_000)
    directive = policy.actuate(d)
    adapter.publish(directive)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_publishes_directive_as_message() -> None:
    sink = InMemorySink()
    adapter = ActuationToTelemetryAdapter(sink)
    policy = KillOnlyActuationPolicy()
    d = _make_decision()
    directive = policy.actuate(d)
    adapter.publish(directive)
    assert sink.captured[0].message is directive


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = ActuationToTelemetryAdapter(sink, channel="/custom/actuations")
    policy = KillOnlyActuationPolicy()
    d = _make_decision()
    directive = policy.actuate(d)
    adapter.publish(directive)
    assert sink.captured[0].channel == "/custom/actuations"
    assert adapter.channel == "/custom/actuations"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        ActuationToTelemetryAdapter(sink, channel="no_slash")


def test_adapter_satisfies_actuation_sink_protocol() -> None:
    sink = InMemorySink()
    adapter = ActuationToTelemetryAdapter(sink)
    assert isinstance(adapter, ActuationSink)


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_kill_directive(tmp_path: Path) -> None:
    p = tmp_path / "kill.mcap"
    policy = KillOnlyActuationPolicy()
    d = _make_decision(kind=DecisionKind.ENGAGE_KILL, stamp=1000)
    original = policy.actuate(d)

    with MCAPFileSink(p) as sink:
        ActuationToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_ACTUATIONS
    assert msgs[0].log_time_sim_ns == 1000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, ActuationDirective)
    # Compare fields explicitly (np.ndarray prevents __eq__).
    assert decoded.decision.kind == original.decision.kind
    assert decoded.decision.reason == original.decision.reason
    assert (
        decoded.decision.decision_stamp_sim_ns
        == original.decision.decision_stamp_sim_ns
    )
    assert decoded.policy_id == original.policy_id
    assert decoded.reason == original.reason
    assert decoded.directive_stamp_sim_ns == original.directive_stamp_sim_ns
    assert isinstance(decoded.actuator_command, DirectMotorCommand)
    np.testing.assert_array_equal(
        decoded.actuator_command.throttle,
        original.actuator_command.throttle,  # type: ignore[union-attr]
    )


def test_mcap_round_trip_directive_with_none_command(tmp_path: Path) -> None:
    """Directive con actuator_command=None debe round-trip correctamente."""
    p = tmp_path / "none.mcap"
    policy = KillOnlyActuationPolicy()
    d = _make_decision(
        kind=DecisionKind.PROCEED, stamp=500, reason="overall_known"
    )
    original = policy.actuate(d)
    assert original.actuator_command is None

    with MCAPFileSink(p) as sink:
        ActuationToTelemetryAdapter(sink).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    decoded = decode_message(msgs[0])
    assert decoded.actuator_command is None
    assert decoded.reason == "no_command_for_proceed"


def test_mcap_round_trip_multiple_directives_mixed(tmp_path: Path) -> None:
    p = tmp_path / "mixed.mcap"
    policy = KillOnlyActuationPolicy()
    kinds_stamps = [
        (DecisionKind.PROCEED, 100),
        (DecisionKind.ENGAGE_KILL, 200),
        (DecisionKind.HOLD, 300),
    ]
    originals: list[ActuationDirective] = []
    with MCAPFileSink(p) as sink:
        adapter = ActuationToTelemetryAdapter(sink)
        for kind, stamp in kinds_stamps:
            d = _make_decision(kind=kind, stamp=stamp, reason="ok")
            directive = policy.actuate(d)
            adapter.publish(directive)
            originals.append(directive)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 3
    for original, msg in zip(originals, msgs, strict=True):
        decoded = decode_message(msg)
        assert decoded.decision.kind == original.decision.kind
        assert decoded.reason == original.reason
        # Only the KILL directive has a command.
        if original.decision.kind == DecisionKind.ENGAGE_KILL:
            assert decoded.actuator_command is not None
        else:
            assert decoded.actuator_command is None


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    """Misma directive publicada en dos MCAPs idénticos → bytes
    idénticos (hereda T4 byte determinism)."""

    def write(path: Path) -> None:
        policy = KillOnlyActuationPolicy()
        d = _make_decision(kind=DecisionKind.ENGAGE_KILL, stamp=1000)
        directive = policy.actuate(d)
        with MCAPFileSink(path) as sink:
            ActuationToTelemetryAdapter(sink).publish(directive)

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline end-to-end: belief → assess → decide → actuate
# ---------------------------------------------------------------------------


def _make_state(stamp: int, pos_var: float = 1e-4) -> VehicleState:
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
        sensors=SensorHealthMap(
            by_id=MappingProxyType({"imu0": SensorHealth.OK})
        ),
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


def test_pipeline_belief_through_actuation_smoke(tmp_path: Path) -> None:
    """Pipeline canónico: belief → assess → decide → actuate → MCAP."""
    p = tmp_path / "pipeline.mcap"
    # 1. belief + assessment
    state = _make_state(stamp=1000)
    thresholds = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    assessment = assess_belief(state, thresholds)
    # 2. decision
    decision_policy = UncertaintyAwareReferencePolicy()
    ctx = DecisionContext(
        belief_stamp_sim_ns=state.stamp_sim_ns,
        self_assessment=assessment,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    decision, _rationale = decide_with_rationale(decision_policy, ctx)
    # 3. actuation
    actuation_policy = KillOnlyActuationPolicy()
    with MCAPFileSink(p) as sink:
        actuate_and_publish(
            actuation_policy,
            decision,
            ActuationToTelemetryAdapter(sink),
        )

    # 4. read back
    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())
    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, ActuationDirective)
    # With covariance KNOWN, the policy decides PROCEED → actuation
    # emits no command.
    assert decoded.decision.kind == DecisionKind.PROCEED
    assert decoded.actuator_command is None
    assert decoded.reason == "no_command_for_proceed"
