# ADR-0018 — Comparative Belief Analysis with Provenance Manifests v1

## Status
Accepted (2026-06-07).

## Context

ADR-0013 / 0014 / 0016 / 0017 give Ghost a complete intra-run analysis
chain. After ADR-0017 an investigator can describe a run with a
single JSON artifact (`BeliefConsistencySummary`). What they **cannot**
do is compare runs to each other in a structured, deterministic, and
auditable way.

In practice this means:

1. The next manual task an investigator faces after ADR-0017 is
   opening two (or N) JSONs and computing deltas by hand.
2. There is no formal way to declare *what configuration* produced a
   given summary — the linkage is informal, file-name-based, and
   fragile.
3. There is no way to verify that the artifacts a summary claims to
   describe still match the bytes on disk months later.

ADR-0017 §"Description is not evaluation" prevents the summary itself
from growing comparison primitives. This ADR commits to two **new**
artifacts that together close the gap:

- **`RunManifest`** — content-addressed provenance: SHA-256 of every
  declared input and output, plus the opaque config descriptor the
  caller chose.
- **`ComparativeBeliefReport`** — N-way structured deltas between
  multiple `BeliefConsistencySummary` instances, with each label's
  manifest passed through as provenance.

Both are pure, deterministic, stdlib-only, JSON-only — same posture
as the rest of the analysis layer.

This ADR changes the **dimension** of analysis available to Ghost
(intra-run → inter-run); it does not introduce a new mode of
analysis (no inference, no evaluation, no recommendation).

## Decision

Add `project_ghost.analysis.comparison` module with:

1. **Models (frozen dataclasses).**
   - `ManifestArtifact(path, sha256, kind)`
   - `RunManifest(run_id, config_descriptor, inputs, outputs)`
   - `LabeledSummary(label, summary, manifest)`
   - `MetricDelta(baseline_label, baseline_value, values, deltas)`
   - `ComparativeBeliefReport(baseline_label, labels, metrics,
     manifests, analysis_version)`

2. **Pure functions.**
   - `build_run_manifest(*, run_id, config_descriptor, inputs,
     outputs)`: hashes every file at the given path.
   - `verify_run_manifest(manifest)`: re-hashes referenced files and
     reports `(ok, messages)`. Audit primitive; reads disk, writes
     nothing.
   - `build_comparative_report(labeled_summaries)`: single forward
     pass; deltas vs baseline; manifests pass-through.

3. **Decoders.**
   - `decode_run_manifest_from_json(data)`
   - `decode_consistency_summary_from_json(data)` (companion to the
     ADR-0016 decoder; needed because ADR-0017 did not expose one)
   - `decode_comparative_report_from_json(data)`

4. **Encoders + writers (canonical JSON).**
   - `encode_run_manifest_to_bytes(manifest)`
   - `encode_comparative_report_to_bytes(report)`
   - `generate_run_manifest(manifest, output_path)`
   - `generate_comparative_report(report, output_path)`

5. **Constants (versioned contracts).**
   - `RUN_MANIFEST_SCHEMA_VERSION: str = "1"`
   - `BELIEF_COMPARISON_REPORT_SCHEMA_VERSION: str = "1"`
   - `BELIEF_COMPARISON_ANALYSIS_VERSION: int = 1`

6. **CLI subcommands.**

   ```
   ghost build-manifest
       --run-id ID
       [--config-json PATH]
       [--config-kv KEY=VALUE ...]
       [--input PATH=KIND ...]
       [--output-artifact PATH=KIND ...]
       [--output PATH]
   ```

   ```
   ghost compare-belief
       --summary  LABEL=PATH ...
       [--manifest LABEL=PATH ...]
       [--output PATH]
   ```

   Both write canonical JSON either to `--output` or to stdout.
   `--summary` accepts ≥1 path; the first is the baseline.

### Aggregation rules (frozen)

| Metric | `deltas[label]` |
|---|---|
| `value` and `baseline_value` both non-`None` | `value - baseline_value` |
| Either is `None` | `None` |
| `label == baseline_label` with non-`None` baseline | `0` of matching type |

The metric set is exactly the 20 numeric fields of
`BeliefConsistencySummary` (excluding `analysis_version`). The set is
closed: any change requires bumping
`BELIEF_COMPARISON_ANALYSIS_VERSION`.

### Provenance

`RunManifest.config_descriptor` is an opaque JSON-safe mapping. Its
contents are caller's responsibility; the only contract is JSON
serializability, validated at construction time.

`build_run_manifest` computes SHA-256 from disk at build time with
1 MiB buffered chunks via `hashlib`. `verify_run_manifest` re-computes
them on demand. Path strings are preserved verbatim — no symlink
resolution, no canonicalization.

## Inputs

- **CLI `build-manifest`**: filesystem paths + a free-form
  `config_descriptor` (JSON file and/or KV pairs).
- **CLI `compare-belief`**: ≥1 `BeliefConsistencySummary` JSON files
  produced by `ghost summarize-belief` (ADR-0017), optionally paired
  with `RunManifest` JSON files produced by `ghost build-manifest`.
- **Library**: `RunManifest`, `Sequence[LabeledSummary]`.

## Outputs

- A `RunManifest` dataclass + canonical JSON.
- A `ComparativeBeliefReport` dataclass + canonical JSON.

## Limits

- The comparative report covers ONLY paired summaries provided by the
  caller. There is no automatic discovery, no globbing, no querying.
- Only `min`, `max`, `mean` over the 20 numeric fields propagate to
  the comparison via deltas. No `std`, no variance, no percentiles,
  no quartiles.
- `timestamp_span_ns` deltas use the simple subtraction `last -
  first` from each summary's stored values; the comparison does NOT
  align timestamps across runs.
- The summary does NOT cross-correlate fields (e.g., "trace vs error",
  "timestamp vs covariance"). Such artifacts belong to separate ADRs.
- `RunManifest.config_descriptor` is opaque — the comparison does NOT
  parse it to detect "which knob changed". The operator inspects.
- `verify_run_manifest` reads disk; its return value is therefore
  filesystem-state dependent. Documented as the only function in
  this module that is not deterministic.

## Determinism

For identical inputs within a fixed `(CPython, stdlib)`:

- `build_run_manifest` produces byte-identical `RunManifest` instances
  (file SHA-256 is stable by the `hashlib` standard).
- `build_comparative_report` produces field-by-field equal reports.
- Both encoders produce byte-identical UTF-8 JSON.
- SHA-256 of the encoded bytes is stable across processes.

Manifests stored with absolute paths are reproducible only on the
same filesystem layout. Manifests stored with relative paths (paths
declared at build time relative to a stable root) are
location-independent and the SHA-256 of the encoded manifest is
stable across machines.

The module:

- Reads no clock.
- Performs no I/O beyond explicit file reads in `build_run_manifest`
  and `verify_run_manifest`.
- Holds no thread-local state.
- Uses no random.
- Uses no `time`, `datetime`, `threading`, `asyncio`.
- Has zero new dependencies — `hashlib` and `json` are stdlib.

## Exclusions (explicit non-goals)

NOT implemented and NOT extension points sanctioned by this ADR:

- **Ratios** (`value / baseline`). Only deltas.
- **Statistics over labels** (mean of deltas, std of values).
- **Significance tests, p-values, confidence intervals**.
- **Rankings** ("best to worst").
- **Outlier detection across labels**.
- **Clustering of runs** by similarity.
- **Aggregation across config_descriptors** (e.g. "average seed").
- **HTML / PDF / Markdown / charts / dashboards / histograms**.
- **NL summaries, LLM, embeddings, ML, classification**.
- **Watch mode, daemon mode, streaming**.
- **Signing of manifests** (GPG, x509).
- **Path canonicalization / symlink resolution**.
- **Record-level comparison** between two
  `BeliefTraceabilityReport` (different artifact, different ADR).
- **Automatic provenance discovery** ("find the manifest for this
  summary"). The pairing is the caller's choice.

## "Description is not evaluation. Comparison is not judgment."

A row in `metrics["position_error_max_m"]` showing a delta of
`+0.42 m` is two numbers stated side by side. The report:

- does NOT assert that the run with the larger error was "worse",
- does NOT assert calibration claims when paired with a small
  covariance trace,
- does NOT score, rank, alert, or recommend,
- does NOT infer which knob in `config_descriptor` caused the delta.

The operator reads the deltas, consults the manifests, and forms
their own hypothesis. The system refuses to do so.

## Consequences

**Positive.**

- Ghost stops being a single-sample microscope and becomes an
  ablation bench. Parameter sweeps, regression tests of estimators,
  seed sensitivity studies, and scenario benchmarks reduce to
  "produce N summaries + N manifests + one `compare-belief`."
- Provenance becomes content-addressed and auditable.
  `verify_run_manifest` lets a researcher confirm — months after a
  run — that the artifacts the summary referenced are still the
  ones on disk.
- Every future investigative ADR (multi-seed ensemble, scenario
  comparison, estimator regression) can be authored on top of this
  primitive without re-inventing comparison logic.
- Two new artifacts, both versioned: the contract bumps are
  intentional and tracked.

**Negative.**

- The investigator now runs two CLIs (`summarize-belief` then
  `compare-belief`) and optionally a third (`build-manifest`) per
  run. Justified because keeping ADR-0016 / 0017 / 0018 contracts
  independently versionable is more valuable than CLI brevity.
- Manifests with absolute paths are not location-portable. A new
  ADR can introduce a path-normalization convention if portability
  becomes the dominant requirement.
- Investigators may treat large deltas as quality judgments. The
  "Description is not evaluation" clause must be cited whenever the
  assumption surfaces.

## Alternatives Considered

1. **Embed the summary inside the comparative report**. Rejected:
   couples ADR-0017's schema to ADR-0018's aggregation; a new metric
   would force a coupled bump.
2. **Take two MCAPs directly in `compare-belief`** (skip the
   summary step). Rejected: duplicates ADR-0016's alignment logic
   and hides the dependency.
3. **Add ratios, percentiles, std, variance**. Rejected: each adds a
   design decision (Bessel correction, percentile interpolation, etc.)
   that merits its own ADR. v1 holds the line at min/max/mean +
   deltas.
4. **Cross-field correlations** (e.g.,
   `covariance_vs_error_ratio`). Rejected: implies a relationship
   the comparative artifact is not authorized to describe.
5. **Single combined artifact (`summarize-belief` produces both
   summary and provenance)**. Rejected: conflates two versioned
   contracts and breaks the separation between "facts about one run"
   and "comparison between runs".

## Backward compatibility

Zero impact. New module, new public symbols, two new CLI subcommands.
ADR-0013, ADR-0015, ADR-0016, ADR-0017 and their modules / CLIs are
unchanged.
