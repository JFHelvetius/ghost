"""`analysis` — derived run analysis artifacts.

T5 / ADR-0013 (`RunSummary`), ADR-0016 (`BeliefTraceabilityReport`),
ADR-0017 (`BeliefConsistencySummary`), ADR-0018
(`RunManifest` + `ComparativeBeliefReport`), ADR-0019
(`BeliefCalibrationReport`).

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
- ``ManifestArtifact`` / ``RunManifest`` (frozen dataclasses):
  content-addressed provenance for a run (ADR-0018).
- ``LabeledSummary`` / ``MetricDelta`` /
  ``ComparativeBeliefReport`` (frozen dataclasses): N-way structured
  deltas between summaries (ADR-0018).
- ``build_run_manifest`` / ``verify_run_manifest`` /
  ``build_comparative_report``: pure functions for provenance and
  comparison.
- ``decode_consistency_summary_from_json`` /
  ``decode_run_manifest_from_json`` /
  ``decode_comparative_report_from_json``: companion decoders.
- ``encode_run_manifest_to_bytes`` /
  ``encode_comparative_report_to_bytes`` /
  ``generate_run_manifest`` / ``generate_comparative_report``:
  canonical JSON encoders + file writers for ADR-0018.
- ``BELIEF_COMPARISON_ANALYSIS_VERSION`` /
  ``BELIEF_COMPARISON_REPORT_SCHEMA_VERSION`` /
  ``RUN_MANIFEST_SCHEMA_VERSION``: versioned contracts.
- ``BeliefCalibrationRecord`` / ``BeliefCalibrationReport`` (frozen
  dataclasses): per-record + aggregate audit of declared-vs-empirical
  uncertainty ratios (ADR-0019). Observational, no verdicts.
- ``analyze_belief_calibration(report, *, source_belief_report_sha256)``:
  pure auditor over the ADR-0016 traceability report.
- ``decode_calibration_report_from_json`` /
  ``encode_calibration_report_to_bytes`` /
  ``generate_calibration_report``: canonical JSON IO for ADR-0019.
- ``BELIEF_CALIBRATION_ANALYSIS_VERSION`` /
  ``BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION``: versioned contracts.

CLI: six subcommands live in ``project_ghost.cli``:

- ``ghost analyze-run --mcap PATH --state PATH --output PATH``
- ``ghost analyze-belief --truth-mcap PATH --belief-mcap PATH
  [--output PATH]``
- ``ghost summarize-belief --report PATH [--output PATH]``
- ``ghost build-manifest --run-id ID [--config-json PATH]
  [--config-kv KEY=VALUE ...] [--input PATH=KIND ...]
  [--output-artifact PATH=KIND ...] [--output PATH]``
- ``ghost compare-belief --summary LABEL=PATH ...
  [--manifest LABEL=PATH ...] [--output PATH]``
- ``ghost analyze-calibration --belief-report PATH [--output PATH]``
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
from .calibration import (
    BELIEF_CALIBRATION_ANALYSIS_VERSION,
    BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
    BeliefCalibrationRecord,
    BeliefCalibrationReport,
    analyze_belief_calibration,
    decode_calibration_report_from_json,
    encode_calibration_report_to_bytes,
    generate_calibration_report,
)
from .comparison import (
    BELIEF_COMPARISON_ANALYSIS_VERSION,
    BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
    RUN_MANIFEST_SCHEMA_VERSION,
    ComparativeBeliefReport,
    LabeledSummary,
    ManifestArtifact,
    MetricDelta,
    RunManifest,
    build_comparative_report,
    build_run_manifest,
    decode_comparative_report_from_json,
    decode_consistency_summary_from_json,
    decode_run_manifest_from_json,
    encode_comparative_report_to_bytes,
    encode_run_manifest_to_bytes,
    generate_comparative_report,
    generate_run_manifest,
    verify_run_manifest,
)
from .models import SUMMARY_SCHEMA_VERSION, RunSummary
from .report import (
    REPORT_SCHEMA_VERSION,
    encode_report_to_bytes,
    generate_run_report,
)
from .summary import build_run_summary

__all__ = [
    "BELIEF_CALIBRATION_ANALYSIS_VERSION",
    "BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION",
    "BELIEF_COMPARISON_ANALYSIS_VERSION",
    "BELIEF_COMPARISON_REPORT_SCHEMA_VERSION",
    "BELIEF_CONSISTENCY_ANALYSIS_VERSION",
    "BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION",
    "BELIEF_TRACEABILITY_ANALYSIS_VERSION",
    "BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "SUMMARY_SCHEMA_VERSION",
    "BeliefCalibrationRecord",
    "BeliefCalibrationReport",
    "BeliefConsistencySummary",
    "BeliefTraceRecord",
    "BeliefTraceabilityReport",
    "ComparativeBeliefReport",
    "LabeledSummary",
    "ManifestArtifact",
    "MetricDelta",
    "RunManifest",
    "RunSummary",
    "analyze_belief_calibration",
    "build_comparative_report",
    "build_run_manifest",
    "build_run_summary",
    "build_traceability_report",
    "compute_orientation_error",
    "compute_position_error",
    "decode_belief_report_from_json",
    "decode_calibration_report_from_json",
    "decode_comparative_report_from_json",
    "decode_consistency_summary_from_json",
    "decode_run_manifest_from_json",
    "encode_belief_report_to_bytes",
    "encode_calibration_report_to_bytes",
    "encode_comparative_report_to_bytes",
    "encode_consistency_summary_to_bytes",
    "encode_report_to_bytes",
    "encode_run_manifest_to_bytes",
    "generate_belief_report",
    "generate_calibration_report",
    "generate_comparative_report",
    "generate_consistency_report",
    "generate_run_manifest",
    "generate_run_report",
    "summarize_belief_consistency",
    "verify_run_manifest",
]
