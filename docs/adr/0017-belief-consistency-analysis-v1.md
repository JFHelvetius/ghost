# ADR-0017 — Belief Consistency Analysis v1

## Status
Accepted (2026-06-07).

## Context

ADR-0016 introduced `BeliefTraceabilityReport`: per-sample comparison
between truth and belief, with covariance diagnostics attached
record-by-record. The artifact answers questions about individual
samples, but leaves an operator that wants a run-level view scanning N
records by hand.

ADR-0009 §6 — *"know when you do not know"* — sets the auditability
obligation. ADR-0014 (Behavior Traceability v1) and ADR-0016 (Belief
Traceability v1) staked out the observational posture: reconstruct
captured facts, do not interpret. This ADR extends that posture one
more step: **aggregate the per-sample facts into descriptive
statistics**, still without interpretation.

This ADR commits to one specific, narrow mechanism:

> A pure, deterministic aggregator that ingests a
> `BeliefTraceabilityReport` and emits a frozen
> `BeliefConsistencySummary` containing the descriptive statistics
> (min, max, mean) over the report's records, plus the timestamp range
> and finite-metric sub-counts.

That is **all** the system does. The points listed under "Exclusions"
below are not extension hooks — they are explicit non-goals.

The framing matches ADR-0014 ("traceability is not explanation") and
ADR-0016 ("traceability is not estimation, not evaluation"):

> **Description is not evaluation.**

A row of numbers in the summary is exactly that. It does NOT mean the
belief was good, bad, overconfident, or underconfident. The operator
reads the numbers and forms hypotheses; the system explicitly refuses
to do so.

## Decision

Add `project_ghost.analysis.belief_consistency` module with:

1. **`BeliefConsistencySummary`** — frozen dataclass:

   - **Counts**
     - `total_samples` (int)
     - `samples_with_covariance` (int): pass-through from ADR-0016.
     - `samples_without_covariance` (int): pass-through from ADR-0016.

   - **Timestamp range**
     - `timestamp_first_ns` (`int | None`): `min(record.timestamp_ns)`;
       `None` iff `total_samples == 0`.
     - `timestamp_last_ns` (`int | None`): `max(record.timestamp_ns)`;
       `None` iff `total_samples == 0`.
     - `timestamp_span_ns` (`int | None`): `last - first`; `None` iff
       `total_samples == 0`.

   - **Position error (meters)**
     - `position_error_min_m` / `_max_m` / `_mean_m` (float):
       descriptive statistics over **all** records;
       `0.0` for empty input (consistent with ADR-0016 convention).

   - **Orientation error (radians)**
     - `orientation_error_min_rad` / `_max_rad` / `_mean_rad` (float):
       same posture as position error.

   - **Covariance trace**
     - `covariance_trace_min` / `_max` / `_mean` (`float | None`):
       descriptive statistics over records whose
       `covariance_trace is not None`; `None` if no such record exists.

   - **Covariance condition number**
     - `covariance_condition_number_min` / `_max` / `_mean`
       (`float | None`): same posture, over records whose
       `covariance_condition_number is not None`.

   - **Finite-metric sub-counts**
     - `samples_with_finite_trace` (int): count of records with
       `covariance_trace is not None`.
     - `samples_with_finite_condition_number` (int): count of records
       with `covariance_condition_number is not None`.

   - `analysis_version` (int): equals
     `BELIEF_CONSISTENCY_ANALYSIS_VERSION`.

2. **`summarize_belief_consistency(report)`** — pure function. Single
   pass over `report.records`. No clock reads, no I/O, no random.

3. **`decode_belief_report_from_json(data)`** — helper that reconstructs
   a `BeliefTraceabilityReport` from the canonical JSON structure
   produced by `encode_belief_report_to_bytes` (ADR-0016). Validates
   `schema_version` against
   `BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION`; raises `ValueError` on
   mismatch. Uses the existing `telemetry.from_json_dict` to
   reconstruct the inner dataclass tree — `__post_init__` is therefore
   re-executed and bad data fails loudly.

4. **`encode_consistency_summary_to_bytes(summary)`** — canonical JSON
   encoder. `sort_keys=True`, `indent=2`, `ensure_ascii=False`,
   trailing newline, UTF-8.

5. **`generate_consistency_report(summary, output_path)`** — file
   writer. Pure write; does not invent parent directories.

6. **`ghost summarize-belief --report PATH [--output PATH]`** — CLI
   subcommand. Reads the JSON report, summarizes, emits JSON. Stdout
   when `--output` is omitted. JSON only.

Constants:

- `BELIEF_CONSISTENCY_ANALYSIS_VERSION: int = 1`
- `BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION: str = "1"`

Pipeline (intended composition):

```
ghost analyze-belief --truth-mcap T --belief-mcap B --output report.json
ghost summarize-belief --report report.json --output summary.json
```

## Inputs

- A `BeliefTraceabilityReport` (in-memory) **or** the path to its
  canonical JSON file.

## Outputs

- A `BeliefConsistencySummary` dataclass instance.
- A JSON document of the summary (via
  `encode_consistency_summary_to_bytes` or
  `generate_consistency_report`).

## Limits

- The summary covers ONLY records already aligned by ADR-0016. The
  producer is responsible for alignment policy.
- Descriptive statistics restricted to `min`, `max`, `mean`. **Std
  deviation, variance, quartiles, percentiles are NOT included.**
  Adding any of them is a deliberate new ADR, not an extension of
  this one.
- `timestamp_span_ns` is the simple `last - first`. It does NOT
  reorder, deduplicate, detect gaps, or detect overlaps.
- The summary does NOT embed the records themselves; the records
  remain in the source `BeliefTraceabilityReport`.
- The summary does NOT cross-correlate fields (e.g. "trace vs error",
  "timestamp vs covariance"). Such artifacts belong in separate ADRs.

## Determinism

For identical `BeliefTraceabilityReport` input within a fixed
`(CPython, numpy)`:

- The produced `BeliefConsistencySummary` is field-by-field equal.
- The encoded summary bytes are byte-identical.
- The SHA-256 of the encoded bytes is stable across processes.
- CLI: identical input JSON produces identical output JSON bytes.

The summarizer:

- Reads no clock.
- Performs no I/O (except the CLI, which reads input and writes
  output exactly once).
- Holds no thread-local state.
- Uses no random.
- Does NOT depend on dict iteration order — every aggregation uses
  explicit `min`, `max`, `sum` over `report.records`, whose ordering
  is preserved from the source.

## Exclusions (explicit non-goals)

NOT implemented and NOT extension points sanctioned by this ADR:

- **Bayesian / Kalman / particle / smoothing filters**.
- **Inference**: NEES, NIS, Mahalanobis distance, chi-square gates,
  consistency tests.
- **Confidence / risk scoring**: no derived "estimator quality"
  metric.
- **Classification**: no labeling of records as "outliers",
  "anomalies", or "good"/"bad".
- **Alerting / paging / notifications**.
- **Anomaly / trend detection / forecasting**.
- **Recommendations / autonomous decisions**.
- **Planners / controllers / path optimization**.
- **SLAM / localization / sensor fusion**.
- **ML / neural networks**.
- **Dashboards / GUI / plotting / charts / histograms / heatmaps**.
- **HTML / PDF / Markdown report rendering**.
- **Natural-language summaries**.
- **Std deviation / variance / percentiles / quartiles** (deferred to
  a future ADR if requested).
- **Cross-sample correlations** (timestamp vs error, trace vs error,
  etc.).

## "Description is not evaluation"

`covariance_trace_mean = 1e-3` and `position_error_max_m = 0.42` are
two facts the summary exposes side-by-side. The summary does NOT:

- assert that 1e-3 was "too small" for an error of 0.42 m,
- assert that the estimator was overconfident, underconfident, or
  correctly calibrated,
- assert any causal relationship between the two,
- score the run.

A human reading the summary can form hypotheses; the system explicitly
refuses to do so. If and when Project Ghost decides it needs evaluation
(NEES, NIS, calibration scoring), it will be a separate ADR and a
separate artifact that does NOT extend this one.

## Consequences

**Positive.**

- A single derived artifact answers the eight run-level questions
  about belief consistency that would otherwise require manually
  scanning N records.
- Composes cleanly with ADR-0016: `analyze-belief | summarize-belief`
  becomes the canonical pipeline.
- `BELIEF_CONSISTENCY_ANALYSIS_VERSION` and
  `BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION` are versioned contracts;
  bumping either is a deliberate breaking change.
- The narrow descriptive-statistics scope prevents creep into
  evaluation territory.

**Negative.**

- An operator may be tempted to read calibration claims into a
  `covariance_trace_mean` paired with a large `position_error_max_m`.
  The ADR's "description is not evaluation" clause must be cited
  whenever that comes up; we will revisit only when a separate
  evaluation ADR lands.
- Pipeline now requires two CLI invocations (`analyze-belief` then
  `summarize-belief`) instead of one. Justified because keeping
  alignment policy (ADR-0016) and aggregation policy (ADR-0017)
  separately versionable is more valuable than command-line brevity.

## Alternatives Considered

1. **Embed the summary inside `BeliefTraceabilityReport`.** Rejected:
   couples ADR-0016's schema to ADR-0017's aggregation decisions; a
   new aggregate field forces ADR-0016 schema bumps.
2. **Take two MCAPs directly (truth, belief)** like
   `analyze-belief`. Rejected: duplicates the alignment logic of
   ADR-0016 and obscures the dependency. Composition via the report
   JSON makes the contract explicit.
3. **Add `std`, `variance`, `quartiles`, `percentiles`**. Rejected for
   v1: each adds at least one design decision (Bessel correction,
   percentile interpolation, bucketing) that merits its own ADR.
4. **Cross-field correlations** (e.g. `covariance_vs_error_ratio`).
   Rejected: implies a relationship the summary is not authorized to
   describe under the observational posture.
5. **Emit a single combined artifact (`analyze-belief` produces both
   the trace report and the summary)**. Rejected: violates the
   separation of "facts" (ADR-0016) from "descriptive statistics over
   the facts" (this ADR), and conflates two versioned contracts into
   one.

## Backward compatibility

Zero impact. New module, new public symbols, new CLI subcommand.
ADR-0013 (`RunSummary`) unchanged. ADR-0014 (`BehaviorTrace`)
unchanged. ADR-0015 (`NoisyGroundTruthEstimator`) unchanged. ADR-0016
(`BeliefTraceabilityReport`) unchanged.
