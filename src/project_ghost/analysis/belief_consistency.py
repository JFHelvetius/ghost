"""Belief consistency analysis (ADR-0017).

Pure, deterministic, descriptive. Ingests a
``BeliefTraceabilityReport`` (ADR-0016) and emits a frozen
``BeliefConsistencySummary`` with min/max/mean over the report's
records, plus the timestamp range and finite-metric sub-counts.

**Honest framing.** This module produces descriptive statistics over
already-observed paired samples. It does NOT:

- evaluate the belief,
- compute consistency tests (NEES / NIS / Mahalanobis),
- classify records,
- detect anomalies,
- recommend corrective action,
- cross-correlate fields.

Operators read the numbers and form their own hypotheses. The system
explicitly refuses to do so.

Encoding posture: ``sort_keys=True``, ``indent=2``,
``ensure_ascii=False``, trailing newline, UTF-8. Byte determinism
within a fixed ``(CPython, numpy)`` tuple.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from project_ghost.telemetry import from_json_dict

from .belief_traceability import (
    BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION,
    BeliefTraceabilityReport,
)

if TYPE_CHECKING:
    from pathlib import Path


BELIEF_CONSISTENCY_ANALYSIS_VERSION: int = 1
BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Summary dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefConsistencySummary:
    """Descriptive statistics over a `BeliefTraceabilityReport`.

    Aggregation rules (frozen per ADR-0017):

    - Counts: ``total_samples`` is ``len(report.records)``;
      ``samples_with_covariance`` / ``samples_without_covariance`` are
      pass-through from the input report.
    - Timestamps: ``first = min(record.timestamp_ns)``,
      ``last = max(...)``, ``span = last - first``. All three are
      ``None`` iff ``total_samples == 0``.
    - Position / orientation error: ``min``, ``max``, ``mean`` over
      **all** records. Empty input collapses to ``0.0`` (consistent
      with ADR-0016 convention).
    - Covariance trace / condition number: ``min``, ``max``, ``mean``
      over records whose corresponding field is **not** ``None``. If
      no such record exists, all three are ``None``.
    - ``samples_with_finite_trace`` /
      ``samples_with_finite_condition_number`` count only records
      whose computed metric was finite (i.e., not collapsed to
      ``None`` by ADR-0016).

    The summary intentionally does **not** carry the records
    themselves; the source ``BeliefTraceabilityReport`` is the
    authoritative store for per-sample data.
    """

    total_samples: int
    samples_with_covariance: int
    samples_without_covariance: int

    timestamp_first_ns: int | None
    timestamp_last_ns: int | None
    timestamp_span_ns: int | None

    position_error_min_m: float
    position_error_max_m: float
    position_error_mean_m: float

    orientation_error_min_rad: float
    orientation_error_max_rad: float
    orientation_error_mean_rad: float

    covariance_trace_min: float | None
    covariance_trace_max: float | None
    covariance_trace_mean: float | None

    covariance_condition_number_min: float | None
    covariance_condition_number_max: float | None
    covariance_condition_number_mean: float | None

    samples_with_finite_trace: int
    samples_with_finite_condition_number: int

    analysis_version: int = BELIEF_CONSISTENCY_ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize_belief_consistency(
    report: BeliefTraceabilityReport,
) -> BeliefConsistencySummary:
    """Aggregate descriptive statistics over a traceability report.

    Pure function: reads no clock, performs no I/O, holds no
    thread-local state, uses no random. Single forward pass over
    ``report.records``.
    """
    records = report.records
    n = len(records)

    if n == 0:
        timestamp_first: int | None = None
        timestamp_last: int | None = None
        timestamp_span: int | None = None
        pos_min = pos_max = pos_mean = 0.0
        ori_min = ori_max = ori_mean = 0.0
    else:
        timestamps = [r.timestamp_ns for r in records]
        timestamp_first = min(timestamps)
        timestamp_last = max(timestamps)
        timestamp_span = timestamp_last - timestamp_first

        pos_errors = [r.position_error_norm_m for r in records]
        ori_errors = [r.orientation_error_rad for r in records]
        pos_min = min(pos_errors)
        pos_max = max(pos_errors)
        pos_mean = sum(pos_errors) / n
        ori_min = min(ori_errors)
        ori_max = max(ori_errors)
        ori_mean = sum(ori_errors) / n

    # Covariance trace: include only records whose computed trace was
    # finite (ADR-0016 collapses non-finite metrics to None).
    traces: list[float] = [r.covariance_trace for r in records if r.covariance_trace is not None]
    if traces:
        cov_trace_min: float | None = min(traces)
        cov_trace_max: float | None = max(traces)
        cov_trace_mean: float | None = sum(traces) / len(traces)
    else:
        cov_trace_min = None
        cov_trace_max = None
        cov_trace_mean = None

    conds: list[float] = [
        r.covariance_condition_number for r in records if r.covariance_condition_number is not None
    ]
    if conds:
        cov_cond_min: float | None = min(conds)
        cov_cond_max: float | None = max(conds)
        cov_cond_mean: float | None = sum(conds) / len(conds)
    else:
        cov_cond_min = None
        cov_cond_max = None
        cov_cond_mean = None

    return BeliefConsistencySummary(
        total_samples=n,
        samples_with_covariance=report.samples_with_covariance,
        samples_without_covariance=report.samples_without_covariance,
        timestamp_first_ns=timestamp_first,
        timestamp_last_ns=timestamp_last,
        timestamp_span_ns=timestamp_span,
        position_error_min_m=pos_min,
        position_error_max_m=pos_max,
        position_error_mean_m=pos_mean,
        orientation_error_min_rad=ori_min,
        orientation_error_max_rad=ori_max,
        orientation_error_mean_rad=ori_mean,
        covariance_trace_min=cov_trace_min,
        covariance_trace_max=cov_trace_max,
        covariance_trace_mean=cov_trace_mean,
        covariance_condition_number_min=cov_cond_min,
        covariance_condition_number_max=cov_cond_max,
        covariance_condition_number_mean=cov_cond_mean,
        samples_with_finite_trace=len(traces),
        samples_with_finite_condition_number=len(conds),
    )


# ---------------------------------------------------------------------------
# Decoder for the ADR-0016 JSON envelope
# ---------------------------------------------------------------------------


def decode_belief_report_from_json(
    data: Mapping[str, Any],
) -> BeliefTraceabilityReport:
    """Reconstruct a ``BeliefTraceabilityReport`` from canonical JSON.

    Expects the structure produced by
    ``encode_belief_report_to_bytes`` (ADR-0016)::

        {
          "schema_version": "1",
          "report": { ...fields... }
        }

    Validates ``schema_version`` against the literal
    ``BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION``. Reconstruction goes
    through ``telemetry.from_json_dict``, so each nested dataclass's
    ``__post_init__`` re-runs — bad data fails loudly.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f"decode_belief_report_from_json: expected mapping; got {type(data).__name__}"
        )
    if "schema_version" not in data:
        raise ValueError("decode_belief_report_from_json: missing 'schema_version'")
    schema_version = data["schema_version"]
    if schema_version != BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"decode_belief_report_from_json: incompatible "
            f"schema_version {schema_version!r}; expected "
            f"{BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION!r}"
        )
    if "report" not in data:
        raise ValueError("decode_belief_report_from_json: missing 'report' field")
    report_dict = data["report"]
    if not isinstance(report_dict, Mapping):
        raise TypeError(
            f"decode_belief_report_from_json: 'report' must be a mapping; "
            f"got {type(report_dict).__name__}"
        )
    decoded = from_json_dict(BeliefTraceabilityReport, report_dict)
    if not isinstance(decoded, BeliefTraceabilityReport):  # pragma: no cover
        raise TypeError(
            "decode_belief_report_from_json: decoded object is not a BeliefTraceabilityReport"
        )
    return decoded


# ---------------------------------------------------------------------------
# JSON encoder + file writer
# ---------------------------------------------------------------------------


def encode_consistency_summary_to_bytes(
    summary: BeliefConsistencySummary,
) -> bytes:
    """Encode ``summary`` to deterministic UTF-8 JSON bytes.

    Output structure::

        {
          "schema_version": "1",
          "summary": { ...alphabetically sorted fields... }
        }

    Encoding rules (frozen):

    - ``sort_keys=True``
    - ``indent=2``
    - ``ensure_ascii=False``
    - trailing newline
    - UTF-8
    """
    document = {
        "schema_version": BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
        "summary": dataclasses.asdict(summary),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_consistency_report(summary: BeliefConsistencySummary, output_path: Path) -> None:
    """Write ``summary`` as canonical JSON to ``output_path``.

    Overwrites if the file exists. Does not invent parent directories.
    """
    output_path.write_bytes(encode_consistency_summary_to_bytes(summary))


__all__ = [
    "BELIEF_CONSISTENCY_ANALYSIS_VERSION",
    "BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION",
    "BeliefConsistencySummary",
    "decode_belief_report_from_json",
    "encode_consistency_summary_to_bytes",
    "generate_consistency_report",
    "summarize_belief_consistency",
]
