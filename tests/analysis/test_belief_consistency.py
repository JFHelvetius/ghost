"""Tests del módulo `analysis.belief_consistency` (ADR-0017).

Cubre, por categorías:

- conteos (total, with/without covariance, sub-counts finitos)
- empty input
- single sample (con / sin covarianza)
- multi-sample (todos con cov, mixto, ninguno con cov, cov degenerada)
- timestamps (first / last / span)
- JSON canonical encoding (sort_keys, indent, ensure_ascii, trailing newline)
- byte-identical reproducibility + SHA-256 estable
- frozen dataclass
- schema validation
- decoder round-trip vía `decode_belief_report_from_json`
- writer output

CLI tests viven en ``test_belief_consistency_cli.py``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from project_ghost.analysis import (
    BELIEF_CONSISTENCY_ANALYSIS_VERSION,
    BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
    BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION,
    BeliefTraceabilityReport,
    BeliefTraceRecord,
    decode_belief_report_from_json,
    encode_belief_report_to_bytes,
    encode_consistency_summary_to_bytes,
    generate_consistency_report,
    summarize_belief_consistency,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    timestamp_ns: int = 0,
    position_error: float = 0.0,
    orientation_error: float = 0.0,
    covariance_trace: float | None = None,
    covariance_condition_number: float | None = None,
    covariance_available: bool = False,
) -> BeliefTraceRecord:
    """Construye un BeliefTraceRecord con valores controlados."""
    return BeliefTraceRecord(
        timestamp_ns=timestamp_ns,
        truth_position_xyz=(0.0, 0.0, 0.0),
        belief_position_xyz=(0.0, 0.0, 0.0),
        truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        position_error_norm_m=position_error,
        orientation_error_rad=orientation_error,
        covariance_trace=covariance_trace,
        covariance_condition_number=covariance_condition_number,
        covariance_available=covariance_available,
    )


def _report(
    *,
    records: tuple[BeliefTraceRecord, ...] = (),
    samples_with_covariance: int | None = None,
    samples_without_covariance: int | None = None,
) -> BeliefTraceabilityReport:
    """Construye un BeliefTraceabilityReport coherente con los records.

    Cuando `samples_with_covariance` no se pasa, se infiere contando
    `covariance_available` en los records — así los tests no replican
    el conteo manualmente.
    """
    n = len(records)
    if samples_with_covariance is None:
        samples_with_covariance = sum(1 for r in records if r.covariance_available)
    if samples_without_covariance is None:
        samples_without_covariance = n - samples_with_covariance
    pos_errors = [r.position_error_norm_m for r in records]
    ori_errors = [r.orientation_error_rad for r in records]
    return BeliefTraceabilityReport(
        total_samples=n,
        samples_with_covariance=samples_with_covariance,
        samples_without_covariance=samples_without_covariance,
        mean_position_error_m=(sum(pos_errors) / n) if n else 0.0,
        max_position_error_m=max(pos_errors) if n else 0.0,
        mean_orientation_error_rad=(sum(ori_errors) / n) if n else 0.0,
        max_orientation_error_rad=max(ori_errors) if n else 0.0,
        records=records,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_analysis_version_constant_is_one() -> None:
    assert BELIEF_CONSISTENCY_ANALYSIS_VERSION == 1


def test_schema_version_constant_is_one_string() -> None:
    assert BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION == "1"


def test_summary_analysis_version_default_is_one() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.analysis_version == BELIEF_CONSISTENCY_ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_report_total_samples_zero() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.total_samples == 0


def test_empty_report_timestamps_are_none() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.timestamp_first_ns is None
    assert summary.timestamp_last_ns is None
    assert summary.timestamp_span_ns is None


def test_empty_report_pos_orient_errors_are_zero() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.position_error_min_m == 0.0
    assert summary.position_error_max_m == 0.0
    assert summary.position_error_mean_m == 0.0
    assert summary.orientation_error_min_rad == 0.0
    assert summary.orientation_error_max_rad == 0.0
    assert summary.orientation_error_mean_rad == 0.0


def test_empty_report_covariance_aggregates_are_none() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.covariance_trace_min is None
    assert summary.covariance_trace_max is None
    assert summary.covariance_trace_mean is None
    assert summary.covariance_condition_number_min is None
    assert summary.covariance_condition_number_max is None
    assert summary.covariance_condition_number_mean is None


def test_empty_report_subcounts_are_zero() -> None:
    summary = summarize_belief_consistency(_report())
    assert summary.samples_with_finite_trace == 0
    assert summary.samples_with_finite_condition_number == 0


# ---------------------------------------------------------------------------
# Single sample — con cov
# ---------------------------------------------------------------------------


def test_single_sample_with_cov_total_samples_one() -> None:
    rec = _record(
        timestamp_ns=1000,
        position_error=0.5,
        orientation_error=0.1,
        covariance_trace=0.015,
        covariance_condition_number=2.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.total_samples == 1


def test_single_sample_with_cov_timestamps_coincide() -> None:
    rec = _record(timestamp_ns=42, covariance_trace=1.0, covariance_available=True)
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.timestamp_first_ns == 42
    assert summary.timestamp_last_ns == 42
    assert summary.timestamp_span_ns == 0


def test_single_sample_with_cov_trace_min_eq_max_eq_mean() -> None:
    rec = _record(
        covariance_trace=0.015,
        covariance_condition_number=3.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.covariance_trace_min == 0.015
    assert summary.covariance_trace_max == 0.015
    assert summary.covariance_trace_mean == 0.015


def test_single_sample_with_cov_condition_min_eq_max_eq_mean() -> None:
    rec = _record(
        covariance_trace=0.01,
        covariance_condition_number=3.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.covariance_condition_number_min == 3.0
    assert summary.covariance_condition_number_max == 3.0
    assert summary.covariance_condition_number_mean == 3.0


# ---------------------------------------------------------------------------
# Single sample — sin cov
# ---------------------------------------------------------------------------


def test_single_sample_without_cov_aggregates_none() -> None:
    rec = _record(covariance_available=False)
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.covariance_trace_min is None
    assert summary.covariance_trace_max is None
    assert summary.covariance_trace_mean is None
    assert summary.covariance_condition_number_min is None
    assert summary.covariance_condition_number_max is None
    assert summary.covariance_condition_number_mean is None


def test_single_sample_without_cov_subcounts_zero() -> None:
    rec = _record(covariance_available=False)
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.samples_with_finite_trace == 0
    assert summary.samples_with_finite_condition_number == 0


def test_single_sample_without_cov_pass_through_counts() -> None:
    rec = _record(covariance_available=False)
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert summary.samples_with_covariance == 0
    assert summary.samples_without_covariance == 1


# ---------------------------------------------------------------------------
# Multi-sample homogéneo (todos con cov)
# ---------------------------------------------------------------------------


def test_multi_sample_position_error_min_max_mean() -> None:
    recs = (
        _record(timestamp_ns=0, position_error=0.1),
        _record(timestamp_ns=1, position_error=0.5),
        _record(timestamp_ns=2, position_error=0.3),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.position_error_min_m == 0.1
    assert summary.position_error_max_m == 0.5
    assert abs(summary.position_error_mean_m - 0.3) < 1e-12


def test_multi_sample_orientation_error_min_max_mean() -> None:
    recs = (
        _record(timestamp_ns=0, orientation_error=0.05),
        _record(timestamp_ns=1, orientation_error=0.15),
        _record(timestamp_ns=2, orientation_error=0.10),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.orientation_error_min_rad == 0.05
    assert summary.orientation_error_max_rad == 0.15
    assert abs(summary.orientation_error_mean_rad - 0.10) < 1e-12


def test_multi_sample_trace_min_max_mean() -> None:
    recs = (
        _record(covariance_trace=0.01, covariance_available=True),
        _record(covariance_trace=0.03, covariance_available=True),
        _record(covariance_trace=0.02, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.covariance_trace_min == 0.01
    assert summary.covariance_trace_max == 0.03
    assert summary.covariance_trace_mean is not None
    assert abs(summary.covariance_trace_mean - 0.02) < 1e-12


def test_multi_sample_condition_min_max_mean() -> None:
    recs = (
        _record(covariance_condition_number=1.0, covariance_available=True),
        _record(covariance_condition_number=5.0, covariance_available=True),
        _record(covariance_condition_number=3.0, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.covariance_condition_number_min == 1.0
    assert summary.covariance_condition_number_max == 5.0
    assert summary.covariance_condition_number_mean is not None
    assert abs(summary.covariance_condition_number_mean - 3.0) < 1e-12


def test_multi_sample_total_samples_matches_records() -> None:
    recs = tuple(_record(timestamp_ns=i) for i in range(7))
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.total_samples == 7


# ---------------------------------------------------------------------------
# Multi-sample con covarianza mixta
# ---------------------------------------------------------------------------


def test_mixed_covariance_aggregates_skip_none_records() -> None:
    recs = (
        _record(covariance_trace=0.01, covariance_condition_number=1.0, covariance_available=True),
        _record(covariance_available=False),
        _record(covariance_trace=0.03, covariance_condition_number=2.0, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.covariance_trace_min == 0.01
    assert summary.covariance_trace_max == 0.03
    assert summary.covariance_trace_mean is not None
    assert abs(summary.covariance_trace_mean - 0.02) < 1e-12
    assert summary.samples_with_finite_trace == 2
    assert summary.samples_with_finite_condition_number == 2


def test_mixed_covariance_pass_through_counts() -> None:
    recs = (
        _record(covariance_available=True, covariance_trace=0.01, covariance_condition_number=1.0),
        _record(covariance_available=False),
        _record(covariance_available=True, covariance_trace=0.02, covariance_condition_number=1.5),
        _record(covariance_available=False),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.samples_with_covariance == 2
    assert summary.samples_without_covariance == 2


# ---------------------------------------------------------------------------
# Covarianza presente pero degenerada (trace o cond colapsada a None)
# ---------------------------------------------------------------------------


def test_degenerate_covariance_excluded_from_trace_aggregates() -> None:
    """Un record con covariance_available=True pero trace=None (cov
    degenerada, e.g. zero-matrix) NO debe sumar al sub-count finito
    ni alterar min/max/mean."""
    recs = (
        _record(covariance_trace=0.01, covariance_condition_number=1.0, covariance_available=True),
        _record(covariance_trace=None, covariance_condition_number=None, covariance_available=True),
        _record(covariance_trace=0.03, covariance_condition_number=2.0, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.samples_with_finite_trace == 2
    assert summary.samples_with_finite_condition_number == 2
    assert summary.samples_with_covariance == 3
    assert summary.covariance_trace_min == 0.01
    assert summary.covariance_trace_max == 0.03


def test_all_covariance_degenerate_yields_none_aggregates() -> None:
    recs = (
        _record(covariance_trace=None, covariance_condition_number=None, covariance_available=True),
        _record(covariance_trace=None, covariance_condition_number=None, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.covariance_trace_min is None
    assert summary.covariance_trace_max is None
    assert summary.covariance_trace_mean is None
    assert summary.covariance_condition_number_min is None
    assert summary.covariance_condition_number_mean is None
    assert summary.samples_with_finite_trace == 0
    assert summary.samples_with_finite_condition_number == 0
    assert summary.samples_with_covariance == 2


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def test_timestamps_first_last_span_correct() -> None:
    recs = (
        _record(timestamp_ns=100),
        _record(timestamp_ns=200),
        _record(timestamp_ns=500),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.timestamp_first_ns == 100
    assert summary.timestamp_last_ns == 500
    assert summary.timestamp_span_ns == 400


def test_timestamps_out_of_order_records_use_min_max() -> None:
    """El builder de ADR-0016 preserva el orden de entrada (no re-ordena).
    El summarizer debe usar min/max de timestamp_ns, no first/last record."""
    recs = (
        _record(timestamp_ns=500),
        _record(timestamp_ns=100),
        _record(timestamp_ns=300),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.timestamp_first_ns == 100
    assert summary.timestamp_last_ns == 500
    assert summary.timestamp_span_ns == 400


def test_single_record_timestamp_span_is_zero() -> None:
    summary = summarize_belief_consistency(_report(records=(_record(timestamp_ns=999),)))
    assert summary.timestamp_first_ns == 999
    assert summary.timestamp_last_ns == 999
    assert summary.timestamp_span_ns == 0


# ---------------------------------------------------------------------------
# JSON canonical encoding
# ---------------------------------------------------------------------------


def test_encoded_summary_has_trailing_newline() -> None:
    summary = summarize_belief_consistency(_report())
    encoded = encode_consistency_summary_to_bytes(summary)
    assert encoded.endswith(b"\n")


def test_encoded_summary_uses_indent_2() -> None:
    summary = summarize_belief_consistency(_report())
    encoded = encode_consistency_summary_to_bytes(summary)
    # indent=2 con un solo nivel de wrapper produce líneas multi-nivel
    assert encoded.count(b"\n") > 1


def test_encoded_summary_keys_sorted() -> None:
    summary = summarize_belief_consistency(_report())
    encoded = encode_consistency_summary_to_bytes(summary).decode("utf-8")
    # Top-level: "schema_version" precede a "summary" alfabéticamente.
    idx_schema = encoded.index('"schema_version"')
    idx_summary = encoded.index('"summary"')
    assert idx_schema < idx_summary


def test_encoded_summary_is_valid_utf8_json() -> None:
    summary = summarize_belief_consistency(_report())
    encoded = encode_consistency_summary_to_bytes(summary)
    parsed = json.loads(encoded.decode("utf-8"))
    assert parsed["schema_version"] == BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION
    assert "summary" in parsed


def test_encoded_summary_envelope_structure() -> None:
    rec = _record(
        timestamp_ns=1,
        covariance_trace=0.01,
        covariance_condition_number=1.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    encoded = encode_consistency_summary_to_bytes(summary)
    parsed = json.loads(encoded.decode("utf-8"))
    assert parsed["summary"]["total_samples"] == 1
    assert parsed["summary"]["analysis_version"] == 1
    assert parsed["summary"]["timestamp_first_ns"] == 1


# ---------------------------------------------------------------------------
# Determinism: byte-identical reproducibility
# ---------------------------------------------------------------------------


def test_two_encodings_are_byte_identical() -> None:
    rec = _record(
        timestamp_ns=1,
        position_error=0.1,
        covariance_trace=0.01,
        covariance_condition_number=1.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    first = encode_consistency_summary_to_bytes(summary)
    second = encode_consistency_summary_to_bytes(summary)
    assert first == second


def test_two_summarizations_yield_equal_summaries() -> None:
    rec = _record(timestamp_ns=1)
    report = _report(records=(rec,))
    a = summarize_belief_consistency(report)
    b = summarize_belief_consistency(report)
    assert a == b


def test_sha256_stable_across_repeated_encodings() -> None:
    recs = tuple(
        _record(
            timestamp_ns=i * 1000,
            position_error=0.1 * i,
            orientation_error=0.01 * i,
            covariance_trace=0.015,
            covariance_condition_number=1.0,
            covariance_available=True,
        )
        for i in range(5)
    )
    summary = summarize_belief_consistency(_report(records=recs))
    hashes = {
        hashlib.sha256(encode_consistency_summary_to_bytes(summary)).hexdigest() for _ in range(5)
    }
    assert len(hashes) == 1


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


def test_summary_is_frozen() -> None:
    summary = summarize_belief_consistency(_report())
    with pytest.raises(FrozenInstanceError):
        summary.total_samples = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# decode_belief_report_from_json — validation + round-trip
# ---------------------------------------------------------------------------


def test_decode_round_trip_preserves_report() -> None:
    rec = _record(
        timestamp_ns=42,
        position_error=0.5,
        orientation_error=0.1,
        covariance_trace=0.015,
        covariance_condition_number=2.0,
        covariance_available=True,
    )
    original = _report(records=(rec,))
    encoded = encode_belief_report_to_bytes(original)
    data = json.loads(encoded.decode("utf-8"))
    decoded = decode_belief_report_from_json(data)
    assert decoded == original


def test_decode_schema_version_mismatch_raises() -> None:
    data = {"schema_version": "999", "report": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_belief_report_from_json(data)


def test_decode_missing_schema_version_raises() -> None:
    data: dict[str, object] = {"report": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_belief_report_from_json(data)


def test_decode_missing_report_raises() -> None:
    data = {"schema_version": BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION}
    with pytest.raises(ValueError, match="report"):
        decode_belief_report_from_json(data)


def test_decode_non_mapping_input_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_belief_report_from_json([1, 2, 3])  # type: ignore[arg-type]


def test_decode_non_mapping_report_raises() -> None:
    data = {
        "schema_version": BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION,
        "report": [1, 2, 3],
    }
    with pytest.raises(TypeError, match="mapping"):
        decode_belief_report_from_json(data)


def test_decode_preserves_records_tuple() -> None:
    recs = tuple(
        _record(
            timestamp_ns=i,
            covariance_trace=float(i),
            covariance_condition_number=1.0,
            covariance_available=True,
        )
        for i in range(3)
    )
    original = _report(records=recs)
    data = json.loads(encode_belief_report_to_bytes(original).decode("utf-8"))
    decoded = decode_belief_report_from_json(data)
    assert isinstance(decoded.records, tuple)
    assert len(decoded.records) == 3


def test_decode_summarize_pipeline_matches_direct_summary() -> None:
    """Pipeline canónico:
        report -> encode_belief_report_to_bytes -> json.loads ->
        decode_belief_report_from_json -> summarize_belief_consistency.
    Debe producir el mismo summary que llamar summarize_belief_consistency
    directamente sobre el report original."""
    rec = _record(
        timestamp_ns=5,
        position_error=0.3,
        covariance_trace=0.02,
        covariance_condition_number=1.5,
        covariance_available=True,
    )
    original = _report(records=(rec,))
    direct = summarize_belief_consistency(original)

    data = json.loads(encode_belief_report_to_bytes(original).decode("utf-8"))
    via_pipeline = summarize_belief_consistency(decode_belief_report_from_json(data))

    assert direct == via_pipeline


# ---------------------------------------------------------------------------
# generate_consistency_report — file writer
# ---------------------------------------------------------------------------


def test_generate_consistency_report_writes_canonical_bytes(
    tmp_path: Path,
) -> None:
    summary = summarize_belief_consistency(_report(records=(_record(timestamp_ns=0),)))
    p = tmp_path / "summary.json"
    generate_consistency_report(summary, p)
    assert p.read_bytes() == encode_consistency_summary_to_bytes(summary)


def test_generate_consistency_report_two_writes_byte_identical(
    tmp_path: Path,
) -> None:
    summary = summarize_belief_consistency(_report())
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_consistency_report(summary, a)
    generate_consistency_report(summary, b)
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# Cross-checks
# ---------------------------------------------------------------------------


def test_subcounts_independent_for_trace_vs_condition() -> None:
    """Un record puede tener trace finito y cond None (o viceversa).
    Los sub-counts deben distinguirlos."""
    recs = (
        _record(covariance_trace=0.01, covariance_condition_number=None, covariance_available=True),
        _record(covariance_trace=None, covariance_condition_number=1.0, covariance_available=True),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.samples_with_finite_trace == 1
    assert summary.samples_with_finite_condition_number == 1


def test_pass_through_counts_match_input_report() -> None:
    """ADR-0017: samples_with/without_covariance son pass-through de
    ADR-0016 — el summarizer no los recomputa."""
    rec = _record(covariance_available=False)
    report = _report(
        records=(rec,),
        samples_with_covariance=999,  # valor inventado intencionalmente
        samples_without_covariance=42,
    )
    summary = summarize_belief_consistency(report)
    assert summary.samples_with_covariance == 999
    assert summary.samples_without_covariance == 42


def test_mean_position_error_correct_for_two_samples() -> None:
    recs = (
        _record(position_error=0.0),
        _record(position_error=1.0),
    )
    summary = summarize_belief_consistency(_report(records=recs))
    assert summary.position_error_mean_m == 0.5


def test_finite_values_propagate_unchanged() -> None:
    """Verifica que `math.isfinite` aplicado al output del summarizer
    para records con datos finitos da True — guardia contra accidental
    introducción de NaN/Inf en agregados."""
    rec = _record(
        position_error=0.5,
        orientation_error=0.1,
        covariance_trace=0.01,
        covariance_condition_number=1.0,
        covariance_available=True,
    )
    summary = summarize_belief_consistency(_report(records=(rec,)))
    assert math.isfinite(summary.position_error_min_m)
    assert math.isfinite(summary.position_error_max_m)
    assert math.isfinite(summary.position_error_mean_m)
    assert summary.covariance_trace_min is not None
    assert math.isfinite(summary.covariance_trace_min)
