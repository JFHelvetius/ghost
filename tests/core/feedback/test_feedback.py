"""Tests del contrato de closed-loop feedback (ADR-0026).

Cubre:

- ``CalibrationHistory.__post_init__`` invariantes: counts no
  negativos, suma consistente, NaN, edge cases con 0 outcomes.
- ``CalibratedSelfAssessment.__post_init__`` invariantes: tipos,
  taxonomy, schema_version.
- ``build_calibration_history``: empty input, full window, truncation
  por ``max_n``, counts correctos, worst Mahalanobis, most recent stamp.
- ``MahalanobisDowngradePolicy``: passthrough cuando vacío;
  passthrough cuando dentro de tolerance; downgrade en cada nivel.
- ``assess_with_feedback`` pure: misma entrada → mismo output
  byte-equal.
- Protocol structural compliance.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.core.feedback import (
    FEEDBACK_PROTOCOL_VERSION,
    CalibratedSelfAssessment,
    CalibrationAdjustmentPolicy,
    CalibrationHistory,
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


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


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


def _make_assessment(stamp: int = 1000, pos_var: float = 1e-4) -> BeliefSelfAssessment:
    return assess_belief(_make_state(stamp, pos_var), _make_thresholds())


def _make_outcome(
    *,
    source_stamp: int = 1000,
    horizon: int = 500,
    error_x: float = 0.0,
    pos_std: float = 0.2,
) -> PredictionOutcome:
    """Produce a PredictionOutcome with a known position error."""
    pred = BeliefForwardPrediction(
        source_belief_stamp_sim_ns=source_stamp,
        predicted_observation_stamp_sim_ns=source_stamp + horizon,
        horizon_ns=horizon,
        predicted_pose=Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_Q.copy(),
        ),
        predicted_pose_std=PoseStd(
            position_std_enu_m=np.full(3, pos_std, dtype=np.float64),
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


# ---------------------------------------------------------------------------
# CalibrationHistory invariants
# ---------------------------------------------------------------------------


def test_calibration_history_empty_is_valid() -> None:
    h = CalibrationHistory(
        outcomes_considered=0,
        count_within_1_std=0,
        count_beyond_1_std=0,
        count_beyond_3_std=0,
        count_beyond_5_std=0,
        worst_position_mahalanobis=0.0,
        worst_orientation_mahalanobis=0.0,
        most_recent_observed_stamp_sim_ns=None,
    )
    assert h.outcomes_considered == 0


def test_calibration_history_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        CalibrationHistory(
            outcomes_considered=1,
            count_within_1_std=-1,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=100,
        )


def test_calibration_history_rejects_sum_mismatch() -> None:
    with pytest.raises(ValueError, match=r"sum\(counts\) .* must equal outcomes_considered"):
        CalibrationHistory(
            outcomes_considered=5,
            count_within_1_std=2,
            count_beyond_1_std=1,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=100,
        )


def test_calibration_history_rejects_nan_mahalanobis() -> None:
    with pytest.raises(ValueError, match="must not be NaN"):
        CalibrationHistory(
            outcomes_considered=1,
            count_within_1_std=1,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=float("nan"),
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=100,
        )


def test_calibration_history_accepts_inf_mahalanobis() -> None:
    h = CalibrationHistory(
        outcomes_considered=1,
        count_within_1_std=0,
        count_beyond_1_std=0,
        count_beyond_3_std=0,
        count_beyond_5_std=1,
        worst_position_mahalanobis=float("inf"),
        worst_orientation_mahalanobis=0.0,
        most_recent_observed_stamp_sim_ns=100,
    )
    assert h.worst_position_mahalanobis == float("inf")


def test_calibration_history_empty_rejects_nonzero_worst() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"worst_position_mahalanobis must be 0\.0 when "
            r"outcomes_considered == 0"
        ),
    ):
        CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=1.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )


def test_calibration_history_empty_rejects_stamp_present() -> None:
    with pytest.raises(
        ValueError,
        match=("most_recent_observed_stamp_sim_ns must be None when outcomes_considered == 0"),
    ):
        CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=100,
        )


def test_calibration_history_nonempty_rejects_stamp_none() -> None:
    with pytest.raises(
        ValueError,
        match=("most_recent_observed_stamp_sim_ns must not be None when outcomes_considered > 0"),
    ):
        CalibrationHistory(
            outcomes_considered=1,
            count_within_1_std=1,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )


def test_calibration_history_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be 1"):
        CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
            schema_version=99,
        )


def test_calibration_history_is_frozen() -> None:
    h = CalibrationHistory(
        outcomes_considered=0,
        count_within_1_std=0,
        count_beyond_1_std=0,
        count_beyond_3_std=0,
        count_beyond_5_std=0,
        worst_position_mahalanobis=0.0,
        worst_orientation_mahalanobis=0.0,
        most_recent_observed_stamp_sim_ns=None,
    )
    with pytest.raises(AttributeError):
        h.outcomes_considered = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CalibratedSelfAssessment invariants
# ---------------------------------------------------------------------------


def test_calibrated_assessment_accepts_valid_input() -> None:
    raw = _make_assessment()
    history = build_calibration_history([], max_n=32)
    cal = CalibratedSelfAssessment(
        raw_assessment=raw,
        calibration_history=history,
        adjusted_overall_level=raw.overall_level,
        adjustment_policy_id="some_policy_v1",
        adjustment_reason="passthrough",
    )
    assert cal.schema_version == FEEDBACK_PROTOCOL_VERSION


def test_calibrated_assessment_rejects_wrong_raw_type() -> None:
    history = build_calibration_history([], max_n=32)
    with pytest.raises(TypeError, match="raw_assessment must be BeliefSelfAssessment"):
        CalibratedSelfAssessment(
            raw_assessment="not an assessment",  # type: ignore[arg-type]
            calibration_history=history,
            adjusted_overall_level=SelfAssessmentLevel.KNOWN,
            adjustment_policy_id="some_policy_v1",
            adjustment_reason="passthrough",
        )


def test_calibrated_assessment_rejects_wrong_history_type() -> None:
    raw = _make_assessment()
    with pytest.raises(TypeError, match="calibration_history must be CalibrationHistory"):
        CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history="not a history",  # type: ignore[arg-type]
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id="some_policy_v1",
            adjustment_reason="passthrough",
        )


def test_calibrated_assessment_rejects_wrong_level_type() -> None:
    raw = _make_assessment()
    history = build_calibration_history([], max_n=32)
    with pytest.raises(TypeError, match="adjusted_overall_level must be SelfAssessmentLevel"):
        CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level="known",  # type: ignore[arg-type]
            adjustment_policy_id="some_policy_v1",
            adjustment_reason="passthrough",
        )


@pytest.mark.parametrize("bad_id", ["", "BadPolicy", "1bad", "has space", "a" * 65])
def test_calibrated_assessment_rejects_bad_policy_id(bad_id: str) -> None:
    raw = _make_assessment()
    history = build_calibration_history([], max_n=32)
    with pytest.raises((TypeError, ValueError)):
        CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id=bad_id,
            adjustment_reason="passthrough",
        )


# ---------------------------------------------------------------------------
# build_calibration_history
# ---------------------------------------------------------------------------


def test_build_history_empty_input() -> None:
    h = build_calibration_history([], max_n=32)
    assert h.outcomes_considered == 0
    assert h.most_recent_observed_stamp_sim_ns is None
    assert h.worst_position_mahalanobis == 0.0


def test_build_history_counts_verdicts_correctly() -> None:
    # std = 0.2; errors at multiples of std → known verdicts.
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=0.1),  # 0.5sigma -> WITHIN
        _make_outcome(source_stamp=2000, error_x=0.4),  # 2sigma -> BEYOND_1
        _make_outcome(source_stamp=3000, error_x=0.8),  # 4sigma -> BEYOND_3
        _make_outcome(source_stamp=4000, error_x=2.0),  # 10sigma -> BEYOND_5
    ]
    h = build_calibration_history(outcomes, max_n=32)
    assert h.outcomes_considered == 4
    assert h.count_within_1_std == 1
    assert h.count_beyond_1_std == 1
    assert h.count_beyond_3_std == 1
    assert h.count_beyond_5_std == 1


def test_build_history_tracks_worst_mahalanobis() -> None:
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=0.1),  # mahal = 0.5
        _make_outcome(source_stamp=2000, error_x=0.6),  # mahal = 3.0
    ]
    h = build_calibration_history(outcomes, max_n=32)
    assert h.worst_position_mahalanobis == pytest.approx(3.0)


def test_build_history_tracks_most_recent_stamp() -> None:
    outcomes = [
        _make_outcome(source_stamp=1000, horizon=500),  # actual at 1500
        _make_outcome(source_stamp=3000, horizon=500),  # actual at 3500
        _make_outcome(source_stamp=2000, horizon=500),  # actual at 2500
    ]
    h = build_calibration_history(outcomes, max_n=32)
    assert h.most_recent_observed_stamp_sim_ns == 3500


def test_build_history_truncates_to_max_n() -> None:
    outcomes = [_make_outcome(source_stamp=1000 * (i + 1)) for i in range(10)]
    h = build_calibration_history(outcomes, max_n=3)
    assert h.outcomes_considered == 3
    # The 3 most recent are 8000, 9000, 10000 (all error_x=0 → WITHIN)
    assert h.count_within_1_std == 3


def test_build_history_rejects_zero_max_n() -> None:
    with pytest.raises(ValueError, match="max_n must be > 0"):
        build_calibration_history([], max_n=0)


def test_build_history_rejects_negative_max_n() -> None:
    with pytest.raises(ValueError, match="max_n must be > 0"):
        build_calibration_history([], max_n=-1)


# ---------------------------------------------------------------------------
# MahalanobisDowngradePolicy
# ---------------------------------------------------------------------------


def test_policy_satisfies_protocol() -> None:
    assert isinstance(MahalanobisDowngradePolicy(), CalibrationAdjustmentPolicy)


def test_policy_id_includes_parameters() -> None:
    p = MahalanobisDowngradePolicy(min_outcomes=10, downgrade_threshold=3)
    assert "min10" in p.policy_id
    assert "thr3" in p.policy_id


def test_policy_rejects_bad_params() -> None:
    with pytest.raises(ValueError, match="min_outcomes must be >= 0"):
        MahalanobisDowngradePolicy(min_outcomes=-1)
    with pytest.raises(ValueError, match="downgrade_threshold must be >= 1"):
        MahalanobisDowngradePolicy(downgrade_threshold=0)


def test_policy_passthrough_when_empty_history() -> None:
    policy = MahalanobisDowngradePolicy()
    raw = _make_assessment(pos_var=1e-4)  # KNOWN
    history = build_calibration_history([], max_n=32)
    cal = policy.adjust(raw, history)
    assert cal.adjusted_overall_level == raw.overall_level
    assert cal.adjustment_reason == "no_outcomes_yet"


def test_policy_passthrough_below_min_outcomes() -> None:
    policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    raw = _make_assessment()
    # 3 outcomes all BEYOND_5_STD, but min_outcomes=4 → passthrough
    outcomes = [_make_outcome(source_stamp=1000 * (i + 1), error_x=2.0) for i in range(3)]
    history = build_calibration_history(outcomes, max_n=32)
    cal = policy.adjust(raw, history)
    assert cal.adjusted_overall_level == raw.overall_level
    assert cal.adjustment_reason == "calibration_within_tolerance"


def test_policy_passthrough_below_downgrade_threshold() -> None:
    policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    raw = _make_assessment()
    # 5 outcomes, only 1 BEYOND_3, rest WITHIN_1 → below threshold → passthrough
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=0.8),  # BEYOND_3
        _make_outcome(source_stamp=2000, error_x=0.0),  # WITHIN
        _make_outcome(source_stamp=3000, error_x=0.0),  # WITHIN
        _make_outcome(source_stamp=4000, error_x=0.0),  # WITHIN
        _make_outcome(source_stamp=5000, error_x=0.0),  # WITHIN
    ]
    history = build_calibration_history(outcomes, max_n=32)
    cal = policy.adjust(raw, history)
    assert cal.adjusted_overall_level == raw.overall_level
    assert cal.adjustment_reason == "calibration_within_tolerance"


def test_policy_downgrade_when_threshold_crossed() -> None:
    policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    raw = _make_assessment(pos_var=1e-4)  # KNOWN
    # 4 outcomes, 2 BEYOND_5 → triggers downgrade
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=2.0),  # BEYOND_5
        _make_outcome(source_stamp=2000, error_x=2.0),  # BEYOND_5
        _make_outcome(source_stamp=3000, error_x=0.0),
        _make_outcome(source_stamp=4000, error_x=0.0),
    ]
    history = build_calibration_history(outcomes, max_n=32)
    cal = policy.adjust(raw, history)
    assert raw.overall_level == SelfAssessmentLevel.KNOWN
    assert cal.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    assert cal.adjustment_reason == "downgrade_from_calibration"


def test_policy_downgrades_uncertain_to_unknown() -> None:
    policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    # Use cov that produces UNCERTAIN (pos_var between known and unknown
    # thresholds). thresholds.known=0.05, unknown=0.5 → std in (0.05, 0.5).
    # pos_var = 0.04 → std = 0.2.
    raw = _make_assessment(pos_var=0.04)
    assert raw.overall_level == SelfAssessmentLevel.UNCERTAIN
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=2.0),
        _make_outcome(source_stamp=2000, error_x=2.0),
        _make_outcome(source_stamp=3000, error_x=0.0),
        _make_outcome(source_stamp=4000, error_x=0.0),
    ]
    history = build_calibration_history(outcomes, max_n=32)
    cal = policy.adjust(raw, history)
    assert cal.adjusted_overall_level == SelfAssessmentLevel.UNKNOWN


def test_policy_unknown_stays_unknown_on_downgrade() -> None:
    policy = MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)
    raw = _make_assessment(pos_var=10.0)  # std huge → UNKNOWN
    assert raw.overall_level == SelfAssessmentLevel.UNKNOWN
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=2.0),
        _make_outcome(source_stamp=2000, error_x=2.0),
        _make_outcome(source_stamp=3000, error_x=0.0),
        _make_outcome(source_stamp=4000, error_x=0.0),
    ]
    history = build_calibration_history(outcomes, max_n=32)
    cal = policy.adjust(raw, history)
    assert cal.adjusted_overall_level == SelfAssessmentLevel.UNKNOWN


# ---------------------------------------------------------------------------
# assess_with_feedback pure
# ---------------------------------------------------------------------------


def test_assess_with_feedback_pure() -> None:
    """Same input → byte-equal output."""
    policy = MahalanobisDowngradePolicy()
    raw = _make_assessment()
    outcomes = [
        _make_outcome(source_stamp=1000, error_x=0.1),
        _make_outcome(source_stamp=2000, error_x=2.0),
    ]
    c1 = assess_with_feedback(raw, outcomes, policy)
    c2 = assess_with_feedback(raw, outcomes, policy)
    assert encode_to_bytes(c1) == encode_to_bytes(c2)


def test_assess_with_feedback_returns_calibrated() -> None:
    policy = MahalanobisDowngradePolicy()
    raw = _make_assessment()
    cal = assess_with_feedback(raw, [], policy)
    assert isinstance(cal, CalibratedSelfAssessment)
    assert cal.raw_assessment is raw


# ---------------------------------------------------------------------------
# Extra coverage: low-level validators + properties
# ---------------------------------------------------------------------------


def test_calibration_history_rejects_non_int_count() -> None:
    with pytest.raises(TypeError, match="must be int"):
        CalibrationHistory(
            outcomes_considered=1.5,  # type: ignore[arg-type]
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=None,
        )


def test_calibration_history_rejects_negative_mahalanobis() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        CalibrationHistory(
            outcomes_considered=1,
            count_within_1_std=1,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=-0.1,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=100,
        )


def test_calibration_history_empty_rejects_nonzero_orientation_worst() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"worst_orientation_mahalanobis must be 0\.0 when "
            r"outcomes_considered == 0"
        ),
    ):
        CalibrationHistory(
            outcomes_considered=0,
            count_within_1_std=0,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=1.0,
            most_recent_observed_stamp_sim_ns=None,
        )


def test_calibration_history_rejects_negative_stamp() -> None:
    with pytest.raises(
        ValueError,
        match=r"most_recent_observed_stamp_sim_ns must be >= 0",
    ):
        CalibrationHistory(
            outcomes_considered=1,
            count_within_1_std=1,
            count_beyond_1_std=0,
            count_beyond_3_std=0,
            count_beyond_5_std=0,
            worst_position_mahalanobis=0.0,
            worst_orientation_mahalanobis=0.0,
            most_recent_observed_stamp_sim_ns=-5,
        )


def test_calibrated_assessment_rejects_wrong_schema_version() -> None:
    raw = _make_assessment()
    history = build_calibration_history([], max_n=32)
    with pytest.raises(ValueError, match="schema_version must be 1"):
        CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id="some_policy_v1",
            adjustment_reason="passthrough",
            schema_version=99,
        )


def test_taxonomy_rejects_non_string_input() -> None:
    raw = _make_assessment()
    history = build_calibration_history([], max_n=32)
    with pytest.raises(TypeError, match="adjustment_policy_id must be str"):
        CalibratedSelfAssessment(
            raw_assessment=raw,
            calibration_history=history,
            adjusted_overall_level=raw.overall_level,
            adjustment_policy_id=123,  # type: ignore[arg-type]
            adjustment_reason="passthrough",
        )


def test_policy_exposes_parameters_as_properties() -> None:
    p = MahalanobisDowngradePolicy(min_outcomes=7, downgrade_threshold=3)
    assert p.min_outcomes == 7
    assert p.downgrade_threshold == 3
