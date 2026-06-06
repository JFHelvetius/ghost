"""Integration test: end-to-end pipeline (criterio implícito del spec T5).

Capture (synthesized MCAP via T4) → analyze (T5 build_run_summary +
generate_run_report) → load → validate. Single workflow, single test.
"""

from __future__ import annotations

import json
from pathlib import Path

from project_ghost.analysis import build_run_summary, generate_run_report
from project_ghost.events import EventType
from project_ghost.hal.messages import SensorHealth
from project_ghost.state import FlightMode, MissionMode
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    MCAPFileSink,
    MCAPReplayReader,
    channel_for_sensor,
)

from .conftest import (
    make_event,
    make_imu_sample,
    make_vehicle_state,
    write_actuator_channel,
)


def test_end_to_end_capture_analyze_report(tmp_path: Path) -> None:
    """Synthesize an MCAP with all message types, derive the summary,
    serialize the report, and verify every field of the loaded JSON."""
    mcap = tmp_path / "integration.mcap"
    report_path = tmp_path / "integration.report.json"

    # --- Capture phase ---
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.ARMED))
        sink.publish(
            CHANNEL_STATE_NAV,
            100,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD, mission_mode=MissionMode.IDLE
            ),
        )
        for i in range(5):
            sink.publish(
                channel_for_sensor("imu0"),
                200 + i * 50,
                make_imu_sample(seq=i, stamp_sim_ns=200 + i * 50),
            )
        write_actuator_channel(sink, 500)
        write_actuator_channel(sink, 600)
        sink.publish(
            CHANNEL_STATE_NAV,
            700,
            make_vehicle_state(
                flight_mode=FlightMode.OFFBOARD,
                mission_mode=MissionMode.NAVIGATE,
            ),
        )
        sink.publish(CHANNEL_EVENTS, 800, make_event(type_=EventType.TAKEOFF))
        sink.publish(CHANNEL_EVENTS, 900, make_event(type_=EventType.LANDED))

    final_state = make_vehicle_state(
        sensor_health={
            "imu0": SensorHealth.OK,
            "cam_front": SensorHealth.DEGRADED,
        }
    )

    # --- Analyze phase ---
    with MCAPReplayReader(mcap) as reader:
        summary = build_run_summary(
            run_id="integration-run",
            reader=reader,
            final_state=final_state,
        )

    # --- Report phase ---
    generate_run_report(summary, report_path)

    # --- Validate phase ---
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    s = data["summary"]

    assert s["run_id"] == "integration-run"
    assert s["event_count"] == 3
    assert s["sensor_sample_count"] == 5
    assert s["actuator_command_count"] == 2
    assert s["state_transition_count"] == 2  # initial + mode change
    assert s["healthy_sensor_count"] == 1  # imu0 OK
    assert s["unhealthy_sensor_count"] == 1  # cam_front DEGRADED
    assert s["first_timestamp_ns"] == 0
    assert s["last_timestamp_ns"] == 900
    assert s["duration_ns"] == 900
    assert s["event_type_counts"] == {"armed": 1, "landed": 1, "takeoff": 1}
    assert s["sensor_type_counts"] == {"IMUPayload": 5}
    assert s["actuator_type_counts"] == {"DirectMotorCommand": 2}
    assert len(s["final_state_hash"]) == 64  # SHA-256 hex
