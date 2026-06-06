"""`analysis` — derived run analysis artifacts (T5, ADR-0013).

Offline only. Deterministic. JSON-only output. No databases, dashboards,
services, threads, async, ML, or anomaly detection.

Public API:

- ``RunSummary`` (frozen dataclass): the derived artifact.
- ``build_run_summary(*, run_id, reader, final_state) -> RunSummary``.
- ``generate_run_report(summary, output_path)``: writes a JSON sidecar.
- ``encode_report_to_bytes(summary) -> bytes``: pure encoder.
- ``SUMMARY_SCHEMA_VERSION`` / ``REPORT_SCHEMA_VERSION``: versioned
  contracts. Bumping either is a deliberate change with test updates.

CLI: ``ghost analyze-run --mcap PATH --state PATH --output PATH`` lives in
``project_ghost.cli``.
"""

from __future__ import annotations

from .models import SUMMARY_SCHEMA_VERSION, RunSummary
from .report import (
    REPORT_SCHEMA_VERSION,
    encode_report_to_bytes,
    generate_run_report,
)
from .summary import build_run_summary

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "SUMMARY_SCHEMA_VERSION",
    "RunSummary",
    "build_run_summary",
    "encode_report_to_bytes",
    "generate_run_report",
]
