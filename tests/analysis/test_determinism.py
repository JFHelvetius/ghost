"""Tests de determinismo a nivel byte (criterios 6, 7, 8, 12, 13 del spec T5).

Verifica:

- Same input => identical output (byte level)
- State hash stable
- Histogram ordering stable
- Different state => different hash
"""

from __future__ import annotations

from pathlib import Path

from project_ghost.analysis import (
    build_run_summary,
    encode_report_to_bytes,
)
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


def _write_mixed_mcap(path: Path) -> None:
    """Reproducible MCAP with all message types."""
    with MCAPFileSink(path) as sink:
        sink.publish(CHANNEL_EVENTS, 0, make_event(type_=EventType.ARMED))
        sink.publish(
            CHANNEL_STATE_NAV, 100, make_vehicle_state(flight_mode=FlightMode.OFFBOARD)
        )
        sink.publish(channel_for_sensor("imu0"), 200, make_imu_sample(seq=0))
        sink.publish(channel_for_sensor("imu0"), 300, make_imu_sample(seq=1))
        write_actuator_channel(sink, 400)
        sink.publish(CHANNEL_EVENTS, 500, make_event(type_=EventType.TAKEOFF))
        sink.publish(
            CHANNEL_STATE_NAV, 600, make_vehicle_state(mission_mode=MissionMode.NAVIGATE)
        )


# ---------------------------------------------------------------------------
# Test 12: same input => identical output (full pipeline)
# ---------------------------------------------------------------------------


def test_same_inputs_produce_identical_summary(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)
    state = make_vehicle_state(sensor_health={"imu0": SensorHealth.OK})

    with MCAPReplayReader(mcap) as r:
        a = build_run_summary(run_id="x", reader=r, final_state=state)
    with MCAPReplayReader(mcap) as r:
        b = build_run_summary(run_id="x", reader=r, final_state=state)

    assert a == b


def test_same_inputs_produce_byte_identical_report(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_mixed_mcap(mcap)
    state = make_vehicle_state(sensor_health={"imu0": SensorHealth.OK})

    def summarize() -> bytes:
        with MCAPReplayReader(mcap) as r:
            s = build_run_summary(run_id="x", reader=r, final_state=state)
        return encode_report_to_bytes(s)

    a = summarize()
    b = summarize()
    c = summarize()
    assert a == b == c


# ---------------------------------------------------------------------------
# Test 6: state hash stable
# ---------------------------------------------------------------------------


def test_final_state_hash_is_stable_for_same_state(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state = make_vehicle_state(
        sensor_health={
            "imu0": SensorHealth.OK,
            "cam_front": SensorHealth.DEGRADED,
        }
    )

    hashes: list[str] = []
    for _ in range(3):
        with MCAPReplayReader(mcap) as r:
            s = build_run_summary(run_id="x", reader=r, final_state=state)
        hashes.append(s.final_state_hash)
    assert len(set(hashes)) == 1


# ---------------------------------------------------------------------------
# Test 13: different state => different hash
# ---------------------------------------------------------------------------


def test_different_states_produce_different_hashes(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state_a = make_vehicle_state(flight_mode=FlightMode.OFFBOARD)
    state_b = make_vehicle_state(flight_mode=FlightMode.LAND)

    with MCAPReplayReader(mcap) as r:
        a = build_run_summary(run_id="x", reader=r, final_state=state_a)
    with MCAPReplayReader(mcap) as r:
        b = build_run_summary(run_id="x", reader=r, final_state=state_b)

    assert a.final_state_hash != b.final_state_hash


def test_sensor_health_change_changes_state_hash(tmp_path: Path) -> None:
    mcap = tmp_path / "empty.mcap"
    with MCAPFileSink(mcap):
        pass

    state_a = make_vehicle_state(sensor_health={"imu0": SensorHealth.OK})
    state_b = make_vehicle_state(sensor_health={"imu0": SensorHealth.FAULTY})

    with MCAPReplayReader(mcap) as r:
        a = build_run_summary(run_id="x", reader=r, final_state=state_a)
    with MCAPReplayReader(mcap) as r:
        b = build_run_summary(run_id="x", reader=r, final_state=state_b)

    assert a.final_state_hash != b.final_state_hash


# ---------------------------------------------------------------------------
# Test 7: histogram ordering stable
# ---------------------------------------------------------------------------


def test_histogram_ordering_independent_of_arrival_order(tmp_path: Path) -> None:
    """Two MCAPs with same events in different publish orders produce the
    same histogram dict (sorted keys)."""
    order_a = [
        EventType.ARMED,
        EventType.TAKEOFF,
        EventType.LANDED,
        EventType.TAKEOFF,
    ]
    order_b = [
        EventType.LANDED,
        EventType.TAKEOFF,
        EventType.TAKEOFF,
        EventType.ARMED,
    ]

    def build_mcap_and_summarize(order: list[EventType], filename: str) -> dict[str, int]:
        path = tmp_path / filename
        with MCAPFileSink(path) as sink:
            for i, t in enumerate(order):
                sink.publish(CHANNEL_EVENTS, i * 100, make_event(type_=t))
        state = make_vehicle_state()
        with MCAPReplayReader(path) as r:
            s = build_run_summary(run_id="x", reader=r, final_state=state)
        return s.event_type_counts

    hist_a = build_mcap_and_summarize(order_a, "a.mcap")
    hist_b = build_mcap_and_summarize(order_b, "b.mcap")

    assert hist_a == hist_b
    assert list(hist_a.keys()) == list(hist_b.keys())
    assert list(hist_a.keys()) == sorted(hist_a.keys())


def test_byte_identical_reports_for_same_events_in_different_order(
    tmp_path: Path,
) -> None:
    """Different MCAPs (different storage order) but with same final histogram
    + same final state may NOT be byte-identical at the MCAP level, but the
    DERIVED summary serialized output IS byte-identical because timestamps
    differ. So this test verifies that the summary bytes converge once we
    normalize for replay window — which we don't here, so we only check
    histogram bytes within the summary."""
    # Same publishing schedule (timestamps fixed), only event types reordered.
    order_a = [EventType.ARMED, EventType.TAKEOFF, EventType.LANDED]
    order_b = [EventType.LANDED, EventType.ARMED, EventType.TAKEOFF]

    def write(order: list[EventType], path: Path) -> None:
        with MCAPFileSink(path) as sink:
            for i, t in enumerate(order):
                sink.publish(CHANNEL_EVENTS, i * 100, make_event(type_=t))

    a_mcap = tmp_path / "a.mcap"
    b_mcap = tmp_path / "b.mcap"
    write(order_a, a_mcap)
    write(order_b, b_mcap)

    state = make_vehicle_state()
    with MCAPReplayReader(a_mcap) as r:
        sa = build_run_summary(run_id="x", reader=r, final_state=state)
    with MCAPReplayReader(b_mcap) as r:
        sb = build_run_summary(run_id="x", reader=r, final_state=state)

    # Histograms equal; replay window equal (same timestamps); state equal:
    # entire summary byte-identical.
    assert encode_report_to_bytes(sa) == encode_report_to_bytes(sb)
