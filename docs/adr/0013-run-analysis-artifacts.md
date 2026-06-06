# ADR-0013 — Run Analysis Artifacts

## Status
Accepted (2026-06-06).

## Context

T4 made every captured run replayable and re-validatable. Inspecting a run
— answering "what actually happened?" — still requires manual iteration
through the MCAP message stream. Without aggregate views the evaluation
loop does not scale beyond toy runs.

The autonomy-under-uncertainty mission imposes harder constraints than a
generic analytics layer would face:

- Analysis output MUST be a **derived artifact**: never canonical truth,
  always recomputed from MCAP + final state.
- Analysis MUST be **offline only**. No HTTP, no metrics backend, no
  streaming, no live processing.
- Output MUST be **byte-deterministic** for identical inputs.
- The original MCAP MUST never be modified, even incidentally.
- No probabilistic computation, no ML, no anomaly detection, no
  predictive models, no alerting, no GUI, no dashboards.

## Decision

Add `project_ghost.analysis` subpackage with three primitives and one CLI
subcommand:

1. **`RunSummary`** — frozen dataclass whose fields are exactly the
   answers T5 must produce:

   - `run_id` (str): caller-supplied identifier.
   - `event_count`, `sensor_sample_count`, `actuator_command_count`,
     `state_transition_count` (int).
   - `healthy_sensor_count`, `unhealthy_sensor_count` (int): derived from
     the **final state's** `SensorHealthMap`, not from the replay stream.
   - `first_timestamp_ns`, `last_timestamp_ns`, `duration_ns`
     (int | None): replay window.
   - `event_type_counts`, `sensor_type_counts`, `actuator_type_counts`
     (dict[str, int]): histograms with alphabetically-sorted keys.
   - `final_state_hash` (str): SHA-256 hex digest of the canonically
     encoded final state.
   - `schema_version` (str).

2. **`build_run_summary(*, run_id, reader, final_state) -> RunSummary`** —
   single-pass walk over an `MCAPReplayReader`. Pure function: no clock
   reads, no random, no I/O beyond what the reader does. Histograms use
   sorted keys; counters use commutative-free integer addition in
   iteration order.

3. **`generate_run_report(summary, output_path)`** — writes a
   `run_report.json` with `{"schema_version": ..., "summary": {...}}`.
   JSON encoded with `sort_keys=True`, `indent=2`, `ensure_ascii=False`,
   UTF-8, trailing newline. Byte-deterministic.

4. **`ghost analyze-run`** CLI: argparse subcommand on a new top-level
   `ghost` entry point. Flags `--mcap`, `--state`, `--output`,
   `--run-id`.

The `final_state_hash` uses `telemetry.serialization.encode_to_bytes` —
the same canonical encoder T4 uses for capture. This is the only
runtime dependency on telemetry's encoding posture; it guarantees that
the same `(MCAP, final state)` pair always yields the same hash.

## Inputs

- An MCAP file produced by `telemetry.MCAPFileSink` (or any future
  compatible writer).
- A JSON file containing a serialized `VehicleState` snapshot in the
  encoding format produced by `telemetry.encode_to_bytes` /
  `telemetry.from_json_dict`.

## Outputs

- A single `run_report.json` file at the caller-specified path.

## Determinism

For identical `(MCAP bytes, final state bytes)` inputs within a fixed
`(CPython version, mcap library version, platform)`:

- The produced `RunSummary` is field-by-field equal.
- The encoded report bytes are byte-identical.

Guarantees rely on:

- MCAP iteration order is fixed by storage order (T4).
- `Counter` accumulations are additions in iteration order; integer
  arithmetic.
- Histogram keys are sorted alphabetically before storing.
- `json.dumps(..., sort_keys=True, indent=2, ensure_ascii=False)` is
  byte-stable in CPython for the same input dict.
- SHA-256 over canonical bytes is deterministic by spec.
- No clock reads, no random, no `os.environ` reads, no file timestamps
  embedded in output.

## Limitations

- **Cross-CPython-version byte equality is NOT guaranteed.** Float repr
  rules may shift between CPython releases. Same caveat as T4.
- **`state_transition_count` counts only mode-level transitions** —
  changes in the `(flight.flight_mode, mission.mode)` tuple. Pose drift,
  velocity drift, sensor health flicker do not increment this counter.
  Documented choice; integer-stable across replays.
- **Healthy/unhealthy sensor counts come from the FINAL state**, not the
  replay stream. A sensor that flapped during the run but ended OK
  counts as healthy. The replay stream's history is summarized
  separately by `sensor_type_counts` (number of samples per payload
  type).
- **`actuator_command_count` and `actuator_type_counts`** count any
  messages on channels prefixed with `/actuators/`. Until publishers
  exist for actuator commands, these counts are 0. The analyzer is
  ready for them.

## Explicit Exclusions

None of the following are implemented in T5 nor scheduled as follow-ups
to this milestone:

- Real-time / streaming analytics.
- Machine learning / AI summaries.
- Anomaly detection.
- Trend detection.
- Forecasting / predictive models.
- Alerting.
- Dashboards.
- Charts (PNG / SVG / PDF / HTML).
- Natural-language reports.
- Time-series databases.
- Metrics backends (Prometheus, OpenTelemetry, etc.).
- HTTP endpoints, sockets, RPC.
- Cross-run regression detection.
- Live telemetry processing.

If any of these is ever needed, it requires a new ADR explaining why
the offline-deterministic-derived stance was insufficient.

## Consequences

**Positive.**

- Project Ghost can answer the six T5 questions about any captured run.
- Run reports are themselves deterministic, joining the same replay
  audit chain as the underlying telemetry.
- Adding a new question to a future run summary means: one field on
  `RunSummary`, one block in `build_run_summary`, bump
  `SUMMARY_SCHEMA_VERSION`, regenerate the golden test fixture.

**Negative.**

- `SUMMARY_SCHEMA_VERSION` is a new versioned contract the project must
  maintain.
- Run reports duplicate information that lives in the MCAP; if both go
  out of sync (e.g., the report is regenerated against a different
  state), the SHA-256 of the final state is the audit trail that
  reveals the mismatch.

## Alternatives Considered

- **Custom binary format for the report.** Rejected: less inspectable
  than JSON, no tooling, harder to diff in code review.
- **Live in-process analysis attached to `EventBus`.** Rejected:
  violates "offline only" and conflates capture with derivation.
- **Persist analysis as additional MCAP channels.** Rejected: violates
  "never modify original telemetry."
- **Multi-file output (one JSON per histogram, etc.).** Rejected: more
  parts, more synchronization surface, no benefit.
- **Treat the final state as part of the MCAP (last `/state/nav`
  message).** Rejected: the MCAP may end mid-run; the final state is
  often a separately persisted artifact (e.g., the snapshot taken at
  shutdown). Keeping them separate makes the analyzer's contract
  explicit.
