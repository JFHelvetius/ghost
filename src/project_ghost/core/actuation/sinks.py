"""ActuationSink implementations (ADR-0023).

- ``NullActuationSink``: descarta. Útil cuando el caller invoca
  ``actuate_and_publish`` pero no quiere persistir.
- ``RecordingActuationSink``: guarda en memoria, en orden de
  publicación. Para tests y verificación post-hoc.

Adapters de telemetría viven en ``telemetry.adapters``
(dirección de dependencia: ``telemetry -> core.actuation``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ActuationDirective


class NullActuationSink:
    """Descarta. Implementación trivial para callers que no necesitan
    persistencia."""

    def publish(self, directive: ActuationDirective) -> None:
        del directive  # explicit unused


class RecordingActuationSink:
    """Guarda en memoria en orden de publicación.

    ``records`` devuelve una tupla inmutable para que callers no
    muten el estado interno por accidente.
    """

    def __init__(self) -> None:
        self._records: list[ActuationDirective] = []

    def publish(self, directive: ActuationDirective) -> None:
        self._records.append(directive)

    @property
    def records(self) -> tuple[ActuationDirective, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        """Vacía los records. Útil entre fases de test."""
        self._records.clear()


__all__ = [
    "NullActuationSink",
    "RecordingActuationSink",
]
