"""Tests del paquete `core.decisions` (ADR-0021).

Cubre:

- ``DecisionKind`` catálogo cerrado.
- ``Decision`` validación (reason format, stamp, frozen).
- ``DecisionContext`` validación.
- ``DecisionRationale`` validación + invariante decision/belief stamp.
- ``self_assessment_sha256`` determinismo y content-address.
- ``Policy`` y ``DecisionSink`` Protocol structural (isinstance).
- ``NullDecisionSink``, ``RecordingDecisionSink`` semantic.
- ``UncertaintyAwareReferencePolicy`` mapping completo.
- ``decide_with_rationale``, ``decide_and_publish`` orquestación.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.decisions import (
    DECISION_PROTOCOL_VERSION,
    Decision,
    DecisionContext,
    DecisionKind,
    DecisionRationale,
    DecisionSink,
    NullDecisionSink,
    Policy,
    RecordingDecisionSink,
    UncertaintyAwareReferencePolicy,
    decide_and_publish,
    decide_with_rationale,
    self_assessment_sha256,
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

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    stamp_sim_ns: int = 1000,
    pos_var: float = 1e-4,
    cov_available: bool = True,
) -> VehicleState:
    diag = np.array(
        [pos_var] * 3 + [1e-4] * 3 + [1e-4] * 3 + [1e-6] * 3 + [1e-6] * 3,
        dtype=np.float64,
    )
    cov: np.ndarray | None = np.diag(diag) if cov_available else None
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


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _make_context(
    *,
    stamp_sim_ns: int = 1000,
    self_assessment: BeliefSelfAssessment | None = None,
    pos_var: float = 1e-4,
    cov_available: bool = True,
    include_assessment: bool = True,
) -> DecisionContext:
    state = _make_state(
        stamp_sim_ns=stamp_sim_ns,
        pos_var=pos_var,
        cov_available=cov_available,
    )
    if self_assessment is None and include_assessment:
        self_assessment = assess_belief(state, _make_thresholds())
    return DecisionContext(
        belief_stamp_sim_ns=stamp_sim_ns,
        self_assessment=self_assessment,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )


# ---------------------------------------------------------------------------
# DecisionKind
# ---------------------------------------------------------------------------


def test_decision_kind_catalog_is_seven_entries() -> None:
    """V1 catalog frozen: 7 kinds. Cambiar requiere ADR amendment."""
    expected_count = 7
    assert len(list(DecisionKind)) == expected_count
    expected_values = {
        "proceed",
        "hold",
        "yield_to_pilot",
        "engage_rtl",
        "engage_land",
        "engage_kill",
        "abstain_uncertain",
    }
    assert {dk.value for dk in DecisionKind} == expected_values


def test_decision_kind_is_strenum() -> None:
    """StrEnum permite usar DecisionKind como str (serialización JSON)."""
    assert DecisionKind.PROCEED.value == "proceed"
    assert str(DecisionKind.PROCEED) == "proceed"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def test_decision_valid_construction() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=1000,
        reason="overall_known",
    )
    assert d.kind == DecisionKind.PROCEED
    assert d.decision_stamp_sim_ns == 1000
    assert d.reason == "overall_known"
    assert d.schema_version == DECISION_PROTOCOL_VERSION


def test_decision_is_frozen() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="overall_known",
    )
    with pytest.raises(FrozenInstanceError):
        d.kind = DecisionKind.HOLD  # type: ignore[misc]


def test_decision_rejects_non_decisionkind() -> None:
    with pytest.raises(TypeError, match="DecisionKind"):
        Decision(
            kind="proceed",  # type: ignore[arg-type]
            decision_stamp_sim_ns=0,
            reason="overall_known",
        )


def test_decision_rejects_negative_stamp() -> None:
    with pytest.raises(ValueError, match="decision_stamp_sim_ns"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=-1,
            reason="overall_known",
        )


def test_decision_rejects_empty_reason() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="",
        )


def test_decision_rejects_reason_uppercase() -> None:
    with pytest.raises(ValueError, match="must match"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="Overall_Known",
        )


def test_decision_rejects_reason_with_spaces() -> None:
    with pytest.raises(ValueError, match="must match"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="overall known",
        )


def test_decision_rejects_reason_starting_with_digit() -> None:
    with pytest.raises(ValueError, match="must match"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="1_started_with_digit",
        )


def test_decision_rejects_reason_too_long() -> None:
    with pytest.raises(ValueError, match="<= 64"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="a" * 65,
        )


def test_decision_rejects_non_string_reason() -> None:
    with pytest.raises(TypeError, match="reason must be str"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason=42,  # type: ignore[arg-type]
        )


def test_decision_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=0,
            reason="ok",
            schema_version=999,
        )


def test_decision_accepts_reason_with_digits_and_underscores() -> None:
    d = Decision(
        kind=DecisionKind.HOLD,
        decision_stamp_sim_ns=0,
        reason="reason_v2_with_42_things",
    )
    assert d.reason == "reason_v2_with_42_things"


# ---------------------------------------------------------------------------
# DecisionContext
# ---------------------------------------------------------------------------


def test_decision_context_valid_construction() -> None:
    ctx = _make_context(stamp_sim_ns=42)
    assert ctx.belief_stamp_sim_ns == 42
    assert ctx.self_assessment is not None
    assert ctx.perception_mode is None


def test_decision_context_accepts_none_assessment() -> None:
    ctx = _make_context(include_assessment=False)
    assert ctx.self_assessment is None


def test_decision_context_rejects_negative_stamp() -> None:
    state = _make_state()
    with pytest.raises(ValueError, match="belief_stamp_sim_ns"):
        DecisionContext(
            belief_stamp_sim_ns=-1,
            self_assessment=None,
            flight_status=state.flight,
            mission_status=state.mission,
            perception_mode=None,
        )


def test_decision_context_rejects_wrong_schema_version() -> None:
    state = _make_state()
    with pytest.raises(ValueError, match="schema_version"):
        DecisionContext(
            belief_stamp_sim_ns=0,
            self_assessment=None,
            flight_status=state.flight,
            mission_status=state.mission,
            perception_mode=None,
            schema_version=999,
        )


def test_decision_context_is_frozen() -> None:
    ctx = _make_context()
    with pytest.raises(FrozenInstanceError):
        ctx.belief_stamp_sim_ns = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DecisionRationale
# ---------------------------------------------------------------------------


def test_rationale_valid_construction() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=1000,
        reason="overall_known",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=1000,
        self_assessment_sha256="a" * 64,
        policy_id="some_policy",
    )
    assert r.decision == d
    assert r.policy_id == "some_policy"


def test_rationale_accepts_none_sha() -> None:
    d = Decision(
        kind=DecisionKind.ABSTAIN_UNCERTAIN,
        decision_stamp_sim_ns=0,
        reason="no_assessment",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=0,
        self_assessment_sha256=None,
        policy_id="p",
    )
    assert r.self_assessment_sha256 is None


def test_rationale_rejects_stamp_mismatch() -> None:
    """v1 enforces reactive synchronous decisions."""
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=1000,
        reason="ok",
    )
    with pytest.raises(ValueError, match="must equal decision"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=2000,  # diferente
            self_assessment_sha256=None,
            policy_id="p",
        )


def test_rationale_rejects_bad_sha_length() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    with pytest.raises(ValueError, match="hex chars"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=0,
            self_assessment_sha256="abc",
            policy_id="p",
        )


def test_rationale_rejects_uppercase_sha() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    with pytest.raises(ValueError, match="lowercase hex"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=0,
            self_assessment_sha256="A" * 64,
            policy_id="p",
        )


def test_rationale_rejects_empty_policy_id() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=0,
            self_assessment_sha256=None,
            policy_id="",
        )


def test_rationale_rejects_non_decision_in_decision_field() -> None:
    with pytest.raises(TypeError, match="decision must be Decision"):
        DecisionRationale(
            decision="not_a_decision",  # type: ignore[arg-type]
            belief_stamp_sim_ns=0,
            self_assessment_sha256=None,
            policy_id="p",
        )


def test_rationale_rejects_negative_belief_stamp() -> None:
    # decision with stamp -1 fails first; we need a different angle.
    # Use a decision with stamp 1000, and set belief_stamp to -1; the
    # check "belief_stamp_sim_ns < 0" raises first.
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=1000,
        reason="ok",
    )
    with pytest.raises(ValueError, match="belief_stamp_sim_ns must be >= 0"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=-1,
            self_assessment_sha256=None,
            policy_id="p",
        )


def test_rationale_rejects_non_string_sha() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    with pytest.raises(TypeError, match="must be str or None"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=0,
            self_assessment_sha256=12345,  # type: ignore[arg-type]
            policy_id="p",
        )


def test_rationale_rejects_wrong_schema_version() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    with pytest.raises(ValueError, match="schema_version"):
        DecisionRationale(
            decision=d,
            belief_stamp_sim_ns=0,
            self_assessment_sha256=None,
            policy_id="p",
            schema_version=999,
        )


def test_rationale_is_frozen() -> None:
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=0,
        self_assessment_sha256=None,
        policy_id="p",
    )
    with pytest.raises(FrozenInstanceError):
        r.policy_id = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# self_assessment_sha256
# ---------------------------------------------------------------------------


def test_sha256_is_64_hex_chars() -> None:
    ctx = _make_context()
    assert ctx.self_assessment is not None
    h = self_assessment_sha256(ctx.self_assessment)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_is_deterministic() -> None:
    ctx = _make_context()
    assert ctx.self_assessment is not None
    a = self_assessment_sha256(ctx.self_assessment)
    b = self_assessment_sha256(ctx.self_assessment)
    assert a == b


def test_sha256_differs_when_assessment_differs() -> None:
    ctx_known = _make_context(pos_var=1e-4)
    ctx_unknown = _make_context(pos_var=1.0)
    assert ctx_known.self_assessment is not None
    assert ctx_unknown.self_assessment is not None
    assert self_assessment_sha256(ctx_known.self_assessment) != self_assessment_sha256(
        ctx_unknown.self_assessment
    )


# ---------------------------------------------------------------------------
# Protocols structural (runtime_checkable)
# ---------------------------------------------------------------------------


def test_uncertainty_aware_policy_satisfies_policy_protocol() -> None:
    policy = UncertaintyAwareReferencePolicy()
    assert isinstance(policy, Policy)


def test_null_sink_satisfies_decision_sink_protocol() -> None:
    sink = NullDecisionSink()
    assert isinstance(sink, DecisionSink)


def test_recording_sink_satisfies_decision_sink_protocol() -> None:
    sink = RecordingDecisionSink()
    assert isinstance(sink, DecisionSink)


# ---------------------------------------------------------------------------
# NullDecisionSink / RecordingDecisionSink
# ---------------------------------------------------------------------------


def test_null_sink_discards_silently() -> None:
    sink = NullDecisionSink()
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=0,
        self_assessment_sha256=None,
        policy_id="p",
    )
    sink.publish(d, r)  # no error


def test_recording_sink_keeps_records_in_order() -> None:
    sink = RecordingDecisionSink()
    d1 = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=100,
        reason="ok",
    )
    r1 = DecisionRationale(
        decision=d1,
        belief_stamp_sim_ns=100,
        self_assessment_sha256=None,
        policy_id="p",
    )
    d2 = Decision(
        kind=DecisionKind.HOLD,
        decision_stamp_sim_ns=200,
        reason="ok",
    )
    r2 = DecisionRationale(
        decision=d2,
        belief_stamp_sim_ns=200,
        self_assessment_sha256=None,
        policy_id="p",
    )
    sink.publish(d1, r1)
    sink.publish(d2, r2)
    records = sink.records
    assert len(records) == 2
    assert records[0] == (d1, r1)
    assert records[1] == (d2, r2)


def test_recording_sink_rejects_mismatched_decision_in_rationale() -> None:
    """Enforcement: rationale.decision debe matchear decision al publish."""
    sink = RecordingDecisionSink()
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
        sink.publish(d_a, r_for_b)


def test_recording_sink_clear_empties_records() -> None:
    sink = RecordingDecisionSink()
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=0,
        reason="ok",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=0,
        self_assessment_sha256=None,
        policy_id="p",
    )
    sink.publish(d, r)
    sink.clear()
    assert sink.records == ()


# ---------------------------------------------------------------------------
# UncertaintyAwareReferencePolicy
# ---------------------------------------------------------------------------


def test_reference_policy_has_stable_id() -> None:
    policy = UncertaintyAwareReferencePolicy()
    assert policy.policy_id == "uncertainty_aware_reference_v1"


def test_reference_policy_known_maps_to_proceed() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(pos_var=1e-4)  # std=0.01 → KNOWN
    d = policy.decide(ctx)
    assert d.kind == DecisionKind.PROCEED
    assert d.reason == "overall_known"


def test_reference_policy_uncertain_maps_to_hold() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(pos_var=0.04)  # std=0.2 → UNCERTAIN
    d = policy.decide(ctx)
    assert d.kind == DecisionKind.HOLD
    assert d.reason == "overall_uncertain"


def test_reference_policy_unknown_maps_to_abstain() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(pos_var=1.0)  # std=1.0 → UNKNOWN
    d = policy.decide(ctx)
    assert d.kind == DecisionKind.ABSTAIN_UNCERTAIN
    assert d.reason == "overall_unknown"


def test_reference_policy_no_assessment_maps_to_abstain() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(include_assessment=False)
    d = policy.decide(ctx)
    assert d.kind == DecisionKind.ABSTAIN_UNCERTAIN
    assert d.reason == "no_assessment"


def test_reference_policy_no_covariance_maps_to_abstain() -> None:
    """Sin covarianza, el assessment es UNKNOWN → policy abstiene."""
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(cov_available=False)
    d = policy.decide(ctx)
    assert d.kind == DecisionKind.ABSTAIN_UNCERTAIN
    assert d.reason == "overall_unknown"


def test_reference_policy_preserves_belief_stamp() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(stamp_sim_ns=42_000)
    d = policy.decide(ctx)
    assert d.decision_stamp_sim_ns == 42_000


def test_reference_policy_is_deterministic() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    assert policy.decide(ctx) == policy.decide(ctx)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def test_decide_with_rationale_returns_consistent_pair() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(stamp_sim_ns=1000)
    decision, rationale = decide_with_rationale(policy, ctx)
    assert rationale.decision == decision
    assert rationale.belief_stamp_sim_ns == 1000
    assert rationale.policy_id == policy.policy_id


def test_decide_with_rationale_carries_assessment_sha() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    _, rationale = decide_with_rationale(policy, ctx)
    assert ctx.self_assessment is not None
    assert rationale.self_assessment_sha256 == self_assessment_sha256(ctx.self_assessment)


def test_decide_with_rationale_none_sha_when_no_assessment() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context(include_assessment=False)
    _, rationale = decide_with_rationale(policy, ctx)
    assert rationale.self_assessment_sha256 is None


def test_decide_with_rationale_is_deterministic() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    a = decide_with_rationale(policy, ctx)
    b = decide_with_rationale(policy, ctx)
    assert a == b


def test_decide_and_publish_returns_decision() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    sink = RecordingDecisionSink()
    decision = decide_and_publish(policy, ctx, sink)
    assert isinstance(decision, Decision)


def test_decide_and_publish_records_to_sink() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    sink = RecordingDecisionSink()
    decide_and_publish(policy, ctx, sink)
    assert len(sink.records) == 1
    rec_decision, rec_rationale = sink.records[0]
    assert rec_rationale.decision == rec_decision


def test_decide_and_publish_with_null_sink_discards() -> None:
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    sink = NullDecisionSink()
    decision = decide_and_publish(policy, ctx, sink)
    assert isinstance(decision, Decision)  # smoke


# ---------------------------------------------------------------------------
# Audit chain integrity
# ---------------------------------------------------------------------------


def test_audit_chain_belief_to_decision_is_verifiable() -> None:
    """End-to-end: dado un assessment, un policy y un decision, un
    auditor puede verificar el SHA-256 del assessment desde el
    rationale. Es la propiedad central de provenance de ADR-0021."""
    policy = UncertaintyAwareReferencePolicy()
    ctx = _make_context()
    assert ctx.self_assessment is not None
    _, rationale = decide_with_rationale(policy, ctx)
    # Auditor re-compute:
    expected_sha = self_assessment_sha256(ctx.self_assessment)
    assert rationale.self_assessment_sha256 == expected_sha
    # And re-apply policy:
    re_decision = policy.decide(ctx)
    assert re_decision == rationale.decision
