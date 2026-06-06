"""`events` — Event System (T5.a del roadmap Fase 1, ADR-0006).

Materialización mínima de `docs/specs/events.md`:

- `Event` (frozen dataclass) + `EventSeverity` (IntEnum) +
  `EventType` (StrEnum cerrado de 19 tipos canónicos).
- `EventBus` síncrono in-process con `publish` / `subscribe(types)` /
  `subscribe_all`, asignación monotónica de `sequence`, filtro por
  severity, aislamiento de excepciones por subscriber.
- `Subscription` (handle frozen con `unsubscribe()` idempotente).
- `SubscriberErrorSink` Protocol con `NullSubscriberErrorSink` /
  `RecordingSubscriberErrorSink`.

Fuera de alcance T5.a (deferido a T5.b cuando T4 + máquina async existan):

- Dispatcher async para no-CRITICAL.
- `CRITICAL` sync con garantía de entrega antes del siguiente step.
- Detección de subscribers lentos -> `TELEMETRY_BACKPRESSURE`.
- Persistencia a MCAP canal `/events`.
- `EventReplay` desde MCAP.

`PerceptionModeChanged` (U1.b, `core.uncertainty.mode_events`) y
`SchedulerCallbackError` (T3, `core.clock.error_sink`) NO se canalizan por
este bus; cada uno tiene su propio sink en su dominio. Adapters al bus
llegan cuando T5.b se materialice (`SCHEDULER_CALLBACK_FAILED` evento
publicado por un adapter clock -> events).
"""

from __future__ import annotations

from .bus import (
    EventBus,
    NullSubscriberErrorSink,
    RecordingSubscriberErrorSink,
    SubscriberError,
    SubscriberErrorSink,
    Subscription,
)
from .types import Event, EventSeverity, EventType

EVENTS_PROTOCOL_VERSION: int = 1

__all__ = [
    "EVENTS_PROTOCOL_VERSION",
    "Event",
    "EventBus",
    "EventSeverity",
    "EventType",
    "NullSubscriberErrorSink",
    "RecordingSubscriberErrorSink",
    "SubscriberError",
    "SubscriberErrorSink",
    "Subscription",
]
