"""`analysis` — derived run analysis artifacts.

T5 / ADR-0013 (`RunSummary`), ADR-0016 (`BeliefTraceabilityReport`),
ADR-0017 (`BeliefConsistencySummary`).

Offline only. Deterministic. JSON-only output. No databases, dashboards,
services, threads, async, ML, or anomaly detection.

Public API:

- ``RunSummary`` (frozen dataclass): the derived artifact (T5).
- ``build_run_summary(*, run_id, reader, final_state) -> RunSummary``.
- ``generate_run_report(summary, output_path)``: writes a JSON sidecar.
- ``encode_report_to_bytes(summary) -> bytes``: pure encoder.
- ``SUMMARY_SCHEMA_VERSION`` / ``REPORT_SCHEMA_VERSION``: versioned
  contracts.
- ``BeliefTraceRecord`` / ``BeliefTraceabilityReport`` (frozen
  dataclasses): per-sample and aggregated artifact for the
  truth/belief comparison (ADR-0016).
- ``build_traceability_report(*, truth, belief)``: pure aligner.
- ``compute_position_error`` / ``compute_orientation_error``: pure
  helpers.
- ``encode_belief_report_to_bytes`` / ``generate_belief_report``:
  canonical JSON encoder + file writer for ADR-0016.
- ``BELIEF_TRACEABILITY_ANALYSIS_VERSION`` /
  ``BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION``: versioned contracts.
- ``BeliefConsistencySummary`` (frozen dataclass): descriptive
  statistics over a ``BeliefTraceabilityReport`` (ADR-0017).
- ``summarize_belief_consistency(report)``: pure aggregator.
- ``decode_belief_report_from_json(data)``: companion deserializer for
  the ADR-0016 JSON envelope.
- ``encode_consistency_summary_to_bytes`` /
  ``generate_consistency_report``: canonical JSON encoder + file writer
  for ADR-0017.
- ``BELIEF_CONSISTENCY_ANALYSIS_VERSION`` /
  ``BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION``: versioned contracts.

CLI: three subcommands live in ``project_ghost.cli``:

- ``ghost analyze-run --mcap PATH --state PATH --output PATH``
- ``ghost analyze-belief --truth-mcap PATH --belief-mcap PATH
  [--output PATH]``
- ``ghost summarize-belief --report PATH [--output PATH]``
"""

from __future__ import annotations

from .belief_consistency import (
    BELIEF_CONSISTENCY_ANALYSIS_VERSION,
    BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
    BeliefConsistencySummary,
    decode_belief_report_from_json,
    encode_consistency_summary_to_bytes,
    generate_consistency_report,
    summarize_belief_consistency,
)
from .belief_traceability import (
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
from .models import SUMMARY_SCHEMA_VERSION, RunSummary
from .report import (
    REPORT_SCHEMA_VERSION,
    encode_report_to_bytes,
    generate_run_report,
)
from .summary import build_run_summary

__all__ = [
    "BELIEF_CONSISTENCY_ANALYSIS_VERSION",
    "BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION",
    "BELIEF_TRACEABILITY_ANALYSIS_VERSION",
    "BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "SUMMARY_SCHEMA_VERSION",
    "BeliefConsistencySummary",
    "BeliefTraceRecord",
    "BeliefTraceabilityReport",
    "RunSummary",
    "build_run_summary",
    "build_traceability_report",
    "compute_orientation_error",
    "compute_position_error",
    "decode_belief_report_from_json",
    "encode_belief_report_to_bytes",
    "encode_consistency_summary_to_bytes",
    "encode_report_to_bytes",
    "generate_belief_report",
    "generate_consistency_report",
    "generate_run_report",
    "summarize_belief_consistency",
]
