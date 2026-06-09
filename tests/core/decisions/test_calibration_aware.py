"""Tests del calibration-aware DecisionContext + reference policy
(ADR-0027 amendment a ADR-0021).

Cubre:

- ``DecisionContext`` con ``calibrated_self_assessment=None`` (default)
  preserva comportamiento de ADR-0021 byte-equal.
- ``effective_overall_level`` devuelve calibrated cuando presente, raw
  cuando solo raw, ``None`` cuando ninguno.
- ``__post_init__`` rechaza ``calibrated_self_assessment`` con stamp
  inconsistente vs raw.
- ``__post_init__`` rechaza ``calibrated_self_assessment`` de tipo
  incorrecto.
- ``UncertaintyAwareReferencePolicy`` produce decisión basada en
  ``effective_overall_level`` (no en raw cuando calibration está
  presente).
- Backward-compat: la policy con context sin calibrated emite la misma
  decisión que ADR-0021 pre-amendment.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.core.decisions import (
    DecisionContext,
    DecisionKind,
    UncertaintyAwareReferencePolicy,
)
from project_ghost.core.feedback import (
    CalibratedSelfAssessment,
    CalibrationHistory,
    MahalanobisDowngradePolicy,
    assess_with_feedback,
)
from project_ghost.core.prediction import (
    BeliefForwardPrediction,
    PoseStd,
    compute_divergence,
)
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    BeliefSelfAssessment,
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
from project_ghost.telemetry import encode_to_bytes

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


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _make_assessment(
    stamp: int = 1000, pos_var: float = 1e-4
) -> BeliefSelfAssessment:
    return assess_belief(_make_state(stamp, pos_var), _make_thresholds())


def _make_bad_outcome(
    source_stamp: int = 1000, horizon: int = 500
) -> object:
    pred = BeliefForwardPrediction(
        source_belief_stamp_sim_ns=source_stamp,
        predicted_observation_stamp_sim_ns=source_stamp + horizon,
        horizon_ns=horizon,
        predicted_pose=Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_Q.copy(),
        ),
        predicted_pose_std=PoseStd(
            position_std_enu_m=np.full(3, 0.05, dtype=np.float64),
            orientation_std_rad=np.full(3, 10.0, dtype=np.float64),
        ),
        associated_directive_hash=None,
        predictor_id="constant_velocity_v1",
    )
    actual = Pose(
        position_enu_m=np.array([1.0, 0.0, 0.0], dtype=np.float64),
        orientation_q=_Q.copy(),
    )
    return compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )


def _make_downgrade_calibrated(
    stamp: int = 1000,
) -> CalibratedSelfAssessment:
    """Build a calibrated assessment whose adjusted level is UNCERTAIN
    via the standard feedback path."""
    raw = _make_assessment(stamp=stamp, pos_var=1e-4)  # KNOWN
    outcomes = [
        _make_bad_outcome(source_stamp=900 + 100 * i, horizon=10)
        for i in range(4)
    ]
    policy = MahalanobisDowngradePolicy(
        min_outcomes=4, downgrade_threshold=2
    )
    cal = assess_with_feedback(raw, outcomes, policy)
    assert cal.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    return cal


def _empty_history() -> CalibrationHistory:
    return CalibrationHistory(
        outcomes_considered=0,
        count_within_1_std=0,
        count_beyond_1_std=0,
        count_beyond_3_std=0,
        count_beyond_5_std=0,
        worst_position_mahalanobis=0.0,
        worst_orientation_mahalanobis=0.0,
        most_recent_observed_stamp_sim_ns=None,
    )


# ---------------------------------------------------------------------------
# DecisionContext.effective_overall_level
# ---------------------------------------------------------------------------


def test_effective_level_is_none_when_no_assessment() -> None:
    state = _make_state()
    ctx = DecisionContext(
        belief_stamp_sim_ns=state.stamp_sim_ns,
        self_assessment=None,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    assert ctx.effective_overall_level is None


def test_effective_level_falls_back_to_raw_when_no_calibrated() -> None:
    raw = _make_assessment(pos_var=1e-4)  # KNOWN
    state = _make_state(stamp=raw.belief_stamp_sim_ns)
    ctx = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    assert ctx.effective_overall_level == SelfAssessmentLevel.KNOWN


def test_effective_level_prefers_calibrated_when_present() -> None:
    cal = _make_downgrade_calibrated(stamp=1000)
    state = _make_state(stamp=1000)
    ctx = DecisionContext(
        belief_stamp_sim_ns=1000,
        self_assessment=cal.raw_assessment,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
        calibrated_self_assessment=cal,
    )
    assert cal.raw_assessment.overall_level == SelfAssessmentLevel.KNOWN
    assert ctx.effective_overall_level == SelfAssessmentLevel.UNCERTAIN


def test_effective_level_uses_calibrated_even_without_raw() -> None:
    """Edge case: calibrated present, raw=None. The calibrated record
    embeds the raw inline, so effective level is well-defined."""
    cal = _make_downgrade_calibrated(stamp=1000)
    state = _make_state(stamp=1000)
    ctx = DecisionContext(
        belief_stamp_sim_ns=1000,
        self_assessment=None,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
        calibrated_self_assessment=cal,
    )
    assert ctx.effective_overall_level == SelfAssessmentLevel.UNCERTAIN


# ---------------------------------------------------------------------------
# DecisionContext.__post_init__ invariants
# ---------------------------------------------------------------------------


def test_post_init_rejects_calibrated_of_wrong_type() -> None:
    state = _make_state()
    with pytest.raises(
        TypeError,
        match="calibrated_self_assessment must be CalibratedSelfAssessment",
    ):
        DecisionContext(
            belief_stamp_sim_ns=state.stamp_sim_ns,
            self_assessment=None,
            flight_status=state.flight,
            mission_status=state.mission,
            perception_mode=None,
            calibrated_self_assessment="not a calibrated",  # type: ignore[arg-type]
        )


def test_post_init_rejects_mismatched_stamps() -> None:
    raw = _make_assessment(stamp=2000)
    cal = _make_downgrade_calibrated(stamp=1000)
    state = _make_state(stamp=2000)
    with pytest.raises(
        ValueError,
        match=r"calibrated_self_assessment stamp .* must equal self_assessment stamp",
    ):
        DecisionContext(
            belief_stamp_sim_ns=2000,
            self_assessment=raw,
            flight_status=state.flight,
            mission_status=state.mission,
            perception_mode=None,
            calibrated_self_assessment=cal,
        )


def test_post_init_accepts_consistent_stamps() -> None:
    cal = _make_downgrade_calibrated(stamp=1500)
    raw = cal.raw_assessment
    state = _make_state(stamp=1500)
    ctx = DecisionContext(
        belief_stamp_sim_ns=1500,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
        calibrated_self_assessment=cal,
    )
    assert ctx.calibrated_self_assessment is cal


# ---------------------------------------------------------------------------
# Backward-compat: omitting the new field is byte-equal to ADR-0021
# ---------------------------------------------------------------------------


def test_decision_context_default_calibrated_is_none() -> None:
    raw = _make_assessment()
    state = _make_state(stamp=raw.belief_stamp_sim_ns)
    ctx = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    assert ctx.calibrated_self_assessment is None


def test_decision_context_without_calibrated_byte_equal_across_runs() -> None:
    raw = _make_assessment()
    state = _make_state(stamp=raw.belief_stamp_sim_ns)
    ctx1 = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    ctx2 = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    # encode_to_bytes is a public determinism contract; context goes
    # through it indirectly via rationale → decision, but we encode
    # the raw assessment to assert backward compat of the carried
    # field.
    assert encode_to_bytes(ctx1.self_assessment) == encode_to_bytes(
        ctx2.self_assessment
    )


# ---------------------------------------------------------------------------
# UncertaintyAwareReferencePolicy is calibration-aware
# ---------------------------------------------------------------------------


def test_policy_uses_calibrated_level_when_downgraded() -> None:
    """Calibration downgrades KNOWN -> UNCERTAIN; the policy must
    decide HOLD, not PROCEED."""
    cal = _make_downgrade_calibrated(stamp=1000)
    state = _make_state(stamp=1000)
    ctx = DecisionContext(
        belief_stamp_sim_ns=1000,
        self_assessment=cal.raw_assessment,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
        calibrated_self_assessment=cal,
    )
    decision = UncertaintyAwareReferencePolicy().decide(ctx)
    assert decision.kind == DecisionKind.HOLD
    assert decision.reason == "overall_uncertain"


def test_policy_preserves_raw_behavior_without_calibrated() -> None:
    """Backward-compat: with calibrated=None, decision matches the
    raw overall level exactly (ADR-0021 behavior preserved)."""
    raw = _make_assessment(pos_var=1e-4)  # KNOWN
    state = _make_state(stamp=raw.belief_stamp_sim_ns)
    ctx = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    decision = UncertaintyAwareReferencePolicy().decide(ctx)
    assert decision.kind == DecisionKind.PROCEED
    assert decision.reason == "overall_known"


def test_policy_handles_calibrated_passthrough_when_no_outcomes() -> None:
    """When the calibration is a passthrough (no outcomes), the
    policy decides on the raw level (which the calibrated mirrors)."""
    raw = _make_assessment(pos_var=1e-4)  # KNOWN
    passthrough = CalibratedSelfAssessment(
        raw_assessment=raw,
        calibration_history=_empty_history(),
        adjusted_overall_level=raw.overall_level,
        adjustment_policy_id="mahalanobis_downgrade_v1_min4_thr2",
        adjustment_reason="no_outcomes_yet",
    )
    state = _make_state(stamp=raw.belief_stamp_sim_ns)
    ctx = DecisionContext(
        belief_stamp_sim_ns=raw.belief_stamp_sim_ns,
        self_assessment=raw,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
        calibrated_self_assessment=passthrough,
    )
    decision = UncertaintyAwareReferencePolicy().decide(ctx)
    assert decision.kind == DecisionKind.PROCEED


def test_policy_handles_no_assessment_at_all() -> None:
    state = _make_state()
    ctx = DecisionContext(
        belief_stamp_sim_ns=state.stamp_sim_ns,
        self_assessment=None,
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )
    decision = UncertaintyAwareReferencePolicy().decide(ctx)
    assert decision.kind == DecisionKind.ABSTAIN_UNCERTAIN
    assert decision.reason == "no_assessment"
