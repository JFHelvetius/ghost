"""Tests de `telemetry.channels`."""

from __future__ import annotations

import pytest

from project_ghost.telemetry import (
    CHANNEL_EVENTS,
    CHANNEL_STATE_NAV,
    TELEMETRY_PROTOCOL_VERSION,
    channel_for_sensor,
)


def test_channel_constants_are_frozen_strings() -> None:
    assert CHANNEL_EVENTS == "/events"
    assert CHANNEL_STATE_NAV == "/state/nav"


def test_telemetry_protocol_version_is_one() -> None:
    assert TELEMETRY_PROTOCOL_VERSION == 1


def test_channel_for_sensor_anchor() -> None:
    assert channel_for_sensor("imu0") == "/sensors/imu0"
    assert channel_for_sensor("cam_front") == "/sensors/cam_front"


def test_channel_for_sensor_rejects_empty() -> None:
    with pytest.raises(ValueError, match="sensor_id"):
        channel_for_sensor("")


def test_channel_for_sensor_rejects_slashes() -> None:
    with pytest.raises(ValueError, match="'/'"):
        channel_for_sensor("imu/0")
    with pytest.raises(ValueError, match="'/'"):
        channel_for_sensor("/imu0")
