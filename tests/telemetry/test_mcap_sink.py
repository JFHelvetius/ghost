"""Tests de `telemetry.mcap_sink.MCAPFileSink`.

Cubre apertura/cierre, validación de inputs, registro de schemas y
canales, y la verificación **byte-level** de determinismo solicitada
por el review de T4.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.events import Event, EventSeverity, EventType
from project_ghost.hal.messages import IMUPayload, SensorHealth, SensorMeta, SensorSample
from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    MCAPFileSink,
    TelemetrySink,
    channel_for_sensor,
)


def _event(seq: int = 0) -> Event:
    return Event(
        type=EventType.MISSION_START,
        severity=EventSeverity.INFO,
        source="test.source",
        stamp_sim_ns=seq * 100,
        stamp_wall_ns=seq * 100,
        sequence=seq,
        payload=MappingProxyType({"idx": seq}),
        correlation_id="run-1",
    )


def _imu_sample(seq: int = 0) -> SensorSample[IMUPayload]:
    return SensorSample[IMUPayload](
        sensor_id="imu0",
        seq=seq,
        stamp_sensor_ns=seq * 100,
        stamp_sim_ns=seq * 100,
        stamp_wall_ns=seq * 100,
        health=SensorHealth.OK,
        payload=IMUPayload(
            accel_mps2=np.array([0.1, 0.2, 9.81], dtype=np.float64),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        ),
        meta=SensorMeta(
            frame_id="body",
            calibration_id=None,
            extensions=MappingProxyType({}),
        ),
    )


def _write_run(path: Path, n: int = 5) -> None:
    with MCAPFileSink(path) as sink:
        for i in range(n):
            sink.publish(CHANNEL_EVENTS, i * 100, _event(seq=i))


# ---------------------------------------------------------------------------
# Construction + close
# ---------------------------------------------------------------------------


def test_mcap_sink_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "run.mcap"
    with MCAPFileSink(p) as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())
    assert p.exists()
    assert p.stat().st_size > 0


def test_mcap_sink_satisfies_telemetry_sink_protocol(tmp_path: Path) -> None:
    with MCAPFileSink(tmp_path / "x.mcap") as sink:
        assert isinstance(sink, TelemetrySink)


def test_mcap_sink_close_is_idempotent(tmp_path: Path) -> None:
    sink = MCAPFileSink(tmp_path / "x.mcap")
    sink.close()
    sink.close()


def test_mcap_sink_rejects_publish_after_close(tmp_path: Path) -> None:
    sink = MCAPFileSink(tmp_path / "x.mcap")
    sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        sink.publish(CHANNEL_EVENTS, 0, _event())


def test_mcap_sink_file_path_property(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    with MCAPFileSink(p) as sink:
        assert sink.file_path == p


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_mcap_sink_rejects_channel_without_leading_slash(tmp_path: Path) -> None:
    with MCAPFileSink(tmp_path / "x.mcap") as sink, pytest.raises(ValueError, match="'/'"):
        sink.publish("events", 0, _event())


def test_mcap_sink_rejects_negative_stamp(tmp_path: Path) -> None:
    with MCAPFileSink(tmp_path / "x.mcap") as sink:
        with pytest.raises(ValueError, match="stamp_sim_ns"):
            sink.publish(CHANNEL_EVENTS, -1, _event())


def test_mcap_sink_rejects_mixed_types_on_same_channel(tmp_path: Path) -> None:
    """Channel is typed; mixing schemas would break replay decoding."""
    with MCAPFileSink(tmp_path / "x.mcap") as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())
        with pytest.raises(ValueError, match="already registered"):
            sink.publish(CHANNEL_EVENTS, 100, _imu_sample())


# ---------------------------------------------------------------------------
# Multi-channel writes
# ---------------------------------------------------------------------------


def test_mcap_sink_multiple_channels_register_independently(tmp_path: Path) -> None:
    with MCAPFileSink(tmp_path / "x.mcap") as sink:
        sink.publish(CHANNEL_EVENTS, 0, _event())
        sink.publish(channel_for_sensor("imu0"), 0, _imu_sample())
        sink.publish(channel_for_sensor("imu0"), 100, _imu_sample(seq=1))
    # No assertion beyond "didn't raise" — verification of contents is
    # done by replay tests against this file.


# ---------------------------------------------------------------------------
# Byte-level determinism (T4 review requirement)
# ---------------------------------------------------------------------------


def test_mcap_file_is_byte_deterministic_for_same_input(tmp_path: Path) -> None:
    """encode(x); encode(x); encode(x) → identical files (T4 review).

    Holds within a fixed (CPython, mcap library) version pair. Documented
    limitation if cross-version compatibility is ever required.
    """
    p1 = tmp_path / "a.mcap"
    p2 = tmp_path / "b.mcap"
    p3 = tmp_path / "c.mcap"
    _write_run(p1)
    _write_run(p2)
    _write_run(p3)
    bytes1 = p1.read_bytes()
    bytes2 = p2.read_bytes()
    bytes3 = p3.read_bytes()
    assert bytes1 == bytes2 == bytes3


def test_mcap_file_byte_determinism_with_sensor_samples(tmp_path: Path) -> None:
    p1 = tmp_path / "a.mcap"
    p2 = tmp_path / "b.mcap"

    def write(path: Path) -> None:
        with MCAPFileSink(path) as sink:
            for i in range(3):
                sink.publish(channel_for_sensor("imu0"), i * 100, _imu_sample(seq=i))

    write(p1)
    write(p2)
    assert p1.read_bytes() == p2.read_bytes()
