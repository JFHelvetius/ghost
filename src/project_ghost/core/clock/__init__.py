"""`core.clock` — fuente única de tiempo y aleatoriedad determinista.

Implementación de `docs/specs/clock.md` (T3 del roadmap Fase 1) y ADR-0002
"Deterministic Simulation". Provee:

- **Protocols** (`SimClock`, `SystemClock`, `RandomSource`, `Handle`) para
  que backends arbitrarios (PyBullet, Gazebo, replay) puedan satisfacer la
  misma API sin acoplarse a esta implementación.
- **`SimClockImpl`** — reloj determinista con min-heap scheduler. Aritmética
  entera en ns; FIFO tie-break en `(at_ns, sequence)`; cancelación
  idempotente; excepciones aisladas a un `SchedulerErrorSink`.
- **`RandomSourceImpl`** — fuente jerárquica con derivación SHA-256.
  Etiquetas dinámicas (uuid, timestamp) **prohibidas** por convención
  (rompen replay).
- **`SchedulerErrorSink`** Protocol + `NullSchedulerErrorSink` /
  `RecordingSchedulerErrorSink` — patrón análogo a `ModeEventSink` en U1.b.
  El adapter al `EventBus` se añadirá cuando T5 aterrice.

Fuera de alcance T3:

- `SystemClock` impl para hardware (Protocol declarado, sin clase concreta).
- `ReplayClock` desde MCAP (depende de T4/T12).
- Adapter `SchedulerErrorSink -> EventBus` (depende de T5).
- Wall-clock-throttle mode (spec §10, futuro).
"""

from __future__ import annotations

from .error_sink import (
    NullSchedulerErrorSink,
    RecordingSchedulerErrorSink,
    SchedulerCallbackError,
    SchedulerErrorSink,
)
from .random_source import RandomSourceImpl
from .sim_clock import SimClockImpl
from .types import Handle, RandomSource, SimClock, SystemClock

CLOCK_PROTOCOL_VERSION: int = 1

__all__ = [
    "CLOCK_PROTOCOL_VERSION",
    "Handle",
    "NullSchedulerErrorSink",
    "RandomSource",
    "RandomSourceImpl",
    "RecordingSchedulerErrorSink",
    "SchedulerCallbackError",
    "SchedulerErrorSink",
    "SimClock",
    "SimClockImpl",
    "SystemClock",
]
