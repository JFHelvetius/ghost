"""Tests del paquete `core.actuation` (ADR-0023).

Cubre:

- ``ActuationDirective`` validación (frozen, stamp consistency,
  taxonomy format, actuator_command type check).
- ``ActuationPolicy`` y ``ActuationSink`` Protocol structural.
- ``NullActuationSink`` / ``RecordingActuationSink`` semantic.
- ``KillOnlyActuationPolicy``: mapping completo sobre los 7
  DecisionKind, determinismo, policy_id estable.
- ``actuate_and_publish`` orquestación.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from project_ghost.core.actuation import (
    ACTION_PROTOCOL_VERSION,
    ActuationDirective,
    ActuationPolicy,
    ActuationSink,
    KillOnlyActuationPolicy,
    NullActuationSink,
    RecordingActuationSink,
    actuate_and_publish,
)
from project_ghost.core.decisions import Decision, DecisionKind
from project_ghost.hal.messages.actuators import (
    AttitudeCommand,
    DirectMotorCommand,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_decision(
    kind: DecisionKind = DecisionKind.PROCEED,
    stamp: int = 1000,
    reason: str = "overall_known",
) -> Decision:
    return Decision(
        kind=kind,
        decision_stamp_sim_ns=stamp,
        reason=reason,
    )


def _make_kill_command() -> DirectMotorCommand:
    return DirectMotorCommand(throttle=np.zeros(4, dtype=np.float64))


def _make_attitude_command() -> AttitudeCommand:
    return AttitudeCommand(
        q_target=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
        thrust_normalized=0.5,
        yaw_rate_rps=0.0,
    )


# ---------------------------------------------------------------------------
# ActuationDirective
# ---------------------------------------------------------------------------


def test_directive_valid_construction_with_command() -> None:
    d = _make_decision(stamp=1000)
    cmd = _make_kill_command()
    directive = ActuationDirective(
        decision=d,
        actuator_command=cmd,
        directive_stamp_sim_ns=1000,
        policy_id="test_policy",
        reason="kill_zero_throttle",
    )
    assert directive.decision is d
    assert directive.actuator_command is cmd
    assert directive.schema_version == ACTION_PROTOCOL_VERSION


def test_directive_valid_construction_with_none_command() -> None:
    """``actuator_command=None`` es legítimo y explícito."""
    d = _make_decision()
    directive = ActuationDirective(
        decision=d,
        actuator_command=None,
        directive_stamp_sim_ns=d.decision_stamp_sim_ns,
        policy_id="test_policy",
        reason="no_command_for_proceed",
    )
    assert directive.actuator_command is None


def test_directive_accepts_attitude_command() -> None:
    d = _make_decision()
    directive = ActuationDirective(
        decision=d,
        actuator_command=_make_attitude_command(),
        directive_stamp_sim_ns=d.decision_stamp_sim_ns,
        policy_id="p",
        reason="ok",
    )
    assert isinstance(directive.actuator_command, AttitudeCommand)


def test_directive_is_frozen() -> None:
    d = _make_decision()
    directive = ActuationDirective(
        decision=d,
        actuator_command=None,
        directive_stamp_sim_ns=d.decision_stamp_sim_ns,
        policy_id="p",
        reason="ok",
    )
    with pytest.raises(FrozenInstanceError):
        directive.policy_id = "x"  # type: ignore[misc]


def test_directive_rejects_non_decision() -> None:
    with pytest.raises(TypeError, match="decision must be Decision"):
        ActuationDirective(
            decision="not a decision",  # type: ignore[arg-type]
            actuator_command=None,
            directive_stamp_sim_ns=0,
            policy_id="p",
            reason="ok",
        )


def test_directive_rejects_negative_stamp() -> None:
    d = _make_decision(stamp=1000)
    with pytest.raises(ValueError, match="directive_stamp_sim_ns must be >= 0"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=-1,
            policy_id="p",
            reason="ok",
        )


def test_directive_rejects_stamp_mismatch() -> None:
    d = _make_decision(stamp=1000)
    with pytest.raises(ValueError, match=r"must equal decision\.decision_stamp"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=2000,
            policy_id="p",
            reason="ok",
        )


def test_directive_rejects_invalid_actuator_command_type() -> None:
    d = _make_decision()
    with pytest.raises(TypeError, match="actuator_command must be"):
        ActuationDirective(
            decision=d,
            actuator_command="not a command",  # type: ignore[arg-type]
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="ok",
        )


def test_directive_rejects_bad_policy_id_format() -> None:
    d = _make_decision()
    with pytest.raises(ValueError, match="policy_id must match"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="Bad Policy",
            reason="ok",
        )


def test_directive_rejects_bad_reason_format() -> None:
    d = _make_decision()
    with pytest.raises(ValueError, match="reason must match"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="CamelCase",
        )


def test_directive_rejects_empty_reason() -> None:
    d = _make_decision()
    with pytest.raises(ValueError, match="reason cannot be empty"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="",
        )


def test_directive_rejects_too_long_reason() -> None:
    d = _make_decision()
    with pytest.raises(ValueError, match="<= 64"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="a" * 65,
        )


def test_directive_rejects_non_string_policy_id() -> None:
    d = _make_decision()
    with pytest.raises(TypeError, match="policy_id must be str"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id=42,  # type: ignore[arg-type]
            reason="ok",
        )


def test_directive_rejects_wrong_schema_version() -> None:
    d = _make_decision()
    with pytest.raises(ValueError, match="schema_version"):
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="ok",
            schema_version=999,
        )


# ---------------------------------------------------------------------------
# Protocols structural
# ---------------------------------------------------------------------------


def test_kill_only_policy_satisfies_actuation_policy_protocol() -> None:
    policy = KillOnlyActuationPolicy()
    assert isinstance(policy, ActuationPolicy)


def test_null_sink_satisfies_actuation_sink_protocol() -> None:
    sink = NullActuationSink()
    assert isinstance(sink, ActuationSink)


def test_recording_sink_satisfies_actuation_sink_protocol() -> None:
    sink = RecordingActuationSink()
    assert isinstance(sink, ActuationSink)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


def test_null_sink_discards_silently() -> None:
    sink = NullActuationSink()
    d = _make_decision()
    directive = ActuationDirective(
        decision=d,
        actuator_command=None,
        directive_stamp_sim_ns=d.decision_stamp_sim_ns,
        policy_id="p",
        reason="ok",
    )
    sink.publish(directive)  # no error


def test_recording_sink_keeps_directives_in_order() -> None:
    sink = RecordingActuationSink()
    d1 = _make_decision(stamp=100)
    d2 = _make_decision(stamp=200)
    dv1 = ActuationDirective(
        decision=d1,
        actuator_command=None,
        directive_stamp_sim_ns=100,
        policy_id="p",
        reason="ok",
    )
    dv2 = ActuationDirective(
        decision=d2,
        actuator_command=None,
        directive_stamp_sim_ns=200,
        policy_id="p",
        reason="ok",
    )
    sink.publish(dv1)
    sink.publish(dv2)
    records = sink.records
    assert len(records) == 2
    assert records[0] is dv1
    assert records[1] is dv2


def test_recording_sink_clear_empties() -> None:
    sink = RecordingActuationSink()
    d = _make_decision()
    sink.publish(
        ActuationDirective(
            decision=d,
            actuator_command=None,
            directive_stamp_sim_ns=d.decision_stamp_sim_ns,
            policy_id="p",
            reason="ok",
        )
    )
    sink.clear()
    assert sink.records == ()


# ---------------------------------------------------------------------------
# KillOnlyActuationPolicy
# ---------------------------------------------------------------------------


def test_kill_only_policy_has_stable_id() -> None:
    policy = KillOnlyActuationPolicy()
    assert policy.policy_id == "kill_only_v1"


def test_kill_only_policy_emits_zero_throttle_for_engage_kill() -> None:
    policy = KillOnlyActuationPolicy()
    d = _make_decision(kind=DecisionKind.ENGAGE_KILL, reason="kill_now")
    directive = policy.actuate(d)
    assert directive.actuator_command is not None
    assert isinstance(directive.actuator_command, DirectMotorCommand)
    np.testing.assert_array_equal(
        directive.actuator_command.throttle,
        np.zeros(4, dtype=np.float64),
    )
    assert directive.reason == "kill_zero_throttle"
    assert directive.policy_id == "kill_only_v1"


@pytest.mark.parametrize(
    "kind",
    [
        DecisionKind.PROCEED,
        DecisionKind.HOLD,
        DecisionKind.YIELD_TO_PILOT,
        DecisionKind.ENGAGE_RTL,
        DecisionKind.ENGAGE_LAND,
        DecisionKind.ABSTAIN_UNCERTAIN,
    ],
)
def test_kill_only_policy_emits_none_for_non_kill(kind: DecisionKind) -> None:
    """Cualquier kind distinto de ENGAGE_KILL produce actuator_command=None
    con reason 'no_command_for_<kind>'."""
    policy = KillOnlyActuationPolicy()
    d = Decision(
        kind=kind,
        decision_stamp_sim_ns=500,
        reason="ok",
    )
    directive = policy.actuate(d)
    assert directive.actuator_command is None
    assert directive.reason == f"no_command_for_{kind.value}"
    assert directive.policy_id == "kill_only_v1"


def test_kill_only_policy_preserves_decision_stamp() -> None:
    policy = KillOnlyActuationPolicy()
    d = _make_decision(stamp=42_000)
    directive = policy.actuate(d)
    assert directive.directive_stamp_sim_ns == 42_000


def test_kill_only_policy_preserves_decision_reference() -> None:
    policy = KillOnlyActuationPolicy()
    d = _make_decision()
    directive = policy.actuate(d)
    assert directive.decision is d


def test_kill_only_policy_is_deterministic() -> None:
    policy = KillOnlyActuationPolicy()
    d_kill = _make_decision(kind=DecisionKind.ENGAGE_KILL, reason="k")
    a = policy.actuate(d_kill)
    b = policy.actuate(d_kill)
    # Compare all fields except actuator_command (np.array compares
    # element-wise). The decision and metadata must match exactly.
    assert a.decision is b.decision
    assert a.policy_id == b.policy_id
    assert a.reason == b.reason
    assert a.directive_stamp_sim_ns == b.directive_stamp_sim_ns
    assert isinstance(a.actuator_command, DirectMotorCommand)
    assert isinstance(b.actuator_command, DirectMotorCommand)
    np.testing.assert_array_equal(
        a.actuator_command.throttle,
        b.actuator_command.throttle,
    )


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def test_actuate_and_publish_records_to_sink() -> None:
    policy = KillOnlyActuationPolicy()
    sink = RecordingActuationSink()
    d = _make_decision(kind=DecisionKind.ENGAGE_KILL, reason="kill")
    returned = actuate_and_publish(policy, d, sink)
    assert len(sink.records) == 1
    assert sink.records[0] is returned
    assert returned.policy_id == policy.policy_id


def test_actuate_and_publish_returns_directive() -> None:
    policy = KillOnlyActuationPolicy()
    sink = NullActuationSink()
    d = _make_decision()
    returned = actuate_and_publish(policy, d, sink)
    assert isinstance(returned, ActuationDirective)


def test_actuate_and_publish_with_null_sink_smoke() -> None:
    policy = KillOnlyActuationPolicy()
    sink = NullActuationSink()
    d = _make_decision(kind=DecisionKind.PROCEED)
    directive = actuate_and_publish(policy, d, sink)
    # PROCEED → None command
    assert directive.actuator_command is None


def test_actuate_and_publish_with_multiple_decisions() -> None:
    policy = KillOnlyActuationPolicy()
    sink = RecordingActuationSink()
    decisions = [
        _make_decision(kind=DecisionKind.PROCEED, stamp=100, reason="ok"),
        _make_decision(kind=DecisionKind.ENGAGE_KILL, stamp=200, reason="kill"),
        _make_decision(kind=DecisionKind.HOLD, stamp=300, reason="ok"),
    ]
    for d in decisions:
        actuate_and_publish(policy, d, sink)
    records = sink.records
    assert len(records) == 3
    # First and third: no command
    assert records[0].actuator_command is None
    assert records[2].actuator_command is None
    # Second: zero throttle
    second_cmd = records[1].actuator_command
    assert isinstance(second_cmd, DirectMotorCommand)
    np.testing.assert_array_equal(
        second_cmd.throttle,
        np.zeros(4, dtype=np.float64),
    )
