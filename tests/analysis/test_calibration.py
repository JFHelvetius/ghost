"""Tests del módulo `analysis.calibration` (ADR-0019).

Cubre:

- Validación de SHA-256 source (formato, longitud, hex).
- Per-record honesty audit:
  * registros usables (covariance_available=True, trace>0)
  * registros sin covarianza
  * registros con trace=None
  * registros con trace=0 (rechazado por sqrt indefinido / división por 0)
  * registros con trace<0 (rechazado defensivamente)
- Cálculos:
  * sqrt_trace == sqrt(trace)
  * position_ratio == position_error_norm_m / sqrt_trace
  * orientation_ratio == orientation_error_rad / sqrt_trace
- Agregados:
  * min/max/mean correctos sobre records usables
  * empty / all-unusable → None
  * mixto (algunos usables, otros no) → cuentas correctas
- BeliefCalibrationReport invariants (frozen, validación de SHA,
  total_records vs len(records), suma de cuentas).
- JSON canonical encoding (sort_keys, indent=2, trailing newline, UTF-8).
- Determinism (byte-identical, SHA-256 estable).
- Round-trip encode→decode.
- Schema / analysis_version validation en decoder.
- File writer.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from project_ghost.analysis import (
    BELIEF_CALIBRATION_ANALYSIS_VERSION,
    BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
    BeliefCalibrationRecord,
    BeliefCalibrationReport,
    BeliefTraceabilityReport,
    BeliefTraceRecord,
    analyze_belief_calibration,
    decode_calibration_report_from_json,
    encode_calibration_report_to_bytes,
    generate_calibration_report,
)

if TYPE_CHECKING:
    from pathlib import Path


_DUMMY_SHA = "a" * 64
_DUMMY_SHA_B = "b" * 64


def _record(
    *,
    timestamp_ns: int = 0,
    position_error_norm_m: float = 0.0,
    orientation_error_rad: float = 0.0,
    covariance_trace: float | None = None,
    covariance_condition_number: float | None = None,
    covariance_available: bool = False,
) -> BeliefTraceRecord:
    return BeliefTraceRecord(
        timestamp_ns=timestamp_ns,
        truth_position_xyz=(0.0, 0.0, 0.0),
        belief_position_xyz=(0.0, 0.0, 0.0),
        truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        position_error_norm_m=position_error_norm_m,
        orientation_error_rad=orientation_error_rad,
        covariance_trace=covariance_trace,
        covariance_condition_number=covariance_condition_number,
        covariance_available=covariance_available,
    )


def _report(records: tuple[BeliefTraceRecord, ...] = ()) -> BeliefTraceabilityReport:
    n = len(records)
    with_cov = sum(1 for r in records if r.covariance_available)
    pos_errs = [r.position_error_norm_m for r in records]
    ori_errs = [r.orientation_error_rad for r in records]
    return BeliefTraceabilityReport(
        total_samples=n,
        samples_with_covariance=with_cov,
        samples_without_covariance=n - with_cov,
        mean_position_error_m=(sum(pos_errs) / n) if n else 0.0,
        max_position_error_m=max(pos_errs) if n else 0.0,
        mean_orientation_error_rad=(sum(ori_errs) / n) if n else 0.0,
        max_orientation_error_rad=max(ori_errs) if n else 0.0,
        records=records,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_analysis_version_constant_is_one() -> None:
    assert BELIEF_CALIBRATION_ANALYSIS_VERSION == 1


def test_schema_version_constant_is_one() -> None:
    assert BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION == "1"


# ---------------------------------------------------------------------------
# SHA-256 validation
# ---------------------------------------------------------------------------


def test_analyze_rejects_short_sha() -> None:
    with pytest.raises(ValueError, match="hex chars"):
        analyze_belief_calibration(_report(), source_belief_report_sha256="abc")


def test_analyze_rejects_uppercase_sha() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        analyze_belief_calibration(_report(), source_belief_report_sha256="A" * 64)


def test_analyze_rejects_non_hex_sha() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        analyze_belief_calibration(_report(), source_belief_report_sha256="g" * 64)


def test_analyze_rejects_non_string_sha() -> None:
    with pytest.raises(TypeError, match="must be str"):
        analyze_belief_calibration(
            _report(),
            source_belief_report_sha256=42,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Per-record: usable vs not usable
# ---------------------------------------------------------------------------


def test_record_with_covariance_available_and_positive_trace_is_usable() -> None:
    rec = _record(
        position_error_norm_m=0.5,
        orientation_error_rad=0.1,
        covariance_trace=0.04,
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].usable_for_calibration is True


def test_record_without_covariance_is_not_usable() -> None:
    rec = _record(
        position_error_norm_m=0.5,
        covariance_available=False,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    rec_out = cal.records[0]
    assert rec_out.usable_for_calibration is False
    assert rec_out.covariance_sqrt_trace is None
    assert rec_out.position_error_to_uncertainty_ratio is None
    assert rec_out.orientation_error_to_uncertainty_ratio is None


def test_record_with_covariance_available_but_trace_none_is_not_usable() -> None:
    """ADR-0016 collapses non-finite traces to None even when
    covariance_available=True. ADR-0019 must treat them as unusable."""
    rec = _record(
        covariance_available=True,
        covariance_trace=None,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].usable_for_calibration is False
    assert cal.records[0].position_error_to_uncertainty_ratio is None


def test_record_with_zero_trace_is_not_usable() -> None:
    rec = _record(
        covariance_available=True,
        covariance_trace=0.0,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].usable_for_calibration is False


def test_record_with_negative_trace_is_not_usable() -> None:
    """Defensive: PSD covariance shouldn't yield negative trace, but if
    somehow it does, we refuse to take sqrt."""
    rec = _record(
        covariance_available=True,
        covariance_trace=-1.0,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].usable_for_calibration is False


# ---------------------------------------------------------------------------
# Ratio math
# ---------------------------------------------------------------------------


def test_sqrt_trace_is_sqrt_of_trace() -> None:
    rec = _record(covariance_trace=0.25, covariance_available=True)
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].covariance_sqrt_trace == 0.5


def test_position_ratio_is_error_div_sqrt_trace() -> None:
    rec = _record(
        position_error_norm_m=1.0,
        covariance_trace=0.04,  # sqrt = 0.2
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    ratio = cal.records[0].position_error_to_uncertainty_ratio
    assert ratio is not None
    assert abs(ratio - 5.0) < 1e-12


def test_orientation_ratio_is_error_div_sqrt_trace() -> None:
    rec = _record(
        orientation_error_rad=0.6,
        covariance_trace=0.04,  # sqrt = 0.2
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    ratio = cal.records[0].orientation_error_to_uncertainty_ratio
    assert ratio is not None
    assert abs(ratio - 3.0) < 1e-12


def test_zero_error_yields_zero_ratio() -> None:
    rec = _record(
        position_error_norm_m=0.0,
        orientation_error_rad=0.0,
        covariance_trace=1.0,
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].position_error_to_uncertainty_ratio == 0.0
    assert cal.records[0].orientation_error_to_uncertainty_ratio == 0.0


def test_passthrough_position_error_and_orientation_error_and_trace() -> None:
    rec = _record(
        position_error_norm_m=0.42,
        orientation_error_rad=0.123,
        covariance_trace=0.01,
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    out = cal.records[0]
    assert out.position_error_norm_m == 0.42
    assert out.orientation_error_rad == 0.123
    assert out.covariance_trace == 0.01


def test_passthrough_trace_when_unusable() -> None:
    """Even unusable records carry the source trace as passthrough."""
    rec = _record(
        covariance_trace=None,
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records[0].covariance_trace is None


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_empty_report_has_zero_counts_and_none_aggregates() -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.total_records == 0
    assert cal.records_usable_for_calibration == 0
    assert cal.records_not_usable == 0
    assert cal.position_error_to_uncertainty_ratio_min is None
    assert cal.position_error_to_uncertainty_ratio_max is None
    assert cal.position_error_to_uncertainty_ratio_mean is None
    assert cal.orientation_error_to_uncertainty_ratio_min is None
    assert cal.orientation_error_to_uncertainty_ratio_max is None
    assert cal.orientation_error_to_uncertainty_ratio_mean is None


def test_all_unusable_records_aggregates_are_none() -> None:
    recs = (
        _record(covariance_available=False),
        _record(covariance_available=True, covariance_trace=None),
        _record(covariance_available=True, covariance_trace=0.0),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.total_records == 3
    assert cal.records_usable_for_calibration == 0
    assert cal.records_not_usable == 3
    assert cal.position_error_to_uncertainty_ratio_min is None
    assert cal.position_error_to_uncertainty_ratio_mean is None


def test_ratio_aggregates_correct_for_usable_records() -> None:
    # Two usable records with known errors.
    recs = (
        _record(
            position_error_norm_m=1.0,
            orientation_error_rad=0.2,
            covariance_trace=0.25,  # sqrt = 0.5
            covariance_available=True,
        ),
        _record(
            position_error_norm_m=3.0,
            orientation_error_rad=0.6,
            covariance_trace=0.25,
            covariance_available=True,
        ),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    # Ratios: pos = (2.0, 6.0); ori = (0.4, 1.2)
    assert cal.position_error_to_uncertainty_ratio_min == 2.0
    assert cal.position_error_to_uncertainty_ratio_max == 6.0
    assert cal.position_error_to_uncertainty_ratio_mean == 4.0
    assert cal.orientation_error_to_uncertainty_ratio_min == 0.4
    assert cal.orientation_error_to_uncertainty_ratio_max == 1.2
    ori_mean = cal.orientation_error_to_uncertainty_ratio_mean
    assert ori_mean is not None
    assert abs(ori_mean - 0.8) < 1e-12


def test_mixed_records_count_correctly() -> None:
    recs = (
        _record(
            covariance_trace=0.04,
            covariance_available=True,
        ),
        _record(covariance_available=False),
        _record(
            covariance_trace=0.09,
            covariance_available=True,
        ),
        _record(covariance_available=True, covariance_trace=None),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.total_records == 4
    assert cal.records_usable_for_calibration == 2
    assert cal.records_not_usable == 2


def test_aggregates_ignore_unusable_records() -> None:
    """Aggregates must compute over usable records only."""
    recs = (
        _record(
            position_error_norm_m=10.0,
            covariance_trace=0.04,  # sqrt = 0.2; ratio = 50
            covariance_available=True,
        ),
        # Unusable record with very large hypothetical error — must not
        # affect aggregates.
        _record(
            position_error_norm_m=1e6,
            covariance_available=False,
        ),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.position_error_to_uncertainty_ratio_min == 50.0
    assert cal.position_error_to_uncertainty_ratio_max == 50.0
    assert cal.position_error_to_uncertainty_ratio_mean == 50.0


# ---------------------------------------------------------------------------
# BeliefCalibrationReport invariants
# ---------------------------------------------------------------------------


def test_calibration_report_total_records_matches_records_length() -> None:
    cal = analyze_belief_calibration(_report((_record(),)), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.total_records == len(cal.records)


def test_calibration_report_counts_sum_to_total() -> None:
    recs = (
        _record(covariance_trace=0.04, covariance_available=True),
        _record(covariance_available=False),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    assert cal.records_usable_for_calibration + cal.records_not_usable == cal.total_records


def test_calibration_report_is_frozen() -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    with pytest.raises(FrozenInstanceError):
        cal.total_records = 99  # type: ignore[misc]


def test_calibration_record_is_frozen() -> None:
    rec = BeliefCalibrationRecord(
        timestamp_ns=0,
        position_error_norm_m=0.0,
        orientation_error_rad=0.0,
        covariance_trace=None,
        covariance_sqrt_trace=None,
        position_error_to_uncertainty_ratio=None,
        orientation_error_to_uncertainty_ratio=None,
        usable_for_calibration=False,
    )
    with pytest.raises(FrozenInstanceError):
        rec.usable_for_calibration = True  # type: ignore[misc]


def test_calibration_report_validates_source_sha() -> None:
    with pytest.raises(ValueError, match="hex"):
        BeliefCalibrationReport(
            source_belief_report_sha256="not-a-hex",
            total_records=0,
            records_usable_for_calibration=0,
            records_not_usable=0,
            records=(),
            position_error_to_uncertainty_ratio_min=None,
            position_error_to_uncertainty_ratio_max=None,
            position_error_to_uncertainty_ratio_mean=None,
            orientation_error_to_uncertainty_ratio_min=None,
            orientation_error_to_uncertainty_ratio_max=None,
            orientation_error_to_uncertainty_ratio_mean=None,
        )


def test_calibration_report_rejects_total_records_mismatch() -> None:
    with pytest.raises(ValueError, match="total_records"):
        BeliefCalibrationReport(
            source_belief_report_sha256=_DUMMY_SHA,
            total_records=5,  # not matching len(records)=0
            records_usable_for_calibration=0,
            records_not_usable=0,
            records=(),
            position_error_to_uncertainty_ratio_min=None,
            position_error_to_uncertainty_ratio_max=None,
            position_error_to_uncertainty_ratio_mean=None,
            orientation_error_to_uncertainty_ratio_min=None,
            orientation_error_to_uncertainty_ratio_max=None,
            orientation_error_to_uncertainty_ratio_mean=None,
        )


def test_calibration_report_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="usable_for_calibration"):
        BeliefCalibrationReport(
            source_belief_report_sha256=_DUMMY_SHA,
            total_records=1,
            records_usable_for_calibration=3,  # inflated
            records_not_usable=0,
            records=(
                BeliefCalibrationRecord(
                    timestamp_ns=0,
                    position_error_norm_m=0.0,
                    orientation_error_rad=0.0,
                    covariance_trace=None,
                    covariance_sqrt_trace=None,
                    position_error_to_uncertainty_ratio=None,
                    orientation_error_to_uncertainty_ratio=None,
                    usable_for_calibration=False,
                ),
            ),
            position_error_to_uncertainty_ratio_min=None,
            position_error_to_uncertainty_ratio_max=None,
            position_error_to_uncertainty_ratio_mean=None,
            orientation_error_to_uncertainty_ratio_min=None,
            orientation_error_to_uncertainty_ratio_max=None,
            orientation_error_to_uncertainty_ratio_mean=None,
        )


def test_calibration_report_rejects_non_tuple_records() -> None:
    with pytest.raises(TypeError, match="tuple"):
        BeliefCalibrationReport(
            source_belief_report_sha256=_DUMMY_SHA,
            total_records=0,
            records_usable_for_calibration=0,
            records_not_usable=0,
            records=[],  # type: ignore[arg-type]
            position_error_to_uncertainty_ratio_min=None,
            position_error_to_uncertainty_ratio_max=None,
            position_error_to_uncertainty_ratio_mean=None,
            orientation_error_to_uncertainty_ratio_min=None,
            orientation_error_to_uncertainty_ratio_max=None,
            orientation_error_to_uncertainty_ratio_mean=None,
        )


# ---------------------------------------------------------------------------
# JSON canonical encoding
# ---------------------------------------------------------------------------


def test_encoded_report_has_trailing_newline() -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    assert encode_calibration_report_to_bytes(cal).endswith(b"\n")


def test_encoded_report_uses_indent_2() -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    encoded = encode_calibration_report_to_bytes(cal)
    assert encoded.count(b"\n") > 1


def test_encoded_report_keys_sorted() -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    encoded = encode_calibration_report_to_bytes(cal).decode("utf-8")
    # Top level keys: "calibration" precedes "schema_version" alphabetically
    idx_cal = encoded.index('"calibration"')
    idx_schema = encoded.index('"schema_version"')
    assert idx_cal < idx_schema


def test_encoded_report_envelope_structure() -> None:
    rec = _record(covariance_trace=0.04, covariance_available=True)
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    parsed = json.loads(encode_calibration_report_to_bytes(cal).decode("utf-8"))
    assert parsed["schema_version"] == BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION
    assert parsed["calibration"]["total_records"] == 1
    assert parsed["calibration"]["source_belief_report_sha256"] == _DUMMY_SHA


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_encodings_are_byte_identical() -> None:
    recs = (
        _record(
            position_error_norm_m=0.5,
            covariance_trace=0.04,
            covariance_available=True,
        ),
        _record(covariance_available=False),
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    a = encode_calibration_report_to_bytes(cal)
    b = encode_calibration_report_to_bytes(cal)
    assert a == b


def test_two_analyses_yield_equal_reports() -> None:
    rec = _record(
        position_error_norm_m=0.5,
        covariance_trace=0.04,
        covariance_available=True,
    )
    report = _report((rec,))
    a = analyze_belief_calibration(report, source_belief_report_sha256=_DUMMY_SHA)
    b = analyze_belief_calibration(report, source_belief_report_sha256=_DUMMY_SHA)
    assert a == b


def test_sha256_stable_across_repeated_encodings() -> None:
    recs = tuple(
        _record(
            timestamp_ns=i * 1000,
            position_error_norm_m=0.1 * i,
            orientation_error_rad=0.01 * i,
            covariance_trace=0.04,
            covariance_available=True,
        )
        for i in range(5)
    )
    cal = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    hashes = {hashlib.sha256(encode_calibration_report_to_bytes(cal)).hexdigest() for _ in range(5)}
    assert len(hashes) == 1


# ---------------------------------------------------------------------------
# Round-trip decoder
# ---------------------------------------------------------------------------


def test_round_trip_preserves_calibration_report() -> None:
    recs = (
        _record(
            position_error_norm_m=0.5,
            orientation_error_rad=0.1,
            covariance_trace=0.04,
            covariance_available=True,
        ),
        _record(covariance_available=False),
    )
    original = analyze_belief_calibration(_report(recs), source_belief_report_sha256=_DUMMY_SHA)
    encoded = encode_calibration_report_to_bytes(original)
    decoded = decode_calibration_report_from_json(json.loads(encoded.decode("utf-8")))
    assert decoded == original


def test_round_trip_preserves_source_sha() -> None:
    original = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA_B)
    encoded = encode_calibration_report_to_bytes(original)
    decoded = decode_calibration_report_from_json(json.loads(encoded.decode("utf-8")))
    assert decoded.source_belief_report_sha256 == _DUMMY_SHA_B


def test_decode_schema_version_mismatch_raises() -> None:
    data = {"schema_version": "999", "calibration": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_calibration_report_from_json(data)


def test_decode_missing_schema_version_raises() -> None:
    data: dict[str, object] = {"calibration": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_calibration_report_from_json(data)


def test_decode_missing_inner_raises() -> None:
    data = {"schema_version": BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION}
    with pytest.raises(ValueError, match="calibration"):
        decode_calibration_report_from_json(data)


def test_decode_non_mapping_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_calibration_report_from_json("not a mapping")  # type: ignore[arg-type]


def test_decode_non_mapping_inner_raises() -> None:
    data: dict[str, object] = {
        "schema_version": BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
        "calibration": [1, 2, 3],
    }
    with pytest.raises(TypeError, match="mapping"):
        decode_calibration_report_from_json(data)


def test_decode_analysis_version_mismatch_raises() -> None:
    data = {
        "schema_version": BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
        "calibration": {
            "analysis_version": 999,
            "source_belief_report_sha256": _DUMMY_SHA,
            "total_records": 0,
            "records_usable_for_calibration": 0,
            "records_not_usable": 0,
            "records": [],
            "position_error_to_uncertainty_ratio_min": None,
            "position_error_to_uncertainty_ratio_max": None,
            "position_error_to_uncertainty_ratio_mean": None,
            "orientation_error_to_uncertainty_ratio_min": None,
            "orientation_error_to_uncertainty_ratio_max": None,
            "orientation_error_to_uncertainty_ratio_mean": None,
        },
    }
    with pytest.raises(ValueError, match="analysis_version"):
        decode_calibration_report_from_json(data)


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------


def test_generate_writes_canonical_bytes(tmp_path: Path) -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    p = tmp_path / "cal.json"
    generate_calibration_report(cal, p)
    assert p.read_bytes() == encode_calibration_report_to_bytes(cal)


def test_generate_two_writes_byte_identical(tmp_path: Path) -> None:
    cal = analyze_belief_calibration(_report(), source_belief_report_sha256=_DUMMY_SHA)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_calibration_report(cal, a)
    generate_calibration_report(cal, b)
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# Honesty signal smoke test (descriptive, no verdict)
# ---------------------------------------------------------------------------


def test_overconfidence_signal_visible_in_ratio() -> None:
    """When the declared scale is tiny relative to the empirical error,
    the ratio is large. This test documents the intended signal but
    DOES NOT classify anything as 'overconfident'. The threshold is the
    operator's, not the system's."""
    rec = _record(
        position_error_norm_m=1.0,
        covariance_trace=1e-12,  # sqrt = 1e-6
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    ratio = cal.records[0].position_error_to_uncertainty_ratio
    assert ratio is not None
    # Just check the number is what algebra says — no verdict.
    assert math.isclose(ratio, 1.0 / math.sqrt(1e-12))


def test_well_scaled_signal_visible_in_ratio() -> None:
    """When the declared scale is comparable to the empirical error,
    the ratio is order-1. Same posture: no verdict, just the number."""
    rec = _record(
        position_error_norm_m=0.1,
        covariance_trace=0.01,  # sqrt = 0.1
        covariance_available=True,
    )
    cal = analyze_belief_calibration(_report((rec,)), source_belief_report_sha256=_DUMMY_SHA)
    ratio = cal.records[0].position_error_to_uncertainty_ratio
    assert ratio is not None
    assert math.isclose(ratio, 1.0)
