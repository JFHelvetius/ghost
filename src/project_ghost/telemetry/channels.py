"""Channel name constants for the telemetry layer.

Names are part of the file format: once an `.mcap` file is written, the
channel strings inside are part of the contract any replay tool must
understand. We commit to them here and never typo them at call sites.

Adding a new channel here is fine. Renaming an existing one breaks
backward compatibility with previously captured runs — treat as an
ADR-grade change.
"""

from __future__ import annotations

TELEMETRY_PROTOCOL_VERSION: int = 1

CHANNEL_EVENTS: str = "/events"
"""Generic `Event` traffic from `events.EventBus`."""

CHANNEL_STATE_NAV: str = "/state/nav"
"""`VehicleState` snapshots from `state.aggregator` (and, eventually, from
real estimators)."""

_SENSOR_PREFIX: str = "/sensors/"


def channel_for_sensor(sensor_id: str) -> str:
    """Channel name for a given sensor id.

    Convention: ``/sensors/<sensor_id>``. We forbid ``/`` inside
    ``sensor_id`` so the prefix split is unambiguous in tooling.
    """
    if not sensor_id:
        raise ValueError("sensor_id no puede ser vacío")
    if "/" in sensor_id:
        raise ValueError(
            f"sensor_id no puede contener '/'; recibido {sensor_id!r}"
        )
    return _SENSOR_PREFIX + sensor_id


__all__ = [
    "CHANNEL_EVENTS",
    "CHANNEL_STATE_NAV",
    "TELEMETRY_PROTOCOL_VERSION",
    "channel_for_sensor",
]
