# ADR-0016 — Belief Traceability Report v1

## Status
Accepted (2026-06-07).

## Context

ADR-0015 introduced the project's first deliberate producer of
**belief**: a `VehicleState` whose `covariance_15x15 is not None`,
distinct from the truth-bearing `VehicleState` published by
`vehicle_state_from_ground_truth`. Project Ghost now contains two
parallel realities for any captured run:

1. **Ground truth** — the simulator's oracle.
2. **Belief** — what the perturbation-based estimator (or, eventually,
   a real estimator) published.

The mission obligation from ADR-0009 §6 — *the system must know when
it knows* — has, until now, been claimed but not auditable. An
operator inspecting a captured run could read either reality but had
no derived artifact answering the four questions this ADR commits to:

> **What was true. What was believed. How different were they. What
> covariance accompanied that belief.**

This ADR commits to one specific, deliberately narrow mechanism:

> A **purely observational** report that aligns truth and belief
> streams by `stamp_sim_ns`, computes per-sample positional /
> orientation error and per-sample covariance diagnostics
> (trace and condition number), and emits an aggregated JSON document.

That is **all** the system does. The points listed under "Exclusions"
below are not extension hooks — they are explicit non-goals.

The framing matches the one ADR-0014 took for behavior traceability:
this is **traceability, not explanation**. It tells the operator what
the two realities looked like; it does NOT interpret the discrepancy,
score it, flag anomalies, or recommend corrective action.

## Decision

Add `project_ghost.analysis.belief_traceability` module with:

1. **`BeliefTraceRecord`** — frozen dataclass for a single aligned
   (truth, belief) sample:
   - `timestamp_ns` (int): `stamp_sim_ns` shared by the two inputs.
   - `truth_position_xyz`, `belief_position_xyz`
     (`tuple[float, float, float]`): ENU position in meters.
   - `truth_orientation_xyzw`, `belief_orientation_xyzw`
     (`tuple[float, float, float, float]`): quaternion in **scipy
     order** ``[x, y, z, w]``. Internal computations use the
     codebase's Hamilton ``[w, x, y, z]`` convention; the conversion
     happens at the record boundary because scipy ordering is the
     external de-facto standard and the explicit suffix in the field
     name removes ambiguity for downstream consumers.
   - `position_error_norm_m` (float): Euclidean norm
     of ``belief_position - truth_position``.
   - `orientation_error_rad` (float): angle between the two unit
     quaternions, computed as ``2 * arccos(|dot(q_truth, q_belief)|)``
     in Hamilton space (the absolute value accounts for the
     double-cover of unit quaternions).
   - `covariance_trace` (`float | None`): trace of the
     ``covariance_15x15`` carried by the belief state, or `None` if
     belief has no covariance or the trace is non-finite.
   - `covariance_condition_number` (`float | None`): spectral
     condition number ``λ_max / λ_min`` of the covariance, or `None`
     if belief has no covariance or the value is non-finite (zero
     eigenvalue, ill-conditioned).
   - `covariance_available` (bool): `True` iff the belief state
     carried a non-`None` ``covariance_15x15``.
   - `analysis_version` (int): equals
     `BELIEF_TRACEABILITY_ANALYSIS_VERSION`.

2. **`BeliefTraceabilityReport`** — frozen dataclass:
   - `total_samples` (int): length of `records`.
   - `samples_with_covariance` /
     `samples_without_covariance` (int): partition of `records` by
     `covariance_available`.
   - `mean_position_error_m`, `max_position_error_m` (float):
     aggregates over `records`. Empty input → both `0.0` (documented
     convention; the empty-set mean has no canonical value, and
     emitting `0.0` keeps the JSON schema flat).
   - `mean_orientation_error_rad`,
     `max_orientation_error_rad` (float): same posture.
   - `records` (`tuple[BeliefTraceRecord, ...]`): preserved in input
     order; the report does NOT re-sort.
   - `analysis_version` (int): equals
     `BELIEF_TRACEABILITY_ANALYSIS_VERSION`.

3. **`compute_position_error(truth_pos, belief_pos)`** — pure,
   side-effect-free Euclidean norm.

4. **`compute_orientation_error(truth_q_wxyz, belief_q_wxyz)`** —
   pure angle-between-rotations in radians. Hamilton ``[w, x, y, z]``
   input.

5. **`build_traceability_report(*, truth, belief)`** — single forward
   pass:
   - `truth`, `belief`: each a `Sequence[VehicleState]`.
   - Requires equal length; raises `ValueError` otherwise.
   - Requires per-index `stamp_sim_ns` equality; raises `ValueError`
     naming the first mismatched index otherwise.
   - Produces one `BeliefTraceRecord` per aligned pair, in input order.

6. **`encode_belief_report_to_bytes(report)`** — JSON serializer using
   the same encoding posture as ADR-0013 reports:
   ``sort_keys=True``, ``indent=2``, ``ensure_ascii=False``, trailing
   newline, UTF-8.

7. **`generate_belief_report(report, output_path)`** — writes the
   bytes to disk; pure write, no path invention.

8. **`ghost analyze-belief --truth-mcap PATH --belief-mcap PATH
   [--output PATH]`** — CLI subcommand. Reads `VehicleState` records
   from each MCAP via `telemetry.MCAPReplayReader` + decoder catalog
   (ADR-0013 / T4), builds the report, writes JSON to `--output` or
   stdout. JSON only. No text report. No natural language. No charts.

`BELIEF_TRACEABILITY_ANALYSIS_VERSION` is `1`. Bumping it is a
deliberate breaking change.

## Inputs

- A pair of `VehicleState` sequences (in-memory) **or** a pair of MCAP
  files whose records decode to `VehicleState`.
- Truth and belief must be aligned: same length, same
  `stamp_sim_ns` per index. The report does not interpolate, resample,
  align by nearest neighbor, or guess.

## Outputs

- A `BeliefTraceabilityReport` dataclass instance.
- A JSON document of the report (via `encode_belief_report_to_bytes`
  or `generate_belief_report`).

## Limits

- The report covers ONLY paired samples. Truth-only or belief-only
  samples are NOT carried through; alignment must be done by the
  caller (typically by a runtime that publishes both streams
  synchronously).
- Covariance diagnostics are restricted to **trace** and **condition
  number**. The full matrix is NOT embedded in the report; consumers
  who need it should read the source MCAP.
- "Orientation error" is the rotation magnitude, not a signed axis or
  Euler-angle decomposition.
- Aggregates over empty inputs are emitted as `0.0` by convention,
  not as `null` or NaN. `total_samples == 0` is the unambiguous signal
  that the aggregates carry no information.

## Determinism

For identical `(truth, belief)` input sequences within a fixed
`(CPython, numpy)`:

- The produced `BeliefTraceabilityReport` is field-by-field equal.
- The encoded report bytes are byte-identical.
- For CLI: identical input MCAPs produce identical output JSON bytes
  within the same `(CPython, numpy, mcap library)` triple.

The build function:

- Reads no clock.
- Performs no I/O beyond what the reader does (for the CLI path).
- Holds no thread-local state.
- Uses no random.

## Exclusions (explicit non-goals)

The following are NOT implemented and are NOT extension points
sanctioned by this ADR. Any introduction of these would require a new
ADR explaining why pure observation was insufficient and what the
new artifact's honest framing would be:

- **Planners / controllers / path optimization**.
- **Kalman / Bayesian / particle / smoothing filters**.
- **SLAM / localization / sensor fusion**.
- **Anomaly detection / trend detection / forecasting**.
- **Alerting / paging / notifications**.
- **Confidence scoring / risk scoring**.
- **Recommendations / autonomous decisions**.
- **Machine learning / neural networks**.
- **Dashboards / GUI / plotting / charts**.
- **Natural-language summaries**.
- **Cross-sample causality**.
- **Estimation-quality scoring** (e.g., NEES / NIS, consistency
  metrics). Adding such metrics is a deliberate new artifact, not an
  extension of this one.

## "Traceability is not estimation, not evaluation"

This module reconstructs **paired observations**. It does NOT:

- correct belief from truth;
- score how good the belief was;
- compute consistency metrics (NEES / NIS) that require statistical
  framing of "good";
- decide whether a covariance was justified;
- decide whether the system "knew when it did not know" — that
  judgment is the operator's, reading these records.

If `position_error_norm_m` is large while `covariance_trace` is
small, the report does NOT call that "overconfident". It records the
two numbers; the operator forms the hypothesis. The system explicitly
refuses to do so.

The report tells you **what** was true and what was believed. It does
not tell you **whether the belief was good**.

## Consequences

**Positive.**

- Project Ghost can answer the four questions about any captured run
  where both truth and belief streams are available.
- The narrow observational definition prevents scope creep into
  estimation-quality / inference territory.
- The artifact composes cleanly with ADR-0015: the noisy-GT estimator
  produces belief, the truth aggregator produces truth, and this
  report makes the gap explicit and auditable.
- `BELIEF_TRACEABILITY_ANALYSIS_VERSION` is a versioned contract;
  bumping it is a deliberate breaking change.

**Negative.**

- Operators may be tempted to read "small error + small covariance =
  good estimator" or "large error + small covariance = overconfident
  estimator". The ADR's "not evaluation" clause must be cited
  whenever this assumption is made; we will revisit if and when a
  separate estimation-quality artifact lands under its own ADR.
- The strict alignment requirement (same length, same stamps)
  pushes the burden of stream synchronization onto the producer.
  Justified because alignment policies (nearest neighbor,
  interpolation, time-warp) are themselves design decisions that
  would belong in a separate ADR.

## Alternatives Considered

1. **Embed full covariance in records** — Rejected. Bloats the report
   and duplicates data already on disk in the source MCAP. Trace +
   condition number are sufficient for the "what covariance" question
   in the ADR-0009 §6 obligation.
2. **Compute NEES / NIS consistency metrics** — Rejected. Requires
   statistical framing of "good" that the observational stance
   refuses. Belongs in a separate ADR if and when the project decides
   it needs evaluation, not traceability.
3. **Alignment by nearest neighbor / interpolation** — Rejected.
   Embeds a policy decision in the report builder. Strict alignment
   pushes the synchronization to the producer where it belongs.
4. **Per-channel reports (one per estimator)** — Rejected for v1.
   The current architecture has one belief producer; if multiple
   land, a new ADR will decide whether to extend this report or
   emit one per channel.
5. **Live in-process reporting** — Rejected. Violates "offline only"
   posture established in ADR-0013 / ADR-0014.

## Backward compatibility

Zero impact on existing artifacts. New module, new public symbols,
new CLI subcommand. `RunSummary` (ADR-0013) is unchanged.
`BehaviorTrace` (ADR-0014) is unchanged.
