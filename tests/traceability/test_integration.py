"""Integration test: end-to-end pipeline para T6."""

from __future__ import annotations

import json
from pathlib import Path

from project_ghost.events import EventType
from project_ghost.state import FlightMode, MissionMode
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    MCAPFileSink,
    MCAPReplayReader,
    channel_for_sensor,
)
from project_ghost.traceability import (
    build_behavior_trace,
    generate_trace_report,
)

from .conftest import (
    make_event,
    make_imu_sample,
    make_vehicle_state,
    write_actuator_channel,
)


def test_end_to_end_capture_trace_report(tmp_path: Path) -> None:
    """Synthesize an MCAP with all four channel categories before a
    safety violation event. Build the trace. Serialize to JSON. Verify
    every category captured at least one entry."""
    mcap = tmp_path / "integration.mcap"
    output = tmp_path / "trace.json"

    # Capture
    with MCAPFileSink(mcap) as sink:
        sink.publish(
            CHANNEL_EVENTS, 100, make_event(sequence=0, type_=EventType.ARMED)
        )
        sink.publish(
            CHANNEL_STATE_NAV,
            200,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD,
                mission_mode=MissionMode.IDLE,
            ),
        )
        for i in range(3):
            sink.publish(
                channel_for_sensor("imu0"),
                300 + i * 50,
                make_imu_sample(seq=i),
            )
        sink.publish(
            CHANNEL_STATE_NAV,
            500,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD,
                mission_mode=MissionMode.NAVIGATE,
            ),
        )
        write_actuator_channel(sink, 600)
        write_actuator_channel(sink, 700)
        sink.publish(
            CHANNEL_EVENTS,
            800,
            make_event(sequence=42, type_=EventType.SAFETY_VIOLATION),
        )

    # Trace
    with MCAPReplayReader(mcap) as reader:
        trace = build_behavior_trace(
            reader=reader, event_id=42, window_ns=2 * 10**9
        )

    # Report
    generate_trace_report(trace, output)

    # Validate
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    t = data["trace"]
    assert t["event_id"] == 42
    assert t["event_type"] == "safety_violation"
    assert t["window_end_ns"] == 800

    assert len(t["preceding_events"]) == 1
    assert t["preceding_events"][0]["summary"]["type"] == "armed"

    assert len(t["preceding_sensor_samples"]) == 3
    assert [m["summary"]["seq"] for m in t["preceding_sensor_samples"]] == [0, 1, 2]

    assert len(t["preceding_actuator_commands"]) == 2

    # State changes: initial OFFBOARD/IDLE + IDLE→NAVIGATE
    assert len(t["preceding_state_changes"]) == 2
    assert t["preceding_state_changes"][0]["summary"]["mission_mode"] == "idle"
    assert t["preceding_state_changes"][1]["summary"]["mission_mode"] == "navigate"
