"""`build_run_summary` — single-pass derivation of a `RunSummary` from a
replay reader plus a final state snapshot.

The function is pure:

- No clock reads.
- No random.
- No filesystem I/O beyond what the reader does internally.
- No mutation of inputs.
- Iteration order is fixed by the reader (T4 MCAP storage order).

Determinism contract:

- Histograms are stored with alphabetically-sorted keys (see
  ``_sorted_dict``). The dict key order is preserved by Python 3.7+ and
  re-enforced at JSON encode time by ``json.dumps(sort_keys=True)``,
  giving two independent guarantees.
- ``state_transition_count`` increments on every change of the
  ``(flight_mode, mission_mode)`` tuple between consecutive
  ``/state/nav`` messages. The first ``/state/nav`` always counts as
  one transition.
- The final state SHA-256 uses the canonical
  ``telemetry.serialization.encode_to_bytes`` encoder, ensuring the hash
  matches what T4 would have written to disk for the same state.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import TYPE_CHECKING, Any

from project_ghost.hal.messages.sensors import SensorHealth
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    encode_to_bytes,
)

from .models import RunSummary

if TYPE_CHECKING:
    from collections.abc import Mapping

    from project_ghost.state.messages import VehicleState
    from project_ghost.telemetry import MCAPReplayReader


_SENSOR_CHANNEL_PREFIX: str = "/sensors/"
_ACTUATOR_CHANNEL_PREFIX: str = "/actuators/"


def build_run_summary(
    *,
    run_id: str,
    reader: MCAPReplayReader,
    final_state: VehicleState,
) -> RunSummary:
    """Walk the replay stream and produce a deterministic ``RunSummary``.

    The reader must already be opened (e.g., via context manager).
    ``final_state`` is the snapshot taken at run end; it is the single
    source of truth for ``healthy_sensor_count`` /
    ``unhealthy_sensor_count`` and contributes the
    ``final_state_hash``.
    """
    event_count = 0
    sensor_sample_count = 0
    actuator_command_count = 0
    state_transition_count = 0

    first_timestamp_ns: int | None = None
    last_timestamp_ns: int | None = None

    event_type_counts: Counter[str] = Counter()
    sensor_type_counts: Counter[str] = Counter()
    actuator_type_counts: Counter[str] = Counter()

    prev_modes: tuple[str, str] | None = None

    for msg in reader.iter_messages():
        # Timestamp tracking — first/last in iteration order.
        if first_timestamp_ns is None:
            first_timestamp_ns = msg.log_time_sim_ns
        last_timestamp_ns = msg.log_time_sim_ns

        if msg.channel == CHANNEL_EVENTS:
            event_count += 1
            event_type = msg.payload_dict.get("type", "")
            if isinstance(event_type, str):
                event_type_counts[event_type] += 1
        elif msg.channel == CHANNEL_STATE_NAV:
            current_modes = _extract_modes(msg.payload_dict)
            if current_modes != prev_modes:
                state_transition_count += 1
                prev_modes = current_modes
        elif msg.channel.startswith(_SENSOR_CHANNEL_PREFIX):
            sensor_sample_count += 1
            sensor_type_counts[_extract_last_segment(msg.schema_name)] += 1
        elif msg.channel.startswith(_ACTUATOR_CHANNEL_PREFIX):
            actuator_command_count += 1
            actuator_type_counts[_extract_last_segment(msg.schema_name)] += 1

    # Duration: defined only when at least one message was observed.
    if first_timestamp_ns is not None and last_timestamp_ns is not None:
        duration_ns: int | None = last_timestamp_ns - first_timestamp_ns
    else:
        duration_ns = None

    # Healthy / unhealthy sensor counts from the FINAL state's SensorHealthMap.
    healthy_sensor_count = sum(
        1 for h in final_state.sensors.by_id.values() if h == SensorHealth.OK
    )
    unhealthy_sensor_count = sum(
        1 for h in final_state.sensors.by_id.values() if h != SensorHealth.OK
    )

    # SHA-256 of the canonical state encoding. Same encoder T4 uses.
    final_state_hash = _compute_state_hash(final_state)

    return RunSummary(
        run_id=run_id,
        event_count=event_count,
        sensor_sample_count=sensor_sample_count,
        actuator_command_count=actuator_command_count,
        state_transition_count=state_transition_count,
        healthy_sensor_count=healthy_sensor_count,
        unhealthy_sensor_count=unhealthy_sensor_count,
        first_timestamp_ns=first_timestamp_ns,
        last_timestamp_ns=last_timestamp_ns,
        duration_ns=duration_ns,
        event_type_counts=_sorted_dict(event_type_counts),
        sensor_type_counts=_sorted_dict(sensor_type_counts),
        actuator_type_counts=_sorted_dict(actuator_type_counts),
        final_state_hash=final_state_hash,
        # T6 (ADR-0014): every event on /events is a valid target for
        # `traceability.build_behavior_trace`. The count is identical to
        # `event_count`; we expose it as a separate field so consumers
        # can distinguish "events observed" from "events traceable" if
        # the two definitions ever diverge.
        traceable_events_count=event_count,
    )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _extract_modes(payload_dict: Mapping[str, Any]) -> tuple[str, str]:
    """Extract ``(flight_mode, mission_mode)`` from a VehicleState payload.

    Missing fields collapse to empty strings — the comparison still works
    consistently across consecutive messages.
    """
    flight = payload_dict.get("flight", {})
    mission = payload_dict.get("mission", {})
    flight_mode = ""
    mission_mode = ""
    if isinstance(flight, dict):
        fm_value = flight.get("flight_mode", "")
        if isinstance(fm_value, str):
            flight_mode = fm_value
    if isinstance(mission, dict):
        mm_value = mission.get("mode", "")
        if isinstance(mm_value, str):
            mission_mode = mm_value
    return (flight_mode, mission_mode)


def _extract_last_segment(schema_name: str) -> str:
    """Last dot-separated segment of a schema name.

    For ``project_ghost.hal.messages.sensors.SensorSample.IMUPayload`` →
    ``IMUPayload``. For
    ``project_ghost.hal.messages.actuators.DirectMotorCommand`` →
    ``DirectMotorCommand``.
    """
    return schema_name.rsplit(".", 1)[-1]


def _sorted_dict(counter: Counter[str]) -> dict[str, int]:
    """Return a ``dict`` whose keys are sorted alphabetically.

    Python 3.7+ preserves insertion order in ``dict``; sorting here means
    the in-memory representation matches the JSON-encoded representation
    byte-for-byte (with ``sort_keys=True`` as belt and braces).
    """
    return {key: counter[key] for key in sorted(counter)}


def _compute_state_hash(state: VehicleState) -> str:
    """SHA-256 hex digest of ``encode_to_bytes(state)``.

    The canonical encoder is shared with T4 capture. A state that would
    have hashed to ``H`` if T4 had written it is guaranteed to hash to
    ``H`` here.
    """
    encoded = encode_to_bytes(state)
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["build_run_summary"]
