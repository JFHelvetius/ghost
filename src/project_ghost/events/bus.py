"""`EventBus` síncrono in-process — T5.a del roadmap Fase 1.

Implementación mínima del bus descrito en `docs/specs/events.md` §4. Alcance:

- `publish(ev)` asigna `sequence` global monotónico (sobrescribe el campo
  `sequence` del evento que llega del publisher) y entrega sincrónicamente
  a todos los subscribers que matchean en orden de registro.
- `subscribe(types, cb, min_severity)` filtra por tupla de `EventType`.
- `subscribe_all(cb, min_severity)` recibe todo lo que pase el filtro de
  severity.
- `Subscription.unsubscribe()` idempotente; remueve el callback.
- Excepción en un subscriber NO rompe a los demás (aislamiento por
  defecto, igual que `ModeEventSink` en U1.b). Si se proveyó un
  `SubscriberErrorSink`, recibe el error; si no, se traga silenciosamente.

**Deferido a T5.b** (cuando T4 + máquina async existan):

- Dispatcher async en thread propio para severities < CRITICAL.
- `CRITICAL` con entrega sincrónica garantizada antes del siguiente
  `step()`.
- Detección de subscribers lentos > N ms -> `TELEMETRY_BACKPRESSURE`.
- Persistencia a MCAP canal `/events` (depende de T4).
- `EventReplay` desde MCAP (depende de T4/T12).
- Protección contra cadenas `CRITICAL -> CRITICAL`.

`PerceptionModeChanged` (U1.b) **no** se canaliza por este bus — vive en
canal `/perception/mode` con su propio `ModeEventSink`. Dirección de
dependencia: `events/` y `core.uncertainty.mode_events` son hermanos; no se
importan entre sí. `core.clock.SchedulerErrorSink` similarmente vive en su
propio canal hasta que un adapter T5.b traduzca a `Event(SCHEDULER_CALLBACK_FAILED)`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .types import Event, EventSeverity

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .types import EventType


# ---------------------------------------------------------------------------
# Sink opcional para errores de subscribers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubscriberError:
    """Excepción capturada al despachar a un subscriber.

    `event_sequence` es el sequence del evento que se estaba despachando
    (útil para correlacionar con el log de eventos).
    """

    subscriber_repr: str
    event_sequence: int
    exception: BaseException


@runtime_checkable
class SubscriberErrorSink(Protocol):
    """Sink opcional para errores de dispatch. Patrón análogo a
    `core.clock.SchedulerErrorSink` y `core.uncertainty.ModeEventSink`."""

    def report(self, error: SubscriberError) -> None: ...


class NullSubscriberErrorSink:
    """Sink no-op default. Errores se tragan silenciosamente."""

    def report(self, error: SubscriberError) -> None:  # noqa: ARG002
        return None


@dataclass
class RecordingSubscriberErrorSink:
    """Sink que acumula errores. Para tests."""

    errors: list[SubscriberError] = field(default_factory=list)

    def report(self, error: SubscriberError) -> None:
        self.errors.append(error)

    def clear(self) -> None:
        self.errors.clear()


# ---------------------------------------------------------------------------
# Subscription (handle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subscription:
    """Handle devuelto por `EventBus.subscribe` / `subscribe_all`.

    `unsubscribe()` es idempotente y nunca lanza. Análogo a
    `core.clock.Handle` pero específico de subscriptions del bus
    (semánticamente distinto de cancelación de schedules).
    """

    unsubscribe: Callable[[], None]


# ---------------------------------------------------------------------------
# Entrada interna de subscriber
# ---------------------------------------------------------------------------


@dataclass
class _SubscriberEntry:
    """Estado interno por subscriber registrado."""

    callback: Callable[[Event], None]
    min_severity: EventSeverity
    # `None` significa subscribe_all; tupla significa filtro explícito.
    types: tuple[EventType, ...] | None
    unsubscribed: bool = False


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """Bus de eventos sincrónico in-process (T5.a).

    Uso típico:

    .. code-block:: python

        bus = EventBus()

        def on_safety(ev: Event) -> None:
            log.warning("safety event: %s", ev.type)

        sub = bus.subscribe(
            (EventType.SAFETY_VIOLATION, EventType.COLLISION_WARNING),
            on_safety,
            min_severity=EventSeverity.WARN,
        )
        bus.publish(Event(
            type=EventType.SAFETY_VIOLATION,
            severity=EventSeverity.WARN,
            source="control.attitude",
            stamp_sim_ns=clock.now_ns(),
            stamp_wall_ns=time.monotonic_ns(),
            sequence=0,                # el bus lo asigna
            payload={"reason": "max_tilt"},
            correlation_id=None,
        ))

    En T5.a TODO es sincrónico: cuando `publish()` retorna, todos los
    subscribers ya fueron invocados (o no, si fallaron).
    """

    def __init__(self, error_sink: SubscriberErrorSink | None = None) -> None:
        self._subscribers: list[_SubscriberEntry] = []
        self._next_seq: int = 0
        self._error_sink: SubscriberErrorSink = (
            error_sink if error_sink is not None else NullSubscriberErrorSink()
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def publish(self, ev: Event) -> Event:
        """Publica `ev` al bus y devuelve la versión con `sequence` asignado.

        El bus sobrescribe el campo `sequence` del evento incoming con el
        siguiente entero monotónico global. Como `Event` es frozen, se
        construye un nuevo Event con `dataclasses.replace`. La versión
        retornada es la canónica (la que se persistirá a MCAP cuando T4
        aterrice y la que ven los subscribers).
        """
        seq = self._next_seq
        self._next_seq += 1
        sealed = dataclasses.replace(ev, sequence=seq)

        # Dispatch en orden de registro. Iteramos sobre una copia para que
        # un subscriber que se desuscriba (o registre otro) durante su
        # callback no rompa este loop. Las altas/bajas se ven en la
        # siguiente publish.
        for entry in list(self._subscribers):
            if entry.unsubscribed:
                continue
            if sealed.severity < entry.min_severity:
                continue
            if entry.types is not None and sealed.type not in entry.types:
                continue
            try:
                entry.callback(sealed)
            except Exception as exc:
                self._error_sink.report(
                    SubscriberError(
                        subscriber_repr=repr(entry.callback),
                        event_sequence=sealed.sequence,
                        exception=exc,
                    )
                )

        return sealed

    def subscribe(
        self,
        types: Iterable[EventType],
        cb: Callable[[Event], None],
        min_severity: EventSeverity = EventSeverity.DEBUG,
    ) -> Subscription:
        """Subscribe a una colección finita de `EventType`.

        `types` se materializa a `tuple` en el momento del registro; no se
        guarda referencia al iterable original (uncertainty.md §10 — no
        colecciones inestables).
        """
        types_tuple = tuple(types)
        if not types_tuple:
            raise ValueError(
                "subscribe: lista de types no puede ser vacía. "
                "Usar subscribe_all() para recibir todo."
            )
        entry = _SubscriberEntry(
            callback=cb,
            min_severity=min_severity,
            types=types_tuple,
        )
        return self._register(entry)

    def subscribe_all(
        self,
        cb: Callable[[Event], None],
        min_severity: EventSeverity = EventSeverity.DEBUG,
    ) -> Subscription:
        """Subscribe a TODO evento que pase el filtro de severity."""
        entry = _SubscriberEntry(
            callback=cb,
            min_severity=min_severity,
            types=None,
        )
        return self._register(entry)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _register(self, entry: _SubscriberEntry) -> Subscription:
        self._subscribers.append(entry)

        def _unsubscribe() -> None:
            entry.unsubscribed = True

        return Subscription(unsubscribe=_unsubscribe)


__all__ = [
    "EventBus",
    "NullSubscriberErrorSink",
    "RecordingSubscriberErrorSink",
    "SubscriberError",
    "SubscriberErrorSink",
    "Subscription",
]
