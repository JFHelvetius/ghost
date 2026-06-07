"""`analysis` — derived run analysis artifacts (T5, ADR-0013, ADR-0016).

Offline only. Deterministic. JSON-only output. No databases, dashboards,
services, threads, async, ML, or anomaly detection.

Public API:

- ``RunSummary`` (frozen dataclass): the derived artifact (T5).
- ``build_run_summary(*, run_id, reader, final_state) -> RunSummary``.
- ``generate_run_report(summary, output_path)``: writes a JSON sidecar.
- ``encode_report_to_bytes(summary) -> bytes``: pure encoder.
- ``SUMMARY_SCHEMA_VERSION`` / ``REPORT_SCHEMA_VERSION``: versioned
  contracts. Bumping either is a deliberate change with test updates.
- ``BeliefTraceRecord`` / ``BeliefTraceabilityReport`` (frozen
  dataclasses): per-sample and aggregated artifact for the
  truth/belief comparison (ADR-0016).
- ``build_traceability_report(*, truth, belief)``: pure aligner +
  per-sample error / covariance computation.
- ``compute_position_error`` / ``compute_orientation_error``: exposed
  pure helpers, useful outside the report flow.
- ``encode_belief_report_to_bytes`` / ``generate_belief_report``:
  canonical JSON encoder + file writer.
- ``BELIEF_TRACEABILITY_ANALYSIS_VERSION`` /
  ``BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION``: versioned contracts.

CLI: ``ghost analyze-run --mcap PATH --state PATH --output PATH`` and
``ghost analyze-belief --truth-mcap PATH --belief-mcap PATH [--output
PATH]`` live in ``project_ghost.cli``.
"""

from __future__ import annotations

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
    "BELIEF_TRACEABILITY_ANALYSIS_VERSION",
    "BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "SUMMARY_SCHEMA_VERSION",
    "BeliefTraceRecord",
    "BeliefTraceabilityReport",
    "RunSummary",
    "build_run_summary",
    "build_traceability_report",
    "compute_orientation_error",
    "compute_position_error",
    "encode_belief_report_to_bytes",
    "encode_report_to_bytes",
    "generate_belief_report",
    "generate_run_report",
]
