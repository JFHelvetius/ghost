"""Tests for the alternative calibration policies (paper §8.5).

Covers ``EWMADowngradePolicy`` and ``PerAxisHysteresisDowngradePolicy``:

- Protocol structural compliance (each policy is a
  ``CalibrationAdjustmentPolicy``).
- ``policy_id`` stability and parameter-distinctness.
- Constructor validation rejects invalid parameter ranges.
- ``adjust`` is pure: same (raw, history) → same output.
- Decision rule fires correctly on engineered inputs:
  - passthrough below ``min_outcomes``;
  - downgrade above the policy's threshold;
  - passthrough below threshold (within tolerance).
- MD-v1 monotonicity: adjusted is never strictly more confident than
  raw, for any (raw, history) accepted by the policy.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.core.feedback import (
    CalibrationAdjustmentPolicy,
    CalibrationHistory,
    EWMADowngradePolicy,
    PerAxisHysteresisDowngradePolicy,
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

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _make_known_state(stamp_ns: int = 1_000_000_000) -> VehicleState:
    """Mirror of the test_feedback.py fixture: low covariance → KNOWN."""
    cov = np.eye(15, dtype=np.float64) * 1e-4
    pose = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
    )
    twist_world = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )
    twist_body = Twist(
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
        twist_world=twist_world,
        twist_body=twist_body,
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=biases,
        covariance_15x15=cov,
    )
    return VehicleState(
        stamp_sim_ns=stamp_ns,
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


def _make_raw_known() -> BeliefSelfAssessment:
    return assess_belief(_make_known_state(), _make_thresholds())


def _make_history(
    *,
    outcomes_considered: int,
    dirty: int,
    worst_position: float = 0.5,
    worst_orientation: float = 0.5,
) -> CalibrationHistory:
    if dirty > outcomes_considered:
        raise ValueError("dirty must be <= outcomes_considered")
    clean = outcomes_considered - dirty
    # The CalibrationHistory invariants require worst_*_mahalanobis = 0
    # when outcomes_considered = 0 (consistency with the empty window).
    if outcomes_considered == 0:
        wp = 0.0
        wo = 0.0
        stamp: int | None = None
    else:
        wp = worst_position
        wo = worst_orientation
        stamp = 1_000_000_000
    return CalibrationHistory(
        outcomes_considered=outcomes_considered,
        count_within_1_std=clean,
        count_beyond_1_std=0,
        count_beyond_3_std=dirty,
        count_beyond_5_std=0,
        worst_position_mahalanobis=wp,
        worst_orientation_mahalanobis=wo,
        most_recent_observed_stamp_sim_ns=stamp,
    )


# ---------------------------------------------------------------------------
# EWMADowngradePolicy
# ---------------------------------------------------------------------------


def test_ewma_implements_protocol() -> None:
    policy = EWMADowngradePolicy()
    assert isinstance(policy, CalibrationAdjustmentPolicy)


def test_ewma_policy_id_includes_parameters() -> None:
    p1 = EWMADowngradePolicy(alpha=0.5, min_outcomes=3, downgrade_ewma_threshold=0.3)
    p2 = EWMADowngradePolicy(alpha=0.5, min_outcomes=3, downgrade_ewma_threshold=0.4)
    assert p1.policy_id != p2.policy_id
    assert "ewma_downgrade_v1" in p1.policy_id


def test_ewma_rejects_alpha_out_of_range() -> None:
    with pytest.raises(ValueError, match="alpha must be in"):
        EWMADowngradePolicy(alpha=0.0)
    with pytest.raises(ValueError, match="alpha must be in"):
        EWMADowngradePolicy(alpha=1.5)


def test_ewma_rejects_negative_min_outcomes() -> None:
    with pytest.raises(ValueError, match="min_outcomes must be >= 0"):
        EWMADowngradePolicy(min_outcomes=-1)


def test_ewma_rejects_threshold_out_of_range() -> None:
    with pytest.raises(ValueError, match="downgrade_ewma_threshold must be in"):
        EWMADowngradePolicy(downgrade_ewma_threshold=-0.1)
    with pytest.raises(ValueError, match="downgrade_ewma_threshold must be in"):
        EWMADowngradePolicy(downgrade_ewma_threshold=1.5)


def test_ewma_empty_history_is_passthrough() -> None:
    policy = EWMADowngradePolicy()
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=0, dirty=0)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == raw.overall_level
    assert result.adjustment_reason == "no_outcomes_yet"


def test_ewma_below_min_outcomes_is_passthrough() -> None:
    policy = EWMADowngradePolicy(min_outcomes=5)
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=2, dirty=2)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == raw.overall_level
    assert result.adjustment_reason == "calibration_within_tolerance"


def test_ewma_high_dirty_fraction_triggers_downgrade() -> None:
    policy = EWMADowngradePolicy(alpha=0.5, min_outcomes=3, downgrade_ewma_threshold=0.3)
    raw = _make_raw_known()
    # 4 / 5 = 0.8 > 0.3 → downgrade.
    h = _make_history(outcomes_considered=5, dirty=4)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    assert result.adjustment_reason == "downgrade_from_calibration"


def test_ewma_low_dirty_fraction_is_within_tolerance() -> None:
    policy = EWMADowngradePolicy(alpha=0.5, min_outcomes=3, downgrade_ewma_threshold=0.5)
    raw = _make_raw_known()
    # 1 / 5 = 0.2 < 0.5 → passthrough.
    h = _make_history(outcomes_considered=5, dirty=1)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == raw.overall_level
    assert result.adjustment_reason == "calibration_within_tolerance"


def test_ewma_is_pure() -> None:
    policy = EWMADowngradePolicy()
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=5, dirty=4)
    r1 = policy.adjust(raw, h)
    r2 = policy.adjust(raw, h)
    assert r1 == r2


def test_ewma_satisfies_md_monotonicity_under_random_input() -> None:
    """MD-v1 (paper §3.3): adjusted is never strictly more confident than raw."""
    # Seeded local rng — not global state; the property-tests pattern.
    rng = np.random.default_rng(42)
    policy = EWMADowngradePolicy()
    raw = _make_raw_known()
    level_num = {
        SelfAssessmentLevel.KNOWN: 0,
        SelfAssessmentLevel.UNCERTAIN: 1,
        SelfAssessmentLevel.UNKNOWN: 2,
    }
    for _ in range(50):
        n = int(rng.integers(0, 33))
        dirty = int(rng.integers(0, n + 1))
        h = _make_history(outcomes_considered=n, dirty=dirty)
        result = policy.adjust(raw, h)
        assert level_num[result.adjusted_overall_level] >= level_num[raw.overall_level]


# ---------------------------------------------------------------------------
# PerAxisHysteresisDowngradePolicy
# ---------------------------------------------------------------------------


def test_per_axis_implements_protocol() -> None:
    policy = PerAxisHysteresisDowngradePolicy()
    assert isinstance(policy, CalibrationAdjustmentPolicy)


def test_per_axis_policy_id_includes_parameters() -> None:
    p1 = PerAxisHysteresisDowngradePolicy(upper_mahalanobis=3.0)
    p2 = PerAxisHysteresisDowngradePolicy(upper_mahalanobis=5.0)
    assert p1.policy_id != p2.policy_id
    assert "per_axis_hysteresis_v1" in p1.policy_id


def test_per_axis_rejects_negative_min_outcomes() -> None:
    with pytest.raises(ValueError, match="min_outcomes must be >= 0"):
        PerAxisHysteresisDowngradePolicy(min_outcomes=-1)


def test_per_axis_rejects_non_positive_upper() -> None:
    with pytest.raises(ValueError, match="upper_mahalanobis must be > 0"):
        PerAxisHysteresisDowngradePolicy(upper_mahalanobis=0.0)


def test_per_axis_rejects_lower_above_upper() -> None:
    with pytest.raises(ValueError, match="must be <= upper_mahalanobis"):
        PerAxisHysteresisDowngradePolicy(upper_mahalanobis=2.0, lower_mahalanobis=3.0)


def test_per_axis_empty_history_is_passthrough() -> None:
    policy = PerAxisHysteresisDowngradePolicy()
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=0, dirty=0)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == raw.overall_level
    assert result.adjustment_reason == "no_outcomes_yet"


def test_per_axis_position_axis_triggers_downgrade() -> None:
    policy = PerAxisHysteresisDowngradePolicy(min_outcomes=2, upper_mahalanobis=3.0)
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=5, dirty=0, worst_position=4.5, worst_orientation=0.1)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN
    assert result.adjustment_reason == "downgrade_from_calibration"


def test_per_axis_orientation_axis_triggers_downgrade() -> None:
    policy = PerAxisHysteresisDowngradePolicy(min_outcomes=2, upper_mahalanobis=3.0)
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=5, dirty=0, worst_position=0.1, worst_orientation=4.5)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == SelfAssessmentLevel.UNCERTAIN


def test_per_axis_below_thresholds_is_within_tolerance() -> None:
    policy = PerAxisHysteresisDowngradePolicy(min_outcomes=2, upper_mahalanobis=3.0)
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=5, dirty=0, worst_position=1.5, worst_orientation=1.5)
    result = policy.adjust(raw, h)
    assert result.adjusted_overall_level == raw.overall_level
    assert result.adjustment_reason == "calibration_within_tolerance"


def test_per_axis_is_pure() -> None:
    policy = PerAxisHysteresisDowngradePolicy()
    raw = _make_raw_known()
    h = _make_history(outcomes_considered=5, dirty=0, worst_position=4.0, worst_orientation=0.1)
    r1 = policy.adjust(raw, h)
    r2 = policy.adjust(raw, h)
    assert r1 == r2


def test_per_axis_satisfies_md_monotonicity_under_random_input() -> None:
    # Seeded local rng — same pattern as test_ewma_satisfies_md above.
    rng = np.random.default_rng(43)
    policy = PerAxisHysteresisDowngradePolicy()
    raw = _make_raw_known()
    level_num = {
        SelfAssessmentLevel.KNOWN: 0,
        SelfAssessmentLevel.UNCERTAIN: 1,
        SelfAssessmentLevel.UNKNOWN: 2,
    }
    for _ in range(50):
        n = int(rng.integers(0, 33))
        dirty = int(rng.integers(0, n + 1))
        wp = float(rng.uniform(0.0, 10.0))
        wo = float(rng.uniform(0.0, 10.0))
        h = _make_history(
            outcomes_considered=n,
            dirty=dirty,
            worst_position=wp,
            worst_orientation=wo,
        )
        result = policy.adjust(raw, h)
        assert level_num[result.adjusted_overall_level] >= level_num[raw.overall_level]
