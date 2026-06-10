"""`TelemetrySink` Protocol and `InMemorySink`.

The Protocol is a single ``publish`` + idempotent ``close``. Concrete
sinks live in ``mcap_sink.py`` (real on-disk capture) and here
(``InMemorySink``, for tests).

There is intentionally no central ``TelemetryBus`` class. A publisher
that wants to send to multiple sinks holds multiple sink references. The
problem of multiplexing only exists once there is a second real sink,
and is best solved at that point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TelemetrySink(Protocol):
    """Abstract interface for telemetry persistence.

    Contract:

    - ``publish(channel, stamp_sim_ns, message)`` is synchronous: when it
      returns, the message has been accepted (buffered or in memory).
    - ``close()`` flushes and finalizes the sink; subsequent ``publish``
      calls must raise.
    - Channels must start with ``/`` (convention shared with bus topics).
    - ``stamp_sim_ns`` must be ``>= 0``.

    Failure modes use ``RuntimeError`` (closed sink) and ``ValueError``
    (malformed input). Sinks do not silently drop messages.
    """

    def publish(self, channel: str, stamp_sim_ns: int, message: Any) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class CapturedMessage:
    """One in-memory record. ``message`` is the original Python object
    (no serialization round-trip), so tests can assert dataclass equality
    directly."""

    channel: str
    stamp_sim_ns: int
    message: Any


@dataclass
class InMemorySink:
    """Test sink: records published messages in order."""

    captured: list[CapturedMessage] = field(default_factory=list)
    _closed: bool = field(default=False, init=False)

    def publish(self, channel: str, stamp_sim_ns: int, message: Any) -> None:
        if self._closed:
            raise RuntimeError("InMemorySink is closed; cannot publish")
        if not channel.startswith("/"):
            raise ValueError(f"channel must start with '/'; got {channel!r}")
        if stamp_sim_ns < 0:
            raise ValueError(f"stamp_sim_ns must be >= 0; got {stamp_sim_ns}")
        self.captured.append(
            CapturedMessage(
                channel=channel,
                stamp_sim_ns=stamp_sim_ns,
                message=message,
            )
        )

    def close(self) -> None:
        self._closed = True

    def clear(self) -> None:
        """Reset captured list. Useful between test phases."""
        self.captured.clear()

    def __enter__(self) -> InMemorySink:
        return self

    def __exit__(self, *exc: object) -> None:
        del exc
        self.close()


__all__ = [
    "CapturedMessage",
    "InMemorySink",
    "TelemetrySink",
]
