"""Sink de errores del scheduler — patrón análogo a `ModeEventSink` (U1.b).

`docs/specs/clock.md` §5 dice: "Si un callback lanza excepción, se captura,
se publica `Event(SCHEDULER_CALLBACK_FAILED)` y el scheduler continúa."

Como T5 (`events.EventBus`) aún no existe, el `SimClock` no publica eventos
directamente; en su lugar reporta a un `SchedulerErrorSink` inyectable. Un
adapter `SchedulerErrorSink -> EventBus` se añadirá cuando T5 aterrice. Esto
mantiene la dirección de dependencia limpia: `core.clock` no importa nada de
`events/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SchedulerCallbackError:
    """Excepción capturada de un callback programado.

    `callback_repr` es `repr(callback)` para diagnóstico; no se almacena la
    referencia al callable para no extender su vida útil más allá del scope
    del scheduler.
    """

    callback_repr: str
    at_ns: int
    exception: BaseException


@runtime_checkable
class SchedulerErrorSink(Protocol):
    """Sink que recibe errores de callbacks del scheduler.

    Contractualmente:

    - `report()` NO debe lanzar excepciones controlables del sink al
      scheduler (un sink defectuoso no debe colapsar el loop). No se
      enforza con `try/except` general en el scheduler porque tragar
      errores genéricos esconde bugs.
    - Implementaciones deben tratar el error reportado como inmutable.
    """

    def report(self, error: SchedulerCallbackError) -> None: ...


class NullSchedulerErrorSink:
    """Sink no-op. Default cuando `SimClock` se construye sin sink explícito."""

    def report(self, error: SchedulerCallbackError) -> None:  # noqa: ARG002
        return None


@dataclass
class RecordingSchedulerErrorSink:
    """Sink que acumula errores en orden. Para tests deterministas.

    No-frozen porque acumula estado mutable interno (la lista de errores).
    Los errores individuales son frozen.
    """

    errors: list[SchedulerCallbackError] = field(default_factory=list)

    def report(self, error: SchedulerCallbackError) -> None:
        self.errors.append(error)

    def clear(self) -> None:
        self.errors.clear()


__all__ = [
    "NullSchedulerErrorSink",
    "RecordingSchedulerErrorSink",
    "SchedulerCallbackError",
    "SchedulerErrorSink",
]
