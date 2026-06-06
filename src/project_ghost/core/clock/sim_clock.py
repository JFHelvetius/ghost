"""`SimClockImpl` — implementación determinista de `SimClock` con min-heap.

Cumple los contratos de `docs/specs/clock.md` §3 y §5:

- Aritmética entera en ns; sin acumulación en `float`.
- Orden total `(at_ns, sequence)` con FIFO tie-break.
- Excepciones en callbacks: capturadas y reportadas a `SchedulerErrorSink`,
  el scheduler continúa.
- Callbacks que programan eventos cuyo `at_ns <= target` se procesan dentro
  del mismo `advance()`.
- `Handle.cancel()` idempotente; en `schedule_periodic`, cancela TODAS las
  futuras ocurrencias mediante token compartido (no entrada individual del
  heap).

Fuera de alcance T3 (deferidos):

- `ReplayClock` (depende de T4/T12).
- Wall-clock-throttle mode (spec §10, futuro).
- Adapter `SchedulerErrorSink -> EventBus` (depende de T5).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from .error_sink import (
    NullSchedulerErrorSink,
    SchedulerCallbackError,
    SchedulerErrorSink,
)
from .random_source import RandomSourceImpl
from .types import Handle

if TYPE_CHECKING:
    from collections.abc import Callable


# Default step recomendado por la spec §8.1 para Fase 1 (1 ms).
_DEFAULT_STEP_NS: Final[int] = 1_000_000


@dataclass
class _CancelToken:
    """Token mutable compartido entre el handle y las entradas del heap.

    Cancelar un schedule periódico debe detener todas las futuras
    ocurrencias, no solo la próxima. Cuando el scheduler re-pushea una
    entrada periódica al heap, la nueva entrada referencia el mismo token,
    de modo que `token.cancelled = True` afecta a todas.
    """

    cancelled: bool = False


@dataclass(order=True)
class _HeapEntry:
    """Entrada del min-heap.

    Comparación por `(at_ns, sequence)` para garantizar FIFO en empates.
    Los campos no-comparables se marcan `compare=False` para que
    `dataclass(order=True)` ignore Callable y otros tipos sin orden natural.
    """

    at_ns: int
    sequence: int
    callback: Callable[[], None] = field(compare=False)
    token: _CancelToken = field(compare=False)
    periodic_period_ns: int | None = field(default=None, compare=False)


class SimClockImpl:
    """Reloj simulado determinista.

    Uso típico (spec §8.1):

    .. code-block:: python

        clock = SimClockImpl(seed=42)
        clock.schedule_periodic(5_000_000, controller.tick)   # 200 Hz
        clock.schedule_periodic(20_000_000, telemetry.flush)  # 50 Hz
        while clock.now_ns() < END_NS:
            clock.advance(1_000_000)  # 1 ms

    Sin reloj externo: todo tiempo entra por `advance`. ADR-0002.
    """

    def __init__(
        self,
        seed: int,
        step_ns: int = _DEFAULT_STEP_NS,
        error_sink: SchedulerErrorSink | None = None,
    ) -> None:
        if step_ns <= 0:
            raise ValueError(f"step_ns debe ser > 0; recibido {step_ns}")
        self._step_ns: Final[int] = step_ns
        self._now_ns: int = 0
        self._heap: list[_HeapEntry] = []
        self._next_seq: int = 0
        self._random_source = RandomSourceImpl(seed=seed, label="/")
        self._error_sink: SchedulerErrorSink = (
            error_sink if error_sink is not None else NullSchedulerErrorSink()
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def now_ns(self) -> int:
        return self._now_ns

    def step_ns(self) -> int:
        return self._step_ns

    def random_source(self) -> RandomSourceImpl:
        return self._random_source

    def advance(self, dt_ns: int) -> None:
        """Avanza el tiempo simulado en `dt_ns` y dispara callbacks vencidos.

        Callbacks que programan nuevos eventos cuyo `at_ns <= target` se
        procesan dentro del mismo `advance()`. Excepciones se capturan y
        reportan al `SchedulerErrorSink`.
        """
        if dt_ns < 0:
            raise ValueError(f"dt_ns debe ser >= 0; recibido {dt_ns}")
        target = self._now_ns + dt_ns
        while self._heap and self._heap[0].at_ns <= target:
            entry = heapq.heappop(self._heap)
            if entry.token.cancelled:
                continue
            self._now_ns = entry.at_ns
            try:
                entry.callback()
            except Exception as exc:
                self._error_sink.report(
                    SchedulerCallbackError(
                        callback_repr=repr(entry.callback),
                        at_ns=entry.at_ns,
                        exception=exc,
                    )
                )
            if (
                entry.periodic_period_ns is not None
                and not entry.token.cancelled
            ):
                next_entry = _HeapEntry(
                    at_ns=entry.at_ns + entry.periodic_period_ns,
                    sequence=self._next_seq,
                    callback=entry.callback,
                    token=entry.token,
                    periodic_period_ns=entry.periodic_period_ns,
                )
                self._next_seq += 1
                heapq.heappush(self._heap, next_entry)
        self._now_ns = target

    def schedule(self, at_ns: int, cb: Callable[[], None]) -> Handle:
        """Programa `cb` para dispararse en `at_ns` (una sola vez).

        Rechaza `at_ns < now_ns` con `ValueError` — más estricto que la
        spec, que es ambigua sobre past-scheduling. Razón: silenciar
        timestamps pasados esconde bugs de inicialización.
        """
        if at_ns < self._now_ns:
            raise ValueError(
                f"schedule: at_ns ({at_ns}) debe ser >= now_ns ({self._now_ns})"
            )
        token = _CancelToken()
        entry = _HeapEntry(
            at_ns=at_ns,
            sequence=self._next_seq,
            callback=cb,
            token=token,
        )
        self._next_seq += 1
        heapq.heappush(self._heap, entry)

        def _cancel() -> None:
            token.cancelled = True

        return Handle(cancel=_cancel)

    def schedule_periodic(
        self,
        period_ns: int,
        cb: Callable[[], None],
        phase_ns: int = 0,
    ) -> Handle:
        """Programa `cb` periódicamente.

        Dispara en `t = phase_ns + k*period_ns` para `k >= 0` mientras
        `t <= target` (acumulación entera, sin drift). Si `phase_ns < now_ns`
        en el momento del registro, se avanza `k` al siguiente múltiplo
        no-pasado.
        """
        if period_ns <= 0:
            raise ValueError(f"period_ns debe ser > 0; recibido {period_ns}")
        if phase_ns < 0:
            raise ValueError(f"phase_ns debe ser >= 0; recibido {phase_ns}")
        # Primer firing >= now_ns
        if phase_ns >= self._now_ns:
            first_at = phase_ns
        else:
            k = (self._now_ns - phase_ns + period_ns - 1) // period_ns
            first_at = phase_ns + k * period_ns
        token = _CancelToken()
        entry = _HeapEntry(
            at_ns=first_at,
            sequence=self._next_seq,
            callback=cb,
            token=token,
            periodic_period_ns=period_ns,
        )
        self._next_seq += 1
        heapq.heappush(self._heap, entry)

        def _cancel() -> None:
            token.cancelled = True

        return Handle(cancel=_cancel)


__all__ = ["SimClockImpl"]
