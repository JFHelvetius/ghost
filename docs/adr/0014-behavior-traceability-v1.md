# ADR-0014 — Behavior Traceability v1

## Status
Accepted (2026-06-06).

## Context

T5 (ADR-0013) lets a user ask **what** happened in a run. The next
natural question is **why**: given an event, what messages preceded it?

"Behavior traceability" is a heavily-loaded term in autonomous systems
literature. Without a sharp definition the concept slides quickly into
inference engines, scoring, and counterfactual reasoning — none of
which fit Project Ghost's mission constraints.

This ADR commits to one specific, narrow meaning of behavior
traceability:

> Reconstruction, from existing captured artifacts, of the observable
> sequence of messages that preceded a target event within a
> configurable time window.

That is **all** the system does. The points listed under "Exclusions"
below are not extension hooks — they are explicit non-goals.

## Decision

Add `project_ghost.traceability` package with:

1. **`TracedMessage`** — frozen dataclass capturing a compact summary
   of an observed message: ``channel``, ``log_time_sim_ns``,
   ``schema_name``, ``summary`` (small JSON-primitive dict of selected
   payload fields).

2. **`BehaviorTrace`** — frozen dataclass with:
   - ``event_id`` (int): the target event's ``sequence`` field.
   - ``event_type`` (str): the target event's ``type`` field.
   - ``preceding_events``, ``preceding_sensor_samples``,
     ``preceding_actuator_commands``, ``preceding_state_changes``
     (tuple[TracedMessage, ...]): four typed lists, each ordered by
     ``log_time_sim_ns`` ascending. No ranking, no weights, no
     selection criterion beyond "the message appeared in this channel
     category and in the window."
   - ``window_start_ns``, ``window_end_ns`` (int).
   - ``schema_version`` (str).

3. **`build_behavior_trace(*, reader, event_id, window_ns)`** — single
   forward pass through the replay reader. Buffers messages until the
   target event is encountered; raises ``EventNotFoundError`` if it
   isn't. Filters the buffered messages to the window
   ``[event_time - window_ns, event_time)`` and categorizes them.

4. **`generate_trace_report(trace, output)`** — JSON serializer.
   ``output`` can be a path (file) or a writable text stream
   (``sys.stdout``). Same encoding posture as T5:
   ``sort_keys=True, indent=2, ensure_ascii=False``, trailing newline.

5. **`ghost trace-event --mcap PATH --event-id ID --window-seconds N``**
   — CLI subcommand. Outputs JSON to stdout. ``--window-seconds``
   accepts a float; conversion to nanoseconds is
   ``int(window_seconds * 1_000_000_000)``.

State changes are defined identically to T5: a ``/state/nav`` message
counts as a state change when its ``(flight_mode, mission_mode)``
tuple differs from the immediately-preceding ``/state/nav`` message
(regardless of whether the predecessor falls in the window).

## Inputs

- An MCAP file written by ``telemetry.MCAPFileSink`` (read-only).
- ``event_id``: an integer matching the ``sequence`` field of the
  target Event.
- ``window_ns``: non-negative integer; ``0`` is a legal value that
  yields an empty trace.

## Outputs

- A ``BehaviorTrace`` dataclass instance.
- A JSON document of the trace (via ``generate_trace_report``).

## Limits

- The trace covers ONLY messages whose ``log_time_sim_ns`` falls in
  ``[event_time - window_ns, event_time)``. Messages at or after the
  target event are excluded.
- "State changes" track mode-tuple transitions only. Pose drift,
  velocity drift, sensor health flicker do NOT count as state changes.
- Messages without channel categorization (anything outside ``/events``,
  ``/state/nav``, ``/sensors/*``, ``/actuators/*``) are ignored.
- If ``event_id`` is not found before the end of the reader,
  ``EventNotFoundError`` is raised.

## Determinism

For identical ``(MCAP bytes, event_id, window_ns)`` inputs within a
fixed ``(CPython, mcap library, platform)``:

- The produced ``BehaviorTrace`` is field-by-field equal.
- The encoded report bytes are byte-identical.

The trace generation is single-pass and pure: no clock reads, no
random, no thread context, no I/O beyond what the reader does.

## Exclusions (explicit non-goals)

The following are NOT implemented and are NOT extension points
sanctioned by this ADR. Any introduction of these would require a new
ADR explaining why the observational stance was insufficient:

- AI / ML / scoring.
- Anomaly detection / trend detection / forecasting / alerting.
- Reasoning engines / expert systems.
- Graph databases.
- Runtime tracing (only offline replay-based tracing).
- Threads / async / networking.
- Probabilistic causality.
- Counterfactual reasoning.
- Backwards-in-time inference ("if X had not happened, would Y still
  have happened?").
- Cross-event correlation analysis.
- Ranking, weighting, or selection of "relevant" messages.

## "Traceability is not explanation"

This system reconstructs **observed sequences**. It does NOT:

- interpret intent;
- assign blame;
- compute weights or scores;
- order by likelihood;
- infer semantic causality.

If a sensor sample appears in the window before a
``SAFETY_VIOLATION`` event, that does **not** mean the sample caused
the violation. It means the sample was captured before the violation
within the chosen time window. A human inspecting the trace can form
their own hypothesis; the system explicitly refuses to do so.

The system tells you **what** happened in the window. It does not
tell you **why**.

## Consequences

**Positive.**

- Project Ghost can answer the four T6 questions about any captured
  event in any captured run, deterministically and offline.
- The narrow observational definition prevents scope creep into
  inference territory.
- Adding the optional ``traceable_events_count`` field to
  ``RunSummary`` is a backward-compatible extension (default = 0).

**Negative.**

- Users may be tempted to read causal meaning into ordered
  pre-event lists. The ADR's "not explanation" clause must be cited
  whenever this assumption is made.
- The schema version of ``BehaviorTrace`` is now a new versioned
  contract. Future field additions remain backward-compatible;
  removals or semantic changes require bumping the version.

## Alternatives Considered

1. **Inferential traceability with weights** — Rejected. Violates "no
   IA / no scoring" and the truth ≠ belief principle.
2. **Graph-database backed causal analysis** — Rejected. Violates "no
   graph databases" and is overkill for observational reconstruction.
3. **Bidirectional traceability (effects → causes AND causes →
   effects)** — Rejected. Effects → causes requires either ranking or
   guessing, neither of which is permitted. The current direction
   (target event ← preceding observations) is purely observational.
4. **Live in-process tracing via EventBus instrumentation** —
   Rejected. Violates "offline only".

## Backward compatibility

`RunSummary` gains one optional field, ``traceable_events_count``,
with default ``0``. Existing code that constructs ``RunSummary``
without this argument continues to work. Existing JSON reports gain
one new key alphabetically among the existing summary fields.
``SUMMARY_SCHEMA_VERSION`` is NOT bumped: the change is a
backward-compatible addition.
