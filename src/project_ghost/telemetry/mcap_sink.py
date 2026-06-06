"""MCAPFileSink — synchronous on-disk capture.

The ``mcap`` package is imported lazily inside ``MCAPFileSink.__init__``
so that ``from project_ghost.telemetry import InMemorySink`` works in
environments without the ``[telemetry]`` extra installed. Construction
of ``MCAPFileSink`` raises a clear ``ImportError`` if ``mcap`` is missing.

**Schema model.** Each (channel, message-type) pair gets one MCAP
schema record (``name`` only — no formal schema document) and one MCAP
channel record (``message_encoding="json"``). Mixing types on a single
channel is rejected at publish time.

Schema name format:

- Generic dataclass: ``<module>.<ClassName>``.
- ``SensorSample`` (parametric): ``<module>.SensorSample.<PayloadName>``
  so each payload variant has its own decoder entry in ``replay.py``.

**Determinism.** For the same publish sequence, this sink produces
byte-identical files within a fixed combination of CPython version and
``mcap`` library version. Cross-library-version stability is not promised
(the ``mcap`` library may change record layouts between releases). The
*semantic* content — channels, schemas, message bytes, log times — is
stable regardless.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from .serialization import encode_to_bytes

if TYPE_CHECKING:
    from types import TracebackType


def _schema_name_for(message: Any) -> str:
    """Compute the MCAP schema name for a published message.

    Imported types referenced here are kept inside the function so that
    importing ``mcap_sink`` does not require pulling the entire HAL
    surface at module load.
    """
    from project_ghost.hal.messages.sensors import SensorSample  # noqa: PLC0415

    cls = type(message)
    qualified = f"{cls.__module__}.{cls.__name__}"
    if isinstance(message, SensorSample):
        payload_cls = type(message.payload)
        return f"{qualified}.{payload_cls.__name__}"
    return qualified


class MCAPFileSink:
    """On-disk MCAP sink.

    Usage::

        with MCAPFileSink(path) as sink:
            sink.publish("/events", t_ns, event)
        # file is closed + finalized at context exit

    Construction opens the file and writes the MCAP header. ``close()``
    finalizes the file index; not calling it produces a truncated file
    that may be missing the statistics record. Use the context manager.
    """

    LIBRARY_STRING: str = "project_ghost"

    def __init__(self, file_path: Path) -> None:
        try:
            from mcap.writer import Writer  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "MCAPFileSink requires the `mcap` package. Install with "
                "`pip install 'project-ghost[telemetry]'`."
            ) from e
        self._file_path: Path = Path(file_path)
        self._stream: BinaryIO | None = self._file_path.open("wb")
        self._writer: Any = Writer(self._stream)
        self._writer.start(profile="", library=self.LIBRARY_STRING)
        self._schemas: dict[str, int] = {}
        self._channels: dict[str, int] = {}
        self._channel_schema: dict[str, str] = {}

    @property
    def file_path(self) -> Path:
        return self._file_path

    def publish(
        self, channel: str, stamp_sim_ns: int, message: Any
    ) -> None:
        if self._writer is None:
            raise RuntimeError("MCAPFileSink is closed; cannot publish")
        if not channel.startswith("/"):
            raise ValueError(
                f"channel must start with '/'; got {channel!r}"
            )
        if stamp_sim_ns < 0:
            raise ValueError(
                f"stamp_sim_ns must be >= 0; got {stamp_sim_ns}"
            )
        schema_name = _schema_name_for(message)
        channel_id = self._ensure_channel(channel, schema_name)
        payload_bytes = encode_to_bytes(message)
        self._writer.add_message(
            channel_id=channel_id,
            log_time=stamp_sim_ns,
            publish_time=stamp_sim_ns,
            data=payload_bytes,
        )

    def close(self) -> None:
        if self._writer is not None:
            self._writer.finish()
            self._writer = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def __enter__(self) -> MCAPFileSink:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_schema(self, name: str) -> int:
        if name in self._schemas:
            return self._schemas[name]
        schema_id: int = self._writer.register_schema(
            name=name,
            encoding="",  # No formal schema document; payload is JSON.
            data=b"",
        )
        self._schemas[name] = schema_id
        return schema_id

    def _ensure_channel(self, channel: str, schema_name: str) -> int:
        if channel in self._channels:
            registered = self._channel_schema[channel]
            if registered != schema_name:
                raise ValueError(
                    f"channel {channel!r} already registered with schema "
                    f"{registered!r}; refusing to mix {schema_name!r}"
                )
            return self._channels[channel]
        schema_id = self._ensure_schema(schema_name)
        channel_id: int = self._writer.register_channel(
            topic=channel,
            message_encoding="json",
            schema_id=schema_id,
        )
        self._channels[channel] = channel_id
        self._channel_schema[channel] = schema_name
        return channel_id


__all__ = ["MCAPFileSink"]
