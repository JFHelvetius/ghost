"""MCAPReplayReader + ``decode_message``.

Opens an ``.mcap`` file produced by ``MCAPFileSink``, iterates messages
in stored order, and reconstructs typed dataclass instances when the
schema name is in the closed catalogue.

The catalogue is intentionally hardcoded: no plugin registry, no
dynamic discovery. Adding a new persistable type means one line in
``_DECODERS`` and one decoder function. Boring on purpose.

Reconstruction triggers ``__post_init__`` via the original dataclass
constructor, so replay is also an active correctness check: bad data on
disk produces a loud failure, not a silently invalid object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from project_ghost.core.uncertainty.mode_events import PerceptionModeChanged
from project_ghost.events.types import Event
from project_ghost.hal.messages.sensors import (
    AltimeterPayload,
    DepthImagePayload,
    GpsPayload,
    IMUPayload,
    RGBImagePayload,
    SensorHealth,
    SensorMeta,
    SensorSample,
)
from project_ghost.state.messages import VehicleState

from .serialization import from_json_dict

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from types import TracebackType


@dataclass(frozen=True)
class ReplayMessage:
    """One message read from an MCAP file in stored order."""

    channel: str
    schema_name: str
    log_time_sim_ns: int
    payload_dict: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Decoder catalogue — closed set, hardcoded by design.
# ---------------------------------------------------------------------------


def _decode_event(d: Mapping[str, Any]) -> Event:
    # `from_json_dict` returns `Any` because it dispatches dynamically;
    # we know the concrete type here.
    return cast("Event", from_json_dict(Event, d))


def _decode_vehicle_state(d: Mapping[str, Any]) -> VehicleState:
    return cast("VehicleState", from_json_dict(VehicleState, d))


def _decode_perception_mode_changed(
    d: Mapping[str, Any],
) -> PerceptionModeChanged:
    return cast("PerceptionModeChanged", from_json_dict(PerceptionModeChanged, d))


def make_sensor_sample_decoder(
    payload_cls: type[Any],
) -> Callable[[Mapping[str, Any]], SensorSample[Any]]:
    """Build a decoder for ``SensorSample[payload_cls]``.

    ``SensorSample`` is generic; ``get_type_hints`` cannot determine the
    concrete payload type from the wrapper alone, so the generic
    ``from_json_dict(SensorSample, ...)`` cannot be used. This factory
    closes over the known payload class and builds the wrapper explicitly.

    For MCAP-captured streams, prefer ``decode_message`` which already
    uses the right decoder per schema name. Use this function directly
    when you have raw JSON from elsewhere and know the payload type.
    """

    def _decode(d: Mapping[str, Any]) -> SensorSample[Any]:
        payload = from_json_dict(payload_cls, d["payload"])
        meta = from_json_dict(SensorMeta, d["meta"])
        return SensorSample(
            sensor_id=d["sensor_id"],
            seq=d["seq"],
            stamp_sensor_ns=d["stamp_sensor_ns"],
            stamp_sim_ns=d["stamp_sim_ns"],
            stamp_wall_ns=d["stamp_wall_ns"],
            health=SensorHealth(d["health"]),
            payload=payload,
            meta=meta,
            schema_version=d.get("schema_version", 1),
        )

    return _decode


def _build_decoder_table() -> dict[str, Callable[[Mapping[str, Any]], Any]]:
    table: dict[str, Callable[[Mapping[str, Any]], Any]] = {
        f"{Event.__module__}.{Event.__name__}": _decode_event,
        f"{VehicleState.__module__}.{VehicleState.__name__}": _decode_vehicle_state,
        (
            f"{PerceptionModeChanged.__module__}."
            f"{PerceptionModeChanged.__name__}"
        ): _decode_perception_mode_changed,
    }
    for payload_cls in (
        IMUPayload,
        RGBImagePayload,
        DepthImagePayload,
        GpsPayload,
        AltimeterPayload,
    ):
        name = (
            f"{SensorSample.__module__}.{SensorSample.__name__}."
            f"{payload_cls.__name__}"
        )
        table[name] = make_sensor_sample_decoder(payload_cls)
    return table


_DECODERS: dict[str, Callable[[Mapping[str, Any]], Any]] = _build_decoder_table()


def decode_message(msg: ReplayMessage) -> Any:
    """Decode a ``ReplayMessage`` to its original typed Python object.

    Raises ``KeyError`` if ``msg.schema_name`` is outside the closed
    catalogue. Re-runs the original dataclass's ``__post_init__`` so any
    invariant violation is reported at decode time.
    """
    decoder = _DECODERS.get(msg.schema_name)
    if decoder is None:
        raise KeyError(
            f"decode_message: schema desconocido {msg.schema_name!r}. "
            f"Conocidos: {sorted(_DECODERS)!r}"
        )
    return decoder(msg.payload_dict)


def supported_schemas() -> tuple[str, ...]:
    """Public view of the closed schema catalogue. Useful for tests and
    introspection tooling."""
    return tuple(sorted(_DECODERS))


# ---------------------------------------------------------------------------
# MCAPReplayReader
# ---------------------------------------------------------------------------


class MCAPReplayReader:
    """Read an ``.mcap`` file produced by ``MCAPFileSink``.

    Use as a context manager. ``iter_messages()`` yields ``ReplayMessage``
    in the file's stored order (chronological by ``log_time``).
    """

    def __init__(self, file_path: Path) -> None:
        try:
            from mcap.reader import make_reader  # noqa: PLC0415, F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "MCAPReplayReader requires the `mcap` package. Install "
                "with `pip install 'project-ghost[telemetry]'`."
            ) from e
        self._file_path: Path = Path(file_path)
        self._stream: BinaryIO | None = None
        self._reader: Any = None

    @property
    def file_path(self) -> Path:
        return self._file_path

    def __enter__(self) -> MCAPReplayReader:
        from mcap.reader import make_reader  # noqa: PLC0415

        self._stream = self._file_path.open("rb")
        self._reader = make_reader(self._stream)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._stream is not None:
            self._stream.close()
        self._stream = None
        self._reader = None

    def iter_messages(self) -> Iterator[ReplayMessage]:
        if self._reader is None:
            raise RuntimeError(
                "MCAPReplayReader debe abrirse via context manager antes "
                "de iterar"
            )
        for schema, channel, message in self._reader.iter_messages():
            schema_name = schema.name if schema is not None else ""
            yield ReplayMessage(
                channel=channel.topic,
                schema_name=schema_name,
                log_time_sim_ns=int(message.log_time),
                payload_dict=json.loads(message.data.decode("utf-8")),
            )

    def message_count(self) -> int:
        if self._reader is None:
            raise RuntimeError("MCAPReplayReader debe abrirse")
        summary = self._reader.get_summary()
        if summary is None or summary.statistics is None:
            return 0
        return int(summary.statistics.message_count)

    def time_range_sim_ns(self) -> tuple[int, int] | None:
        """``(start, end)`` of log times, or ``None`` if the file is empty."""
        if self._reader is None:
            raise RuntimeError("MCAPReplayReader debe abrirse")
        summary = self._reader.get_summary()
        if summary is None or summary.statistics is None:
            return None
        stats = summary.statistics
        if stats.message_count == 0:
            return None
        return (int(stats.message_start_time), int(stats.message_end_time))


__all__ = [
    "MCAPReplayReader",
    "ReplayMessage",
    "decode_message",
    "make_sensor_sample_decoder",
    "supported_schemas",
]
