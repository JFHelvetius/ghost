"""`build_behavior_trace` + JSON serialization for `BehaviorTrace`.

Single forward pass over the replay reader. Buffers messages until the
target event is encountered; then filters the buffer to the
``[event_time - window_ns, event_time)`` half-open window and
categorizes by channel into four ordered tuples.

The pass is pure: no clock reads, no random, no I/O beyond the reader.
"Traceability is not explanation": this code reconstructs observed
sequences. It does NOT score, rank, weight, or infer.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import TYPE_CHECKING, Any

from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
)

from .models import (
    BehaviorTrace,
    EventNotFoundError,
    TracedMessage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from typing import TextIO

    from project_ghost.telemetry import MCAPReplayReader, ReplayMessage


TRACE_REPORT_SCHEMA_VERSION: str = "1"

_SENSOR_CHANNEL_PREFIX: str = "/sensors/"
_ACTUATOR_CHANNEL_PREFIX: str = "/actuators/"


# ---------------------------------------------------------------------------
# build_behavior_trace
# ---------------------------------------------------------------------------


def build_behavior_trace(  # noqa: PLR0912
    *,
    reader: MCAPReplayReader,
    event_id: int,
    window_ns: int,
) -> BehaviorTrace:
    """Reconstruct the observational pre-event sequence.

    Walks the replay reader once. Raises ``EventNotFoundError`` if no
    ``/events`` message with ``payload.sequence == event_id`` is
    encountered. ``window_ns`` must be ``>= 0`` (``0`` is legal and
    yields empty preceding lists).
    """
    if window_ns < 0:
        raise ValueError(f"window_ns must be >= 0; got {window_ns}")

    buffered: list[ReplayMessage] = []
    target_msg: ReplayMessage | None = None

    for msg in reader.iter_messages():
        if msg.channel == CHANNEL_EVENTS:
            seq = msg.payload_dict.get("sequence")
            if seq == event_id:
                target_msg = msg
                break
        buffered.append(msg)

    if target_msg is None:
        raise EventNotFoundError(f"event_id={event_id} not found in MCAP")

    event_time = target_msg.log_time_sim_ns
    window_start = event_time - window_ns

    # Filter to half-open window [window_start, event_time).
    in_window = [m for m in buffered if window_start <= m.log_time_sim_ns < event_time]

    preceding_events: list[TracedMessage] = []
    preceding_sensor_samples: list[TracedMessage] = []
    preceding_actuator_commands: list[TracedMessage] = []
    preceding_state_changes: list[TracedMessage] = []

    # State-change detection spans the entire pre-event timeline, so an
    # edge-of-window state change is detected even if its predecessor was
    # just outside.
    prev_state_modes: tuple[str, str] | None = None
    in_window_set = {id(m) for m in in_window}

    for m in buffered:
        if m.channel == CHANNEL_STATE_NAV:
            current_modes = _extract_modes(m.payload_dict)
            if current_modes != prev_state_modes:
                if id(m) in in_window_set:
                    preceding_state_changes.append(
                        TracedMessage(
                            channel=m.channel,
                            log_time_sim_ns=m.log_time_sim_ns,
                            schema_name=m.schema_name,
                            summary=_summarize_state(m.payload_dict),
                        )
                    )
                prev_state_modes = current_modes
            continue

        if id(m) not in in_window_set:
            continue

        if m.channel == CHANNEL_EVENTS:
            preceding_events.append(
                TracedMessage(
                    channel=m.channel,
                    log_time_sim_ns=m.log_time_sim_ns,
                    schema_name=m.schema_name,
                    summary=_summarize_event(m.payload_dict),
                )
            )
        elif m.channel.startswith(_SENSOR_CHANNEL_PREFIX):
            preceding_sensor_samples.append(
                TracedMessage(
                    channel=m.channel,
                    log_time_sim_ns=m.log_time_sim_ns,
                    schema_name=m.schema_name,
                    summary=_summarize_sensor(m.payload_dict),
                )
            )
        elif m.channel.startswith(_ACTUATOR_CHANNEL_PREFIX):
            preceding_actuator_commands.append(
                TracedMessage(
                    channel=m.channel,
                    log_time_sim_ns=m.log_time_sim_ns,
                    schema_name=m.schema_name,
                    summary=_summarize_actuator(m.payload_dict),
                )
            )
        # Other channels: silently ignored. Documented per ADR-0014.

    event_type = ""
    raw_type = target_msg.payload_dict.get("type", "")
    if isinstance(raw_type, str):
        event_type = raw_type

    return BehaviorTrace(
        event_id=event_id,
        event_type=event_type,
        preceding_events=tuple(preceding_events),
        preceding_sensor_samples=tuple(preceding_sensor_samples),
        preceding_actuator_commands=tuple(preceding_actuator_commands),
        preceding_state_changes=tuple(preceding_state_changes),
        window_start_ns=window_start,
        window_end_ns=event_time,
    )


# ---------------------------------------------------------------------------
# Report serialization
# ---------------------------------------------------------------------------


def generate_trace_report(
    trace: BehaviorTrace,
    output: Path | TextIO | None = None,
) -> None:
    """Write a trace as deterministic JSON.

    If ``output`` is a ``Path``, the JSON is written to that file
    (binary mode, UTF-8). If ``output`` is a writable text stream, the
    JSON is written to it. If ``output`` is ``None``, output goes to
    ``sys.stdout``.

    Same encoding posture as T5: ``sort_keys=True``, ``indent=2``,
    ``ensure_ascii=False``, trailing newline.
    """
    data = encode_trace_to_bytes(trace)
    if output is None:
        sys.stdout.write(data.decode("utf-8"))
        return
    if isinstance(output, (str, bytes)):
        raise TypeError("output must be a Path or a writable text stream; got str/bytes")
    if hasattr(output, "write_bytes"):
        # pathlib.Path
        output.write_bytes(data)
        return
    # Assume file-like text stream.
    output.write(data.decode("utf-8"))


def encode_trace_to_bytes(trace: BehaviorTrace) -> bytes:
    """Pure encoder; returns deterministic UTF-8 JSON bytes."""
    report = {
        "schema_version": TRACE_REPORT_SCHEMA_VERSION,
        "trace": dataclasses.asdict(trace),
    }
    serialized = json.dumps(
        report,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers internos — payload field extraction
# ---------------------------------------------------------------------------


def _extract_modes(payload: Mapping[str, Any]) -> tuple[str, str]:
    flight = payload.get("flight", {})
    mission = payload.get("mission", {})
    flight_mode = ""
    mission_mode = ""
    if isinstance(flight, dict):
        fm = flight.get("flight_mode", "")
        if isinstance(fm, str):
            flight_mode = fm
    if isinstance(mission, dict):
        mm = mission.get("mode", "")
        if isinstance(mm, str):
            mission_mode = mm
    return (flight_mode, mission_mode)


def _summarize_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "correlation_id": payload.get("correlation_id"),
        "sequence": payload.get("sequence", -1),
        "severity": payload.get("severity", 0),
        "source": payload.get("source", ""),
        "type": payload.get("type", ""),
    }


def _summarize_sensor(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "health": payload.get("health", -1),
        "sensor_id": payload.get("sensor_id", ""),
        "seq": payload.get("seq", -1),
    }


def _summarize_actuator(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "level": payload.get("level", -1),
        "schema_version": payload.get("schema_version", 1),
        "stamp_ns": payload.get("stamp_ns", 0),
    }


def _summarize_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    flight_mode, mission_mode = _extract_modes(payload)
    return {
        "flight_mode": flight_mode,
        "mission_mode": mission_mode,
    }


__all__ = [
    "TRACE_REPORT_SCHEMA_VERSION",
    "build_behavior_trace",
    "encode_trace_to_bytes",
    "generate_trace_report",
]
