"""Frozen dataclasses for run analysis artifacts (T5).

`RunSummary` is the **single output** of `analysis.summary.build_run_summary`.
It is a *derived* artifact — recomputed from MCAP + final state on demand,
never persisted as canonical truth. The canonical sources remain telemetry
capture, state snapshots, and the event stream.

The schema version is a string for ease of human reading in the JSON
output. Bumping it is a deliberate, breaking change that updates the
catalogue of test fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

SUMMARY_SCHEMA_VERSION: str = "1"


@dataclass(frozen=True)
class RunSummary:
    """Single-output dataclass describing a captured run.

    Field semantics:

    - ``run_id``: caller-supplied identifier (typically the MCAP basename
      without extension; CLI defaults to that).
    - ``event_count`` / ``sensor_sample_count`` /
      ``actuator_command_count``: total counts of messages observed on
      the corresponding channel prefixes.
    - ``state_transition_count``: number of changes in the
      ``(flight_mode, mission_mode)`` tuple across consecutive
      ``/state/nav`` messages. The first ``/state/nav`` counts as one
      transition (from undefined). Documented choice per ADR-0013.
    - ``healthy_sensor_count`` / ``unhealthy_sensor_count``: derived
      from the **final state's** ``SensorHealthMap``, not from the
      replay stream. "Healthy" means ``SensorHealth.OK``.
    - ``first_timestamp_ns`` / ``last_timestamp_ns`` /
      ``duration_ns``: replay window; ``None`` if the replay was empty.
    - ``event_type_counts`` / ``sensor_type_counts`` /
      ``actuator_type_counts``: histograms keyed by event type (e.g.,
      ``"mission_start"``), sensor payload class name (e.g.,
      ``"IMUPayload"``), or actuator command class name (e.g.,
      ``"DirectMotorCommand"``). Keys are sorted alphabetically by
      ``build_run_summary`` before being stored; this is the
      contractual ordering that guarantees byte-deterministic
      serialization.
    - ``final_state_hash``: SHA-256 hex digest of the canonically
      encoded final state. Uses
      ``telemetry.serialization.encode_to_bytes`` as the canonical
      encoder so the hash matches the bytes T4 would have written had
      the final state been published to a sink.
    - ``schema_version``: defaults to ``SUMMARY_SCHEMA_VERSION``;
      consumers SHOULD check this before parsing.
    """

    run_id: str
    event_count: int
    sensor_sample_count: int
    actuator_command_count: int
    state_transition_count: int
    healthy_sensor_count: int
    unhealthy_sensor_count: int
    first_timestamp_ns: int | None
    last_timestamp_ns: int | None
    duration_ns: int | None
    event_type_counts: dict[str, int]
    sensor_type_counts: dict[str, int]
    actuator_type_counts: dict[str, int]
    final_state_hash: str
    schema_version: str = SUMMARY_SCHEMA_VERSION
    # T6 (ADR-0014) backward-compatible extension. Counts the number of
    # events on the `/events` channel — i.e. the number of valid targets
    # for `traceability.build_behavior_trace`. Defaults to 0 so existing
    # construction sites continue to work; the field is populated by
    # `build_run_summary`.
    traceable_events_count: int = 0


__all__ = ["SUMMARY_SCHEMA_VERSION", "RunSummary"]
