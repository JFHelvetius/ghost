"""Protocols del subsistema clock — `SimClock`, `SystemClock`, `RandomSource`.

Definidos como `typing.Protocol` para que backends de simulación (PyBullet,
Gazebo, replay) puedan proveer su propia implementación sin acoplarse a una
clase concreta. La implementación determinista para Fase 1 vive en
`sim_clock.SimClockImpl` (T3 del roadmap, ADR-0002).

Contratos vinculantes per `docs/specs/clock.md` §3:

- Unidad atómica entera en nanosegundos. `float` rechazado por la API de
  tiempo (verificación estructural por mypy strict; no hay enforcement
  runtime en el hot loop).
- Monotonía: `now_ns()` jamás retrocede.
- `advance()` solo en `SimClock`; en hardware el tiempo avanza solo.
- Determinismo: misma seed + mismas etiquetas de `RandomSource.child` +
  mismos `schedule_periodic` producen la misma traza bit-a-bit.
- `Handle.cancel()` es idempotente y nunca lanza.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np


@dataclass(frozen=True)
class Handle:
    """Handle devuelto por `SimClock.schedule` y `schedule_periodic`.

    `cancel()` es idempotente, nunca lanza y, en el caso de un schedule
    periódico, detiene **todas** las futuras ocurrencias (no solo la
    siguiente).
    """

    cancel: Callable[[], None]


@runtime_checkable
class RandomSource(Protocol):
    """Fuente determinista de aleatoriedad con jerarquía por etiquetas.

    Contratos:

    - `seed` y `label` son inmutables tras construcción.
    - `child(label)` deriva una sub-fuente mediante hash determinista del
      label; misma cadena de `.child(...)` desde la misma raíz produce las
      mismas secuencias.
    - **Etiquetas dinámicas (uuid, timestamp) están prohibidas por
      convención** — rompen replay determinista.
    - `numpy_rng()` devuelve el mismo `Generator` en llamadas sucesivas
      dentro de la misma instancia; para concerns independientes, crear
      `child()` separado.
    """

    seed: int
    label: str

    def child(self, label: str) -> RandomSource: ...
    def uniform(self, a: float, b: float) -> float: ...
    def normal(self, mu: float, sigma: float) -> float: ...
    def integers(self, low: int, high: int) -> int: ...
    def numpy_rng(self) -> np.random.Generator: ...


@runtime_checkable
class SimClock(Protocol):
    """Reloj simulado con step síncrono determinista."""

    def now_ns(self) -> int: ...
    def step_ns(self) -> int: ...
    def advance(self, dt_ns: int) -> None: ...
    def schedule(self, at_ns: int, cb: Callable[[], None]) -> Handle: ...
    def schedule_periodic(
        self,
        period_ns: int,
        cb: Callable[[], None],
        phase_ns: int = 0,
    ) -> Handle: ...
    def random_source(self) -> RandomSource: ...


@runtime_checkable
class SystemClock(Protocol):
    """Reloj de sistema para hardware o sim free-running.

    En hardware, `advance()` no aplica (el tiempo avanza solo). El scheduling
    se hace por threads con `time.sleep_ns` calibrado, no por time-wheel
    determinista. Implementación deferida a la fase de hardware; el Protocol
    queda declarado para que tipos cliente puedan ser polimórficos.
    """

    def now_ns(self) -> int: ...
    def random_source(self) -> RandomSource: ...


__all__ = ["Handle", "RandomSource", "SimClock", "SystemClock"]
