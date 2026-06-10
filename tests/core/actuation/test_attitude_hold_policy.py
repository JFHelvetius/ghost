"""Tests del ``AttitudeHoldReferencePolicy`` (ADR-0029).

Cubre:

- Construcción: parámetros válidos e inválidos.
- ``PROCEED`` → ``AttitudeCommand`` con thrust configurado.
- ``HOLD`` → ``AttitudeCommand`` con thrust configurado.
- ``ENGAGE_KILL`` → ``DirectMotorCommand`` zero throttle.
- Otros kinds → ``None``.
- Stamp sincronismo: ``directive_stamp_sim_ns == decision_stamp_sim_ns``.
- Identidad del ``policy_id`` en el directive.
- Protocol compliance (``ActuationPolicy``).
- Quaternion target es identidad.
- Determinismo: misma decisión → mismo result encode byte-equal.
"""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.core.actuation import (
    ActuationPolicy,
    AttitudeHoldReferencePolicy,
)
from project_ghost.core.decisions.types import Decision, DecisionKind
from project_ghost.hal.messages.actuators import (
    AttitudeCommand,
    DirectMotorCommand,
)
from project_ghost.telemetry import encode_to_bytes


def _make_decision(kind: DecisionKind, stamp: int = 1000) -> Decision:
    return Decision(
        kind=kind,
        decision_stamp_sim_ns=stamp,
        reason=kind.value,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_construction() -> None:
    p = AttitudeHoldReferencePolicy()
    assert p.proceed_thrust == 0.5
    assert p.hold_thrust == 0.5
    assert p.policy_id == "attitude_hold_v1"


def test_custom_thrust_parameters() -> None:
    p = AttitudeHoldReferencePolicy(proceed_thrust=0.6, hold_thrust=0.4)
    assert p.proceed_thrust == 0.6
    assert p.hold_thrust == 0.4


def test_rejects_proceed_thrust_above_one() -> None:
    with pytest.raises(ValueError, match="proceed_thrust"):
        AttitudeHoldReferencePolicy(proceed_thrust=1.1)


def test_rejects_proceed_thrust_below_zero() -> None:
    with pytest.raises(ValueError, match="proceed_thrust"):
        AttitudeHoldReferencePolicy(proceed_thrust=-0.1)


def test_rejects_hold_thrust_above_one() -> None:
    with pytest.raises(ValueError, match="hold_thrust"):
        AttitudeHoldReferencePolicy(hold_thrust=1.5)


def test_accepts_boundary_thrust_values() -> None:
    p0 = AttitudeHoldReferencePolicy(proceed_thrust=0.0, hold_thrust=0.0)
    assert p0.proceed_thrust == 0.0
    p1 = AttitudeHoldReferencePolicy(proceed_thrust=1.0, hold_thrust=1.0)
    assert p1.proceed_thrust == 1.0


def test_rejects_nan_thrust() -> None:
    with pytest.raises(ValueError, match="proceed_thrust"):
        AttitudeHoldReferencePolicy(proceed_thrust=float("nan"))


# ---------------------------------------------------------------------------
# PROCEED mapping
# ---------------------------------------------------------------------------


def test_proceed_produces_attitude_command() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.PROCEED))
    assert isinstance(directive.actuator_command, AttitudeCommand)


def test_proceed_thrust_matches_parameter() -> None:
    p = AttitudeHoldReferencePolicy(proceed_thrust=0.7)
    directive = p.actuate(_make_decision(DecisionKind.PROCEED))
    assert isinstance(directive.actuator_command, AttitudeCommand)
    assert directive.actuator_command.thrust_normalized == pytest.approx(0.7)


def test_proceed_quaternion_is_identity() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.PROCEED))
    assert isinstance(directive.actuator_command, AttitudeCommand)
    np.testing.assert_array_equal(
        directive.actuator_command.q_target,
        np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
    )


def test_proceed_reason() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.PROCEED))
    assert directive.reason == "attitude_hold_proceed"


# ---------------------------------------------------------------------------
# HOLD mapping
# ---------------------------------------------------------------------------


def test_hold_produces_attitude_command() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.HOLD))
    assert isinstance(directive.actuator_command, AttitudeCommand)


def test_hold_thrust_matches_parameter() -> None:
    p = AttitudeHoldReferencePolicy(hold_thrust=0.3)
    directive = p.actuate(_make_decision(DecisionKind.HOLD))
    assert isinstance(directive.actuator_command, AttitudeCommand)
    assert directive.actuator_command.thrust_normalized == pytest.approx(0.3)


def test_hold_reason() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.HOLD))
    assert directive.reason == "attitude_hold_hold"


# ---------------------------------------------------------------------------
# ENGAGE_KILL mapping
# ---------------------------------------------------------------------------


def test_kill_produces_direct_motor_command() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_KILL))
    assert isinstance(directive.actuator_command, DirectMotorCommand)


def test_kill_motor_throttle_is_zero() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_KILL))
    assert isinstance(directive.actuator_command, DirectMotorCommand)
    np.testing.assert_array_equal(
        directive.actuator_command.throttle,
        np.zeros(4, dtype=np.float64),
    )


def test_kill_reason() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_KILL))
    assert directive.reason == "kill_zero_throttle"


# ---------------------------------------------------------------------------
# Other kinds → None
# ---------------------------------------------------------------------------


def test_rtl_produces_none_command() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_RTL))
    assert directive.actuator_command is None


def test_land_produces_none_command() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_LAND))
    assert directive.actuator_command is None


def test_no_command_reason_includes_kind() -> None:
    p = AttitudeHoldReferencePolicy()
    directive = p.actuate(_make_decision(DecisionKind.ENGAGE_RTL))
    assert directive.reason.startswith("no_command_for_")
    assert "engage_rtl" in directive.reason


# ---------------------------------------------------------------------------
# Stamp and policy_id invariants
# ---------------------------------------------------------------------------


def test_directive_stamp_equals_decision_stamp() -> None:
    p = AttitudeHoldReferencePolicy()
    for kind in (
        DecisionKind.PROCEED,
        DecisionKind.HOLD,
        DecisionKind.ENGAGE_KILL,
        DecisionKind.ENGAGE_RTL,
    ):
        d = _make_decision(kind, stamp=99_000)
        directive = p.actuate(d)
        assert directive.directive_stamp_sim_ns == 99_000


def test_directive_policy_id_matches_policy() -> None:
    p = AttitudeHoldReferencePolicy()
    for kind in (DecisionKind.PROCEED, DecisionKind.HOLD):
        directive = p.actuate(_make_decision(kind))
        assert directive.policy_id == p.policy_id


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_satisfies_actuation_policy_protocol() -> None:
    assert isinstance(AttitudeHoldReferencePolicy(), ActuationPolicy)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_actuate_is_deterministic_5x() -> None:
    p = AttitudeHoldReferencePolicy(proceed_thrust=0.6, hold_thrust=0.4)
    decision = _make_decision(DecisionKind.PROCEED, stamp=12_345_678)
    blobs = [encode_to_bytes(p.actuate(decision)) for _ in range(5)]
    assert all(b == blobs[0] for b in blobs)
