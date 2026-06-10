"""DecisionSink implementations (ADR-0021).

- ``NullDecisionSink``: descarta. Para tests y como default no-op.
- ``RecordingDecisionSink``: guarda en memoria. Para tests y
  verificación post-hoc. Valida que ``rationale.decision == decision``
  para detectar wiring incorrecto.

Adapters de telemetría viven en ``telemetry.adapters`` (dirección de
dependencia: ``telemetry -> core.decisions``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import Decision, DecisionRationale


class NullDecisionSink:
    """Descarta. Útil cuando el caller invoca ``decide_and_publish``
    pero no quiere persistir."""

    def publish(self, decision: Decision, rationale: DecisionRationale) -> None:
        del decision, rationale  # explicit unused


class RecordingDecisionSink:
    """Guarda en memoria para tests y verificación post-hoc.

    Valida que ``rationale.decision == decision`` en cada publish:
    detecta wiring incorrecto donde el caller pasa decision+rationale
    inconsistentes.

    ``records`` devuelve una tupla inmutable para que callers no muten
    el estado interno por accidente.
    """

    def __init__(self) -> None:
        self._records: list[tuple[Decision, DecisionRationale]] = []

    def publish(self, decision: Decision, rationale: DecisionRationale) -> None:
        if rationale.decision != decision:
            raise ValueError(
                "RecordingDecisionSink.publish: rationale.decision must equal decision"
            )
        self._records.append((decision, rationale))

    @property
    def records(self) -> tuple[tuple[Decision, DecisionRationale], ...]:
        return tuple(self._records)

    def clear(self) -> None:
        """Vacía los records guardados. Útil entre fases de test."""
        self._records.clear()


__all__ = [
    "NullDecisionSink",
    "RecordingDecisionSink",
]
