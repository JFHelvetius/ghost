"""ForwardPredictionSink implementations (ADR-0024).

- ``NullForwardPredictionSink``: descarta. Útil cuando el caller invoca
  ``forward_predict_and_publish`` pero no quiere persistir.
- ``RecordingForwardPredictionSink``: guarda en memoria, en orden de
  publicación. Para tests y verificación post-hoc.

Adapters de telemetría viven en ``telemetry.adapters`` (dirección de
dependencia: ``telemetry -> core.prediction``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import BeliefForwardPrediction


class NullForwardPredictionSink:
    """Descarta. Implementación trivial para callers que no necesitan
    persistencia."""

    def publish(self, prediction: BeliefForwardPrediction) -> None:
        del prediction  # explicit unused


class RecordingForwardPredictionSink:
    """Guarda en memoria en orden de publicación.

    ``records`` devuelve una tupla inmutable para que callers no muten
    el estado interno por accidente.
    """

    def __init__(self) -> None:
        self._records: list[BeliefForwardPrediction] = []

    def publish(self, prediction: BeliefForwardPrediction) -> None:
        self._records.append(prediction)

    @property
    def records(self) -> tuple[BeliefForwardPrediction, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        """Vacía los records. Útil entre fases de test."""
        self._records.clear()


__all__ = [
    "NullForwardPredictionSink",
    "RecordingForwardPredictionSink",
]
