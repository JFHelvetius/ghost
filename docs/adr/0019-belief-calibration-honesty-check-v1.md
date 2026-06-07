# ADR-0019 — Belief Calibration Honesty Check v1

## Status
Accepted (2026-06-07).

## Context

ADR-0015 introduced the first deliberate producer of *belief*: a
`VehicleState` whose `covariance_15x15` is non-None. The covariance is
a **caller-declared parameter**, not a quantity inferred from data —
documented explicitly in ADR-0015 and reinforced by the "Truth ≠
belief" framing.

ADR-0016 / 0017 / 0018 added the analytical machinery to **measure**,
**describe** and **compare** the gap between belief and truth at
increasing levels of aggregation. None of them perform the most
fundamental audit the mission framing demands:

> Given that the system declares its uncertainty, **is that declaration
> honest with respect to the empirical error?**

A system that calls itself "knowing when it does not know" cannot
operate on declared covariances whose internal consistency has never
been checked. Today, ADR-0015's estimator publishes any covariance the
caller chose; nothing in the pipeline asks whether the declared scale
is plausible given the observed errors. Every downstream analysis
(consistency summary, comparative deltas, future planners) inherits
this credibility gap.

ADR-0019 closes that gap with a **descriptive observational audit**:
for each record where belief carried a covariance, expose the ratio
between empirical error magnitude and declared uncertainty scale.
Aggregate the ratios over the report. **No verdict.** No "calibrated"
/ "overconfident" labels. No statistical tests. The operator reads
the numbers and forms hypotheses; the system explicitly refuses to do
so.

This is the same posture as ADR-0014 / 0016 / 0017 / 0018 — observation,
not inference. What is new is that the observation is now **about the
agent's own claim** rather than about the agent's behaviour.

## Decision

Add `project_ghost.analysis.calibration` module with:

1. **Models (frozen dataclasses).**
   - `BeliefCalibrationRecord(timestamp_ns, position_error_norm_m,
     orientation_error_rad, covariance_trace,
     covariance_sqrt_trace, position_error_to_uncertainty_ratio,
     orientation_error_to_uncertainty_ratio,
     usable_for_calibration, analysis_version)`
   - `BeliefCalibrationReport(source_belief_report_sha256,
     total_records, records_usable_for_calibration,
     records_not_usable, records, ratio aggregates, analysis_version)`

2. **Pure function.**
   - `analyze_belief_calibration(report, *,
     source_belief_report_sha256)` — single forward pass over
     `report.records`.

3. **Decoder / encoder / writer.** Same canonical JSON posture as
   ADR-0013 / 0016 / 0017 / 0018.

4. **CLI subcommand.**

   ```
   ghost analyze-calibration --belief-report PATH [--output PATH]
   ```

5. **Versioned contracts.**
   - `BELIEF_CALIBRATION_ANALYSIS_VERSION: int = 1`
   - `BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION: str = "1"`

### Per-record ratio definitions (frozen)

For each `BeliefTraceRecord r`:

- A record is **usable for calibration** iff
  `r.covariance_available is True` AND `r.covariance_trace is not None`
  AND `r.covariance_trace > 0`.
- When usable:
  - `covariance_sqrt_trace = sqrt(r.covariance_trace)`
  - `position_error_to_uncertainty_ratio =
    r.position_error_norm_m / covariance_sqrt_trace`
  - `orientation_error_to_uncertainty_ratio =
    r.orientation_error_rad / covariance_sqrt_trace`
- When not usable: the three derived fields are `None`.

### Dimensional honesty (documented, not hidden)

`covariance_trace` is the sum of the 15 diagonal elements of the
declared `covariance_15x15`. Those 15 elements have heterogeneous
units (m², (m/s)², rad², (m/s²)², (rad/s)²); the trace mixes them.
`sqrt(trace)` is therefore **not** a per-axis position standard
deviation. It is an **upper bound on any single per-axis standard
deviation** declared by the agent (because the trace bounds each
eigenvalue from above for any PSD matrix). This makes the ratios:

> Lower bounds on "error magnitude / per-axis declared std".

A ratio much greater than 1 is a robust signal that the declared
covariance cannot support the observed error scale. A ratio
small relative to 1 is **inconclusive** under this V1 (it could mean
the covariance is well-scaled OR that other state dimensions absorb
the trace; the operator interprets given context).

This is the most honest signal available **without modifying the
ADR-0016 schema**. A future ADR may extend `BeliefTraceabilityReport`
to expose per-block covariance traces (position-only, orientation-only,
etc.), enabling per-axis-scaled ratios. That extension is out of v1
scope and would supersede the dimensional disclaimer above.

### Provenance

`BeliefCalibrationReport.source_belief_report_sha256` carries the
SHA-256 hex of the bytes of the input `belief_report.json`. Computed
by the CLI; required (validated) for library callers. Same auditing
model as ADR-0018 / 0019 manifests.

## Inputs

- A `BeliefTraceabilityReport` (in-memory) plus the SHA-256 of its
  source bytes — or, via CLI, a path to its JSON file.

## Outputs

- A `BeliefCalibrationReport` dataclass instance.
- A canonical JSON envelope `{"schema_version": "1", "calibration":
  {...}}`.

## Limits

- The ratios are **dimensionally impure**. Their interpretation as
  honesty signal is documented above and must travel with the
  artifact.
- V1 cannot distinguish "covariance well-scaled per axis" from
  "covariance unjustifiably large in non-position dimensions". A ratio
  much less than 1 is **not** evidence of good calibration.
- Records without covariance are exposed as `usable_for_calibration =
  False` with `None` ratios; they count in `records_not_usable` and
  do not contribute to aggregates.
- This is **not** a NEES / NIS / Mahalanobis statistical test. No
  p-value, no chi-square gate, no threshold-based classification.
- The report does **not** label any record or run as
  "calibrated" / "uncalibrated" / "overconfident" / "underconfident".
  Such verdicts would require statistical framing this ADR explicitly
  rejects.
- Empty input (zero records) or zero usable records produce a
  well-defined empty report: all ratio aggregates `None`, both counts
  zero.

## Determinism

For identical input `BeliefTraceabilityReport` + SHA-256 within fixed
CPython:

- `analyze_belief_calibration` produces a field-by-field equal
  `BeliefCalibrationReport`.
- The encoder produces byte-identical UTF-8 JSON.
- SHA-256 of the encoded bytes is stable across processes.

The module:

- Reads no clock, no random.
- Performs no I/O beyond `hashlib.sha256` on bytes provided to the CLI.
- Holds no thread-local state.
- Uses only stdlib (`math`, `hashlib`, `json`, `dataclasses`,
  `pathlib`, `collections.abc`). **No numpy** — input ratios are
  read as plain `float` from the source dataclasses.

## Exclusions (explicit non-goals)

NOT implemented and NOT extension points sanctioned by this ADR:

- **Verdicts.** No "calibrated" / "uncalibrated" / "overconfident" /
  "underconfident" boolean. No traffic-light status.
- **Statistical tests.** No NEES, NIS, Mahalanobis distance,
  chi-square gates, p-values, confidence intervals, bootstrap.
- **Thresholds.** No "ratio > 3 means X" rule. The operator interprets.
- **Classification of records or runs.**
- **Scoring of estimators** ("estimator A is better calibrated than
  B").
- **Anomaly / outlier detection** over the ratio distribution.
- **Percentiles / quartiles / std / variance / histograms** over the
  ratios. Only min / max / mean — same posture as ADR-0017.
- **Recommendations** ("consider increasing σ_pos to X").
- **Modification of ADR-0015** (the noisy GT estimator) — this ADR
  does NOT change how covariance is declared; it audits what is
  declared.
- **Modification of ADR-0016 schema.** Per-block covariance traces
  are deferred to a future ADR that would supersede the dimensional
  disclaimer.
- **Recomputation of the source covariance.** The audit consumes the
  trace as published by ADR-0016.
- **MCAP reanalysis.** Pure derivation from the JSON artifact.
- **HTML / PDF / charts / dashboards / NL / LLM / ML / embeddings.**

**Cláusula reforzada:**

> *Description is not calibration. Exposing a ratio is not declaring
> calibration honest or dishonest. The system exposes the numbers; the
> operator interprets.*

## Consequences

**Positive.**

- The system finally audits its own uncertainty claims. The agent's
  declared covariance can no longer be silently dishonest — the
  ratios make any order-of-magnitude mismatch visible.
- The audit is **purely observational** and stays within the project's
  posture. No new dependency, no new analytical pretense.
- Every future capability that depends on covariance gains a sanity
  check it could not have had before.
- Honest framing of dimensional limits prevents the artifact from
  being misread as a statistical calibration certificate.

**Negative.**

- A ratio close to 1 does not certify calibration. Operators must
  resist treating the artifact as a verdict. The cláusula must be
  cited whenever this surfaces.
- Without per-block covariance traces (deferred), the audit's signal
  is one-sided: it detects gross overconfidence but cannot
  distinguish well-scaled covariance from
  large-in-other-dimensions covariance.
- Each new mission-relevant artifact requires its own ADR (no
  shortcuts). Justified because the project's credibility depends
  precisely on this discipline.

## Alternatives Considered

1. **Implement NEES / NIS classical statistical tests.** Rejected:
   requires statistical framing ("p < 0.05 means…") that the project's
   observational posture refuses. NEES specifically requires per-axis
   variances which the current `BeliefTraceabilityReport` does not
   expose.
2. **Extend `BeliefTraceabilityReport` (ADR-0016) to expose per-block
   covariance traces.** Rejected for v1: defensible but modifies a
   prior ADR. Deferred to a separate ADR (ADR-0020 or later) that
   would supersede this one's dimensional disclaimer.
3. **Output a calibration verdict (boolean or traffic light).**
   Rejected: any threshold is arbitrary; the operator must decide.
4. **Embed full covariance matrices in the calibration report.**
   Rejected: the trace is sufficient for V1's observational signal
   and avoids artifact bloat.
5. **Make the artifact a sub-section of `BeliefConsistencySummary`
   (ADR-0017).** Rejected: couples two versioned contracts. ADR-0019
   stays separate and ADR-0017 unchanged.

## Backward compatibility

Zero impact. New module, new public symbols, new CLI subcommand.
ADR-0013 / 0015 / 0016 / 0017 / 0018 and their modules / CLIs are
unchanged.

## Mission posture

This ADR is the first ADR explicitly evaluated against the project's
central mission question:

> *What does the agent really know, what does it believe it knows,
> and what are the consequences of the difference?*

It addresses the **second clause** of that question — what the agent
*believes it knows* — by auditing whether the agent's claim about
its uncertainty is internally consistent with the errors observed.
It is the foundation that makes every future claim about
"the agent knowing when it does not know" verifiable rather than
asserted.
