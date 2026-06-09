"""FusionResultSink implementations (ADR-0028)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import FusionResult


class NullFusionResultSink:
    """Descarta. Implementación trivial para callers que no necesitan
    persistencia."""

    def publish(self, result: FusionResult) -> None:
        del result


class RecordingFusionResultSink:
    """Guarda en memoria en orden de publicación. Para tests."""

    def __init__(self) -> None:
        self._records: list[FusionResult] = []

    def publish(self, result: FusionResult) -> None:
        self._records.append(result)

    @property
    def records(self) -> tuple[FusionResult, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records.clear()


__all__ = [
    "NullFusionResultSink",
    "RecordingFusionResultSink",
]
