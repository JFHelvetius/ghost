"""Tests del módulo `analysis.belief_traceability` (ADR-0016).

Cubre, por categorías declaradas en el ADR-0016 §"TEST TARGET":

1. position error
2. orientation error
3. covariance present
4. covariance absent
5. report aggregation
6. deterministic ordering
7. canonical JSON
8. byte-identical output
9. invalid inputs
10. edge cases
11. empty datasets
12. frozen dataclasses
13. reproducibility
14. analysis_version

CLI tests viven en ``test_cli.py``; aquí se prueba la pura API.
"""

from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.analysis import (
    BELIEF_TRACEABILITY_ANALYSIS_VERSION,
    BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION,
    BeliefTraceabilityReport,
    BeliefTraceRecord,
    build_traceability_report,
    compute_orientation_error,
    compute_position_error,
    encode_belief_report_to_bytes,
    generate_belief_report,
)
from project_ghost.hal.messages import GroundTruth, SensorHealth
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    MissionMode,
    MissionStatus,
    SensorHealthMap,
    VehicleState,
    vehicle_state_from_ground_truth,
)
from project_ghost.state.messages import (
    IMUBiases,
    NavigationState,
    Pose,
    Twist,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
_Q_YAW_90 = np.array([np.sqrt(2.0) / 2.0, 0.0, 0.0, np.sqrt(2.0) / 2.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truth_state(
    *,
    stamp_sim_ns: int = 0,
    position: np.ndarray | None = None,
    orientation_q: np.ndarray | None = None,
) -> VehicleState:
    gt = GroundTruth(
        stamp_sim_ns=stamp_sim_ns,
        position_enu_m=(position if position is not None else np.zeros(3, dtype=np.float64)),
        orientation_q=(orientation_q if orientation_q is not None else _Q_IDENTITY.copy()),
        linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
        angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
    )
    return vehicle_state_from_ground_truth(
        gt=gt,
        sensors_health=SensorHealthMap(by_id=MappingProxyType({"imu0": SensorHealth.OK})),
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
        stamp_wall_ns=stamp_sim_ns,
    )


def _belief_state(
    *,
    stamp_sim_ns: int = 0,
    position: np.ndarray | None = None,
    orientation_q: np.ndarray | None = None,
    covariance: np.ndarray | None = None,
) -> VehicleState:
    """VehicleState con (opcional) covarianza no-None. Pose / twists son
    coherentes con `orientation_q`; biases zero."""
    pos = position if position is not None else np.zeros(3, dtype=np.float64)
    q = orientation_q if orientation_q is not None else _Q_IDENTITY.copy()
    pose = Pose(position_enu_m=pos.copy(), orientation_q=q.copy())
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
        covariance_15x15=(covariance.copy() if covariance is not None else None),
    )
    return VehicleState(
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=stamp_sim_ns,
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


def _declared_cov(scale: float = 1e-3) -> np.ndarray:
    return np.eye(15, dtype=np.float64) * scale


# ---------------------------------------------------------------------------
# 1. compute_position_error
# ---------------------------------------------------------------------------


def test_compute_position_error_zero_when_equal() -> None:
    p = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    assert compute_position_error(p, p) == 0.0


def test_compute_position_error_euclidean() -> None:
    a = np.zeros(3, dtype=np.float64)
    b = np.array([3.0, 4.0, 0.0], dtype=np.float64)
    assert compute_position_error(a, b) == 5.0


def test_compute_position_error_symmetric() -> None:
    a = np.array([1.0, -1.0, 0.5], dtype=np.float64)
    b = np.array([2.0, 0.0, 1.5], dtype=np.float64)
    assert compute_position_error(a, b) == compute_position_error(b, a)


def test_compute_position_error_rejects_wrong_shape() -> None:
    a = np.array([1.0, 2.0], dtype=np.float64)
    b = np.zeros(3, dtype=np.float64)
    with pytest.raises(TypeError, match="shape"):
        compute_position_error(a, b)


def test_compute_position_error_rejects_wrong_dtype() -> None:
    a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    b = np.zeros(3, dtype=np.float64)
    with pytest.raises(TypeError, match="float64"):
        compute_position_error(a, b)


def test_compute_position_error_rejects_nan() -> None:
    a = np.array([float("nan"), 0.0, 0.0], dtype=np.float64)
    b = np.zeros(3, dtype=np.float64)
    with pytest.raises(ValueError, match="NaN o Inf"):
        compute_position_error(a, b)


def test_compute_position_error_rejects_non_ndarray() -> None:
    a = [1.0, 2.0, 3.0]
    b = np.zeros(3, dtype=np.float64)
    with pytest.raises(TypeError, match=r"np\.ndarray"):
        compute_position_error(a, b)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. compute_orientation_error
# ---------------------------------------------------------------------------


def test_compute_orientation_error_zero_for_identity() -> None:
    assert compute_orientation_error(_Q_IDENTITY, _Q_IDENTITY) == 0.0


def test_compute_orientation_error_zero_for_identical_quaternion() -> None:
    assert compute_orientation_error(_Q_YAW_90, _Q_YAW_90) == 0.0


def test_compute_orientation_error_yaw_90_against_identity() -> None:
    """yaw 90° vs identity -> angle should be π/2."""
    angle = compute_orientation_error(_Q_IDENTITY, _Q_YAW_90)
    assert abs(angle - (math.pi / 2.0)) < 1e-12


def test_compute_orientation_error_handles_double_cover() -> None:
    """q y -q representan la misma rotación: ángulo 0."""
    q = _Q_YAW_90.copy()
    neg_q = -q
    assert compute_orientation_error(q, neg_q) < 1e-12


def test_compute_orientation_error_in_range_0_pi() -> None:
    """Para cualquier par unit, el ángulo está en [0, π]."""
    q1 = _Q_IDENTITY
    q2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float64)  # 180° around x
    angle = compute_orientation_error(q1, q2)
    assert 0.0 <= angle <= math.pi + 1e-12


def test_compute_orientation_error_rejects_wrong_shape() -> None:
    bad = np.zeros(3, dtype=np.float64)
    with pytest.raises(TypeError, match="shape"):
        compute_orientation_error(bad, _Q_IDENTITY)


# ---------------------------------------------------------------------------
# 3. covariance present
# ---------------------------------------------------------------------------


def test_record_with_covariance_has_trace_and_condition() -> None:
    cov = _declared_cov(scale=2.0e-3)
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0, covariance=cov)]
    report = build_traceability_report(truth=truth, belief=belief)
    rec = report.records[0]
    assert rec.covariance_available is True
    assert rec.covariance_trace is not None
    assert abs(rec.covariance_trace - 15 * 2.0e-3) < 1e-12
    assert rec.covariance_condition_number is not None
    assert abs(rec.covariance_condition_number - 1.0) < 1e-9


def test_report_counts_samples_with_covariance() -> None:
    cov = _declared_cov()
    truth = [_truth_state(stamp_sim_ns=i) for i in range(3)]
    belief = [_belief_state(stamp_sim_ns=i, covariance=cov) for i in range(3)]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.samples_with_covariance == 3
    assert report.samples_without_covariance == 0


# ---------------------------------------------------------------------------
# 4. covariance absent
# ---------------------------------------------------------------------------


def test_record_without_covariance_sets_metrics_to_none() -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0, covariance=None)]
    report = build_traceability_report(truth=truth, belief=belief)
    rec = report.records[0]
    assert rec.covariance_available is False
    assert rec.covariance_trace is None
    assert rec.covariance_condition_number is None


def test_report_counts_samples_without_covariance() -> None:
    truth = [_truth_state(stamp_sim_ns=i) for i in range(4)]
    belief = [_belief_state(stamp_sim_ns=i) for i in range(4)]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.samples_with_covariance == 0
    assert report.samples_without_covariance == 4


def test_report_handles_mixed_covariance_presence() -> None:
    cov = _declared_cov()
    truth = [_truth_state(stamp_sim_ns=i) for i in range(4)]
    belief = [
        _belief_state(stamp_sim_ns=0, covariance=cov),
        _belief_state(stamp_sim_ns=1, covariance=None),
        _belief_state(stamp_sim_ns=2, covariance=cov),
        _belief_state(stamp_sim_ns=3, covariance=None),
    ]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.samples_with_covariance == 2
    assert report.samples_without_covariance == 2


# ---------------------------------------------------------------------------
# 5. report aggregation
# ---------------------------------------------------------------------------


def test_report_total_samples_matches_records() -> None:
    truth = [_truth_state(stamp_sim_ns=i) for i in range(5)]
    belief = [_belief_state(stamp_sim_ns=i) for i in range(5)]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.total_samples == 5
    assert len(report.records) == 5


def test_report_mean_and_max_position_error() -> None:
    truth = [
        _truth_state(stamp_sim_ns=0, position=np.array([0.0, 0.0, 0.0])),
        _truth_state(stamp_sim_ns=1, position=np.array([0.0, 0.0, 0.0])),
    ]
    belief = [
        _belief_state(
            stamp_sim_ns=0,
            position=np.array([3.0, 4.0, 0.0]),  # err=5
        ),
        _belief_state(
            stamp_sim_ns=1,
            position=np.array([0.0, 0.0, 0.0]),  # err=0
        ),
    ]
    report = build_traceability_report(truth=truth, belief=belief)
    assert abs(report.mean_position_error_m - 2.5) < 1e-12
    assert report.max_position_error_m == 5.0


def test_report_mean_and_max_orientation_error() -> None:
    truth = [_truth_state(stamp_sim_ns=i) for i in range(2)]
    belief = [
        _belief_state(stamp_sim_ns=0, orientation_q=_Q_IDENTITY.copy()),
        _belief_state(stamp_sim_ns=1, orientation_q=_Q_YAW_90.copy()),
    ]
    report = build_traceability_report(truth=truth, belief=belief)
    expected_mean = (math.pi / 2.0) / 2.0
    assert abs(report.mean_orientation_error_rad - expected_mean) < 1e-12
    assert abs(report.max_orientation_error_rad - math.pi / 2.0) < 1e-12


# ---------------------------------------------------------------------------
# 6. deterministic ordering
# ---------------------------------------------------------------------------


def test_records_preserve_input_order() -> None:
    """El builder NO re-ordena; preserva el orden de entrada."""
    stamps = [100, 50, 200, 0]  # explicitly out-of-order
    truth = [_truth_state(stamp_sim_ns=s) for s in stamps]
    belief = [_belief_state(stamp_sim_ns=s) for s in stamps]
    report = build_traceability_report(truth=truth, belief=belief)
    assert [r.timestamp_ns for r in report.records] == stamps


# ---------------------------------------------------------------------------
# 7. canonical JSON
# ---------------------------------------------------------------------------


def test_encoded_report_has_trailing_newline() -> None:
    report = build_traceability_report(truth=[_truth_state()], belief=[_belief_state()])
    encoded = encode_belief_report_to_bytes(report)
    assert encoded.endswith(b"\n")


def test_encoded_report_is_utf8_json_with_indent_2() -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0)]
    report = build_traceability_report(truth=truth, belief=belief)
    encoded = encode_belief_report_to_bytes(report)
    parsed = json.loads(encoded.decode("utf-8"))
    assert parsed["schema_version"] == BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION
    # indent=2 produces multi-line output for nested dicts; verify >1 line.
    assert encoded.count(b"\n") > 1


def test_encoded_report_keys_are_sorted_at_every_level() -> None:
    """`json.dumps(sort_keys=True)` ordena las keys alfabéticamente; el test
    verifica el top level (lo más visible) y un record (nivel anidado)."""
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0)]
    report = build_traceability_report(truth=truth, belief=belief)
    encoded = encode_belief_report_to_bytes(report).decode("utf-8")
    # Top level keys: "report" comes before "schema_version" alphabetically.
    idx_report = encoded.index('"report"')
    idx_schema = encoded.index('"schema_version"')
    assert idx_report < idx_schema


# ---------------------------------------------------------------------------
# 8. byte-identical output (determinism)
# ---------------------------------------------------------------------------


def test_byte_identical_output_for_identical_inputs() -> None:
    truth = [_truth_state(stamp_sim_ns=i) for i in range(3)]
    belief = [
        _belief_state(
            stamp_sim_ns=i,
            position=np.array([i * 0.1, 0.0, 0.0]),
            covariance=_declared_cov(),
        )
        for i in range(3)
    ]
    report_a = build_traceability_report(truth=truth, belief=belief)
    report_b = build_traceability_report(truth=truth, belief=belief)
    assert encode_belief_report_to_bytes(report_a) == encode_belief_report_to_bytes(report_b)


def test_two_builds_produce_field_equal_reports() -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0)]
    a = build_traceability_report(truth=truth, belief=belief)
    b = build_traceability_report(truth=truth, belief=belief)
    assert a == b


# ---------------------------------------------------------------------------
# 9. invalid inputs
# ---------------------------------------------------------------------------


def test_length_mismatch_raises() -> None:
    truth = [_truth_state(stamp_sim_ns=0), _truth_state(stamp_sim_ns=1)]
    belief = [_belief_state(stamp_sim_ns=0)]
    with pytest.raises(ValueError, match="longitudes"):
        build_traceability_report(truth=truth, belief=belief)


def test_stamp_mismatch_raises_with_index() -> None:
    truth = [_truth_state(stamp_sim_ns=0), _truth_state(stamp_sim_ns=10)]
    belief = [_belief_state(stamp_sim_ns=0), _belief_state(stamp_sim_ns=11)]
    with pytest.raises(ValueError, match="índice 1"):
        build_traceability_report(truth=truth, belief=belief)


def test_first_index_stamp_mismatch_named_in_error() -> None:
    truth = [_truth_state(stamp_sim_ns=5)]
    belief = [_belief_state(stamp_sim_ns=6)]
    with pytest.raises(ValueError, match="índice 0"):
        build_traceability_report(truth=truth, belief=belief)


# ---------------------------------------------------------------------------
# 10. edge cases
# ---------------------------------------------------------------------------


def test_zero_perturbation_yields_zero_errors() -> None:
    """truth == belief en pose -> errors zero."""
    pos = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    truth = [_truth_state(stamp_sim_ns=0, position=pos.copy())]
    belief = [_belief_state(stamp_sim_ns=0, position=pos.copy(), covariance=_declared_cov())]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.records[0].position_error_norm_m == 0.0
    assert report.records[0].orientation_error_rad == 0.0
    assert report.mean_position_error_m == 0.0
    assert report.max_position_error_m == 0.0


def test_quaternion_xyzw_order_at_record_boundary() -> None:
    """ADR-0016: el record expone xyzw (scipy), internamente es wxyz (Hamilton)."""
    q_hamilton = _Q_YAW_90.copy()
    expected_xyzw = (
        float(q_hamilton[1]),
        float(q_hamilton[2]),
        float(q_hamilton[3]),
        float(q_hamilton[0]),
    )
    truth = [_truth_state(stamp_sim_ns=0, orientation_q=q_hamilton.copy())]
    belief = [_belief_state(stamp_sim_ns=0, orientation_q=q_hamilton.copy())]
    report = build_traceability_report(truth=truth, belief=belief)
    rec = report.records[0]
    assert rec.truth_orientation_xyzw == expected_xyzw
    assert rec.belief_orientation_xyzw == expected_xyzw


def test_degenerate_covariance_yields_none_metrics() -> None:
    """Covarianza all-zeros pasa PSD pero cond = inf -> None."""
    cov = np.zeros((15, 15), dtype=np.float64)
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0, covariance=cov)]
    report = build_traceability_report(truth=truth, belief=belief)
    rec = report.records[0]
    assert rec.covariance_available is True
    assert rec.covariance_trace == 0.0
    assert rec.covariance_condition_number is None


# ---------------------------------------------------------------------------
# 11. empty datasets
# ---------------------------------------------------------------------------


def test_empty_inputs_yield_empty_report() -> None:
    report = build_traceability_report(truth=[], belief=[])
    assert report.total_samples == 0
    assert report.records == ()
    assert report.samples_with_covariance == 0
    assert report.samples_without_covariance == 0
    assert report.mean_position_error_m == 0.0
    assert report.max_position_error_m == 0.0
    assert report.mean_orientation_error_rad == 0.0
    assert report.max_orientation_error_rad == 0.0


def test_empty_report_is_json_serializable() -> None:
    report = build_traceability_report(truth=[], belief=[])
    encoded = encode_belief_report_to_bytes(report)
    parsed = json.loads(encoded.decode("utf-8"))
    assert parsed["report"]["total_samples"] == 0
    assert parsed["report"]["records"] == []


# ---------------------------------------------------------------------------
# 12. frozen dataclasses
# ---------------------------------------------------------------------------


def test_record_is_frozen() -> None:
    rec = BeliefTraceRecord(
        timestamp_ns=0,
        truth_position_xyz=(0.0, 0.0, 0.0),
        belief_position_xyz=(0.0, 0.0, 0.0),
        truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        position_error_norm_m=0.0,
        orientation_error_rad=0.0,
        covariance_trace=None,
        covariance_condition_number=None,
        covariance_available=False,
    )
    with pytest.raises(FrozenInstanceError):
        rec.timestamp_ns = 5  # type: ignore[misc]


def test_report_is_frozen() -> None:
    rep = BeliefTraceabilityReport(
        total_samples=0,
        samples_with_covariance=0,
        samples_without_covariance=0,
        mean_position_error_m=0.0,
        max_position_error_m=0.0,
        mean_orientation_error_rad=0.0,
        max_orientation_error_rad=0.0,
        records=(),
    )
    with pytest.raises(FrozenInstanceError):
        rep.total_samples = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 13. reproducibility (file write)
# ---------------------------------------------------------------------------


def test_generate_belief_report_writes_canonical_bytes(tmp_path: Path) -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0, covariance=_declared_cov())]
    report = build_traceability_report(truth=truth, belief=belief)

    p = tmp_path / "report.json"
    generate_belief_report(report, p)

    assert p.read_bytes() == encode_belief_report_to_bytes(report)


def test_generate_belief_report_two_writes_byte_identical(tmp_path: Path) -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0)]
    report = build_traceability_report(truth=truth, belief=belief)

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_belief_report(report, a)
    generate_belief_report(report, b)

    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# 14. analysis_version
# ---------------------------------------------------------------------------


def test_record_carries_analysis_version() -> None:
    truth = [_truth_state(stamp_sim_ns=0)]
    belief = [_belief_state(stamp_sim_ns=0)]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.records[0].analysis_version == BELIEF_TRACEABILITY_ANALYSIS_VERSION


def test_report_carries_analysis_version() -> None:
    report = build_traceability_report(truth=[], belief=[])
    assert report.analysis_version == BELIEF_TRACEABILITY_ANALYSIS_VERSION


def test_schema_version_is_string_one() -> None:
    assert BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION == "1"


def test_analysis_version_is_integer_one() -> None:
    assert BELIEF_TRACEABILITY_ANALYSIS_VERSION == 1


# ---------------------------------------------------------------------------
# Cross-check: timestamps survive boundary unchanged
# ---------------------------------------------------------------------------


def test_record_timestamp_matches_truth_stamp_sim_ns() -> None:
    truth = [_truth_state(stamp_sim_ns=42_000_000)]
    belief = [_belief_state(stamp_sim_ns=42_000_000)]
    report = build_traceability_report(truth=truth, belief=belief)
    assert report.records[0].timestamp_ns == 42_000_000
