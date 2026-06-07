"""Frozen dataclasses for behavior traceability (T6, ADR-0014).

Two types:

- ``TracedMessage``: a compact record of an observed message — channel,
  log time, schema name, and a small ``summary`` dict of selected
  payload fields kept JSON-primitive.
- ``BehaviorTrace``: four ordered tuples of ``TracedMessage`` plus the
  identification of the target event and the window bounds.

Both are immutable. Their tuple fields are sorted by
``log_time_sim_ns`` ascending — no ranking, no scoring, no selection
criterion beyond "the message appeared in this channel category and
in the window."

"Traceability is not explanation": these types describe what was
observed. They do not interpret intent or assign weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TRACE_SCHEMA_VERSION: str = "1"


@dataclass(frozen=True)
class TracedMessage:
    """One observed message in compact form for behavior tracing.

    Fields:

    - ``channel``: full channel name (e.g., ``"/events"``,
      ``"/sensors/imu0"``).
    - ``log_time_sim_ns``: the message's ``log_time`` as stored in the
      MCAP.
    - ``schema_name``: the MCAP schema name registered for this message
      type. Fully qualified, e.g.,
      ``"project_ghost.events.types.Event"``.
    - ``summary``: a small dict of payload fields chosen per channel
      category. Always JSON-primitive (no numpy, no enums-as-instances,
      no nested dataclasses). Keys are stable per-category; values are
      raw decoded JSON.
    """

    channel: str
    log_time_sim_ns: int
    schema_name: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class BehaviorTrace:
    """Observational record of what preceded a target event.

    Fields:

    - ``event_id``: ``Event.sequence`` of the target event.
    - ``event_type``: ``Event.type`` of the target event (e.g.,
      ``"safety_violation"``).
    - ``preceding_events`` / ``preceding_sensor_samples`` /
      ``preceding_actuator_commands`` / ``preceding_state_changes``:
      tuples of ``TracedMessage`` ordered by ``log_time_sim_ns``
      ascending. No ranking, no scoring. Empty tuples are valid
      (e.g., a small window with nothing in it).
    - ``window_start_ns`` / ``window_end_ns``: the half-open window
      ``[window_start_ns, window_end_ns)`` in sim time. ``window_end_ns``
      equals the target event's ``log_time_sim_ns``.
    - ``schema_version``: defaults to ``TRACE_SCHEMA_VERSION``.

    State changes specifically: a ``/state/nav`` message counts as a
    state change when its ``(flight_mode, mission_mode)`` tuple differs
    from the immediately-preceding ``/state/nav`` message. Predecessor
    tracking spans the entire pre-event timeline (not just the window),
    so a state change at the edge of the window is detected even if the
    predecessor was just outside.
    """

    event_id: int
    event_type: str
    preceding_events: tuple[TracedMessage, ...]
    preceding_sensor_samples: tuple[TracedMessage, ...]
    preceding_actuator_commands: tuple[TracedMessage, ...]
    preceding_state_changes: tuple[TracedMessage, ...]
    window_start_ns: int
    window_end_ns: int
    schema_version: str = TRACE_SCHEMA_VERSION


class EventNotFoundError(LookupError):
    """Raised by ``build_behavior_trace`` when ``event_id`` is not present
    in the MCAP."""


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "BehaviorTrace",
    "EventNotFoundError",
    "TracedMessage",
]
