"""Tests del módulo `analysis.self_assessment` (ADR-0020 offline).

Cubre:

- ``summarize_self_assessments`` con records vacíos / mixtos.
- ``LevelCounts`` validación y semantic.
- ``SelfAssessmentSummary`` invariantes y frozen.
- ``read_self_assessments_from_mcap`` (round-trip lectura).
- Encoder / decoder round-trip.
- JSON canonical encoding (sort_keys, indent, trailing newline).
- Determinismo.
- Schema / analysis_version validation.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.analysis import (
    SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION,
    LevelCounts,
    SelfAssessmentSummary,
    decode_self_assessment_summary_from_json,
    encode_self_assessment_summary_to_bytes,
    generate_self_assessment_summary,
    read_self_assessments_from_mcap,
    summarize_self_assessments,
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
    MCAPFileSink,
    SelfAssessmentToTelemetryAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(
    *,
    stamp_sim_ns: int = 0,
    pos_var: float = 1e-4,
    vel_var: float = 1e-4,
    ori_var: float = 1e-4,
) -> VehicleState:
    diag = np.array(
        [pos_var] * 3
        + [vel_var] * 3
        + [ori_var] * 3
        + [1e-6] * 3
        + [1e-6] * 3,
        dtype=np.float64,
    )
    cov = np.diag(diag)
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


# ---------------------------------------------------------------------------
# LevelCounts
# ---------------------------------------------------------------------------


def test_level_counts_total() -> None:
    c = LevelCounts(known=3, uncertain=2, unknown=1)
    assert c.total() == 6


def test_level_counts_rejects_negative() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        LevelCounts(known=-1, uncertain=0, unknown=0)


# ---------------------------------------------------------------------------
# summarize_self_assessments
# ---------------------------------------------------------------------------


def test_empty_summary() -> None:
    summary = summarize_self_assessments(())
    assert summary.total_records == 0
    assert summary.position_counts.total() == 0
    assert summary.velocity_counts.total() == 0
    assert summary.orientation_counts.total() == 0
    assert summary.overall_counts.total() == 0
    assert summary.timestamp_first_ns is None
    assert summary.timestamp_last_ns is None
    assert summary.timestamp_span_ns is None
    assert summary.distinct_thresholds_sha256 == ()


def test_summary_counts_levels_correctly() -> None:
    t = _make_thresholds()
    # Three records: all KNOWN, all UNCERTAIN, all UNKNOWN (in position
    # at least; we drive the overall via position since others are KNOWN).
    a_known = assess_belief(_make_state(pos_var=1e-4), t)
    a_uncertain = assess_belief(_make_state(pos_var=0.04), t)
    a_unknown = assess_belief(_make_state(pos_var=1.0), t)
    summary = summarize_self_assessments((a_known, a_uncertain, a_unknown))
    assert summary.position_counts.known == 1
    assert summary.position_counts.uncertain == 1
    assert summary.position_counts.unknown == 1
    # overall mirrors position because velocity/orientation are KNOWN here:
    # known record → overall KNOWN
    # uncertain record → overall UNCERTAIN (uncertain pos, KNOWN others)
    # unknown record → overall UNKNOWN
    assert summary.overall_counts.known == 1
    assert summary.overall_counts.uncertain == 1
    assert summary.overall_counts.unknown == 1


def test_summary_timestamps_use_min_max() -> None:
    t = _make_thresholds()
    records = (
        assess_belief(_make_state(stamp_sim_ns=500), t),
        assess_belief(_make_state(stamp_sim_ns=100), t),
        assess_belief(_make_state(stamp_sim_ns=300), t),
    )
    summary = summarize_self_assessments(records)
    assert summary.timestamp_first_ns == 100
    assert summary.timestamp_last_ns == 500
    assert summary.timestamp_span_ns == 400


def test_summary_distinct_thresholds_when_homogeneous() -> None:
    t = _make_thresholds()
    records = tuple(
        assess_belief(_make_state(stamp_sim_ns=i), t) for i in range(3)
    )
    summary = summarize_self_assessments(records)
    assert len(summary.distinct_thresholds_sha256) == 1


def test_summary_distinct_thresholds_when_heterogeneous() -> None:
    """Two distinct AssessmentThresholds produce two distinct hashes
    in the summary — an honest observational signal."""
    t_a = _make_thresholds()
    t_b = AssessmentThresholds(
        position_known_std_m=0.1,  # different
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    records = (
        assess_belief(_make_state(stamp_sim_ns=0), t_a),
        assess_belief(_make_state(stamp_sim_ns=1), t_b),
    )
    summary = summarize_self_assessments(records)
    assert len(summary.distinct_thresholds_sha256) == 2


# ---------------------------------------------------------------------------
# SelfAssessmentSummary invariants
# ---------------------------------------------------------------------------


def test_summary_rejects_count_mismatch() -> None:
    with pytest.raises(ValueError, match="must equal total_records"):
        SelfAssessmentSummary(
            total_records=5,
            position_counts=LevelCounts(known=1, uncertain=0, unknown=0),
            velocity_counts=LevelCounts(known=5, uncertain=0, unknown=0),
            orientation_counts=LevelCounts(known=5, uncertain=0, unknown=0),
            overall_counts=LevelCounts(known=5, uncertain=0, unknown=0),
            timestamp_first_ns=0,
            timestamp_last_ns=4,
            timestamp_span_ns=4,
            distinct_thresholds_sha256=("a" * 64,),
        )


def test_summary_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    s = summarize_self_assessments(())
    with pytest.raises(FrozenInstanceError):
        s.total_records = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# JSON canonical encoding
# ---------------------------------------------------------------------------


def test_encoded_summary_trailing_newline() -> None:
    s = summarize_self_assessments(())
    assert encode_self_assessment_summary_to_bytes(s).endswith(b"\n")


def test_encoded_summary_indent_2() -> None:
    s = summarize_self_assessments(())
    encoded = encode_self_assessment_summary_to_bytes(s)
    assert encoded.count(b"\n") > 1


def test_encoded_summary_keys_sorted() -> None:
    s = summarize_self_assessments(())
    encoded = encode_self_assessment_summary_to_bytes(s).decode("utf-8")
    idx_schema = encoded.index('"schema_version"')
    idx_summary = encoded.index('"summary"')
    assert idx_schema < idx_summary  # alphabetical


def test_encoded_summary_envelope_structure() -> None:
    s = summarize_self_assessments(())
    parsed = json.loads(
        encode_self_assessment_summary_to_bytes(s).decode("utf-8")
    )
    assert (
        parsed["schema_version"]
        == SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION
    )
    assert "summary" in parsed


# ---------------------------------------------------------------------------
# Determinism + round-trip
# ---------------------------------------------------------------------------


def test_two_encodings_byte_identical() -> None:
    t = _make_thresholds()
    records = tuple(
        assess_belief(_make_state(stamp_sim_ns=i), t) for i in range(3)
    )
    summary = summarize_self_assessments(records)
    a = encode_self_assessment_summary_to_bytes(summary)
    b = encode_self_assessment_summary_to_bytes(summary)
    assert a == b


def test_round_trip_preserves_summary() -> None:
    t = _make_thresholds()
    records = tuple(
        assess_belief(_make_state(stamp_sim_ns=i * 100, pos_var=0.04), t)
        for i in range(4)
    )
    original = summarize_self_assessments(records)
    encoded = encode_self_assessment_summary_to_bytes(original)
    decoded = decode_self_assessment_summary_from_json(
        json.loads(encoded.decode("utf-8"))
    )
    assert decoded == original


# ---------------------------------------------------------------------------
# Schema mismatch
# ---------------------------------------------------------------------------


def test_decode_schema_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        decode_self_assessment_summary_from_json(
            {"schema_version": "999", "summary": {}}
        )


def test_decode_missing_schema_raises() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        decode_self_assessment_summary_from_json({"summary": {}})


def test_decode_non_mapping_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_self_assessment_summary_from_json("not a dict")  # type: ignore[arg-type]


def test_decode_analysis_version_mismatch_raises() -> None:
    data = {
        "schema_version": SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION,
        "summary": {
            "analysis_version": 999,
            "total_records": 0,
            "position_counts": {
                "known": 0, "uncertain": 0, "unknown": 0,
            },
            "velocity_counts": {
                "known": 0, "uncertain": 0, "unknown": 0,
            },
            "orientation_counts": {
                "known": 0, "uncertain": 0, "unknown": 0,
            },
            "overall_counts": {
                "known": 0, "uncertain": 0, "unknown": 0,
            },
            "timestamp_first_ns": None,
            "timestamp_last_ns": None,
            "timestamp_span_ns": None,
            "distinct_thresholds_sha256": [],
        },
    }
    with pytest.raises(ValueError, match="analysis_version"):
        decode_self_assessment_summary_from_json(data)


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------


def test_generate_summary_writes_canonical_bytes(tmp_path: Path) -> None:
    s = summarize_self_assessments(())
    p = tmp_path / "summary.json"
    generate_self_assessment_summary(s, p)
    assert p.read_bytes() == encode_self_assessment_summary_to_bytes(s)


# ---------------------------------------------------------------------------
# read_self_assessments_from_mcap (round-trip via real MCAP)
# ---------------------------------------------------------------------------


def test_read_self_assessments_from_mcap_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "sa.mcap"
    t = _make_thresholds()
    originals = tuple(
        assess_belief(_make_state(stamp_sim_ns=i * 1000), t)
        for i in range(3)
    )
    with MCAPFileSink(p) as sink:
        adapter = SelfAssessmentToTelemetryAdapter(sink)
        for a in originals:
            adapter.publish(a)

    read = read_self_assessments_from_mcap(p)
    assert read == originals


def test_read_self_assessments_from_mcap_filters_by_channel(
    tmp_path: Path,
) -> None:
    """Solo records publicados en `/self_assessment` se devuelven; otros
    canales se ignoran. Aquí publicamos al canal default y al canal
    custom; sólo los del default deben aparecer."""
    p = tmp_path / "sa.mcap"
    t = _make_thresholds()
    a_default = assess_belief(_make_state(stamp_sim_ns=100), t)
    a_custom = assess_belief(_make_state(stamp_sim_ns=200), t)
    with MCAPFileSink(p) as sink:
        SelfAssessmentToTelemetryAdapter(sink).publish(a_default)
        SelfAssessmentToTelemetryAdapter(
            sink, channel="/other/sa"
        ).publish(a_custom)

    read = read_self_assessments_from_mcap(p)
    assert len(read) == 1
    assert read[0] == a_default
