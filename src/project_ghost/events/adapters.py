"""Adapters que conectan dominios externos al `EventBus`.

T5.a deja `core.clock.SchedulerErrorSink` y `core.uncertainty.ModeEventSink`
con sinks dedicados por dominio. Este módulo provee el puente al bus para
los dominios cuyos eventos sí pertenecen al canal `/events` del catálogo
canónico de `events.md` §3.

Decisión arquitectónica explícita: **NO existe `ModeEventToEventBusAdapter`**.
`PerceptionModeChanged` (uncertainty.md §9) tiene su propio canal
`/perception/mode` con schema propio; no se traduce a `Event` porque el
catálogo `EventType` no incluye un tipo para cambio de modo perceptual y
añadirlo requeriría ADR (regla análoga a ADR-0010). En MCAP, cuando T4
aterrice, ambos canales se persisten en paralelo manteniendo sus schemas
canónicos.

`SchedulerErrorToEventBusAdapter`, en cambio, es legítimo: `events.md` §3
ya lista `SCHEDULER_CALLBACK_FAILED` como tipo canónico precisamente para
este propósito. La spec del clock §5 dice: "Si un callback lanza excepción,
se captura, se publica `Event(SCHEDULER_CALLBACK_FAILED)`". Este adapter
materializa esa cláusula.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import TYPE_CHECKING

from .types import Event, EventSeverity, EventType

if TYPE_CHECKING:
    from project_ghost.core.clock import SchedulerCallbackError

    from .bus import EventBus


class SchedulerErrorToEventBusAdapter:
    """Adapter que implementa `SchedulerErrorSink` y publica al `EventBus`.

    Uso:

    .. code-block:: python

        bus = EventBus()
        clock = SimClockImpl(seed=42, error_sink=SchedulerErrorToEventBusAdapter(bus))
        bus.subscribe((EventType.SCHEDULER_CALLBACK_FAILED,), on_callback_fail)

    El adapter satisface el Protocol `SchedulerErrorSink` estructuralmente
    (tiene `report(error: SchedulerCallbackError) -> None`), por lo que se
    puede pasar directamente al constructor de `SimClockImpl`.

    Convención de payload (JSON-serializable, per events.md §3):

    - ``callback_repr``: `repr` del callable que falló (proviene del error).
    - ``at_ns``: tiempo simulado en el que el callback debió dispararse.
    - ``exception_type``: nombre de la clase de la excepción.
    - ``exception_message``: ``str(exception)``.

    La excepción cruda **no** se incluye en el payload — no es
    JSON-serializable y mantenerla viva extiende el lifetime más allá del
    scope del scheduler.

    `stamp_sim_ns` se setea a `error.at_ns` (el momento simulado del fallo).
    `stamp_wall_ns` se toma con `time.monotonic_ns()` al momento del
    `report()` — wall time se permite porque solo es para diagnóstico
    cross-reference, no para orden total (events.md §3).
    """

    def __init__(
        self, bus: EventBus, source: str = "core.clock.scheduler"
    ) -> None:
        if not source:
            raise ValueError("source no puede ser vacío")
        self._bus = bus
        self._source = source

    def report(self, error: SchedulerCallbackError) -> None:
        payload = MappingProxyType(
            {
                "callback_repr": error.callback_repr,
                "at_ns": error.at_ns,
                "exception_type": type(error.exception).__name__,
                "exception_message": str(error.exception),
            }
        )
        self._bus.publish(
            Event(
                type=EventType.SCHEDULER_CALLBACK_FAILED,
                severity=EventSeverity.ERROR,
                source=self._source,
                stamp_sim_ns=error.at_ns,
                stamp_wall_ns=time.monotonic_ns(),
                sequence=0,
                payload=payload,
                correlation_id=None,
            )
        )


__all__ = ["SchedulerErrorToEventBusAdapter"]
