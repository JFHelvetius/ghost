"""Tests de la mecánica del scheduler — orden total, FIFO, cancelación.

Estos tests ejercitan el min-heap y la lógica de tokens compartidos a través
de la API pública de `SimClockImpl`. No tocan estado interno.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_ghost.core.clock import SimClockImpl

if TYPE_CHECKING:
    from collections.abc import Callable

_MS_NS: int = 1_000_000


# ---------------------------------------------------------------------------
# Orden total y FIFO tie-break
# ---------------------------------------------------------------------------


def test_callbacks_fire_in_at_ns_order() -> None:
    clock = SimClockImpl(seed=0)
    out: list[str] = []
    # Programar en orden inverso para verificar que el heap ordena.
    clock.schedule(at_ns=30, cb=lambda: out.append("c"))
    clock.schedule(at_ns=10, cb=lambda: out.append("a"))
    clock.schedule(at_ns=20, cb=lambda: out.append("b"))
    clock.advance(100)
    assert out == ["a", "b", "c"]


def test_fifo_tiebreak_for_same_at_ns() -> None:
    """Callbacks con mismo `at_ns` se ejecutan en orden de inscripción."""
    clock = SimClockImpl(seed=0)
    out: list[str] = []
    clock.schedule(at_ns=100, cb=lambda: out.append("first"))
    clock.schedule(at_ns=100, cb=lambda: out.append("second"))
    clock.schedule(at_ns=100, cb=lambda: out.append("third"))
    clock.advance(200)
    assert out == ["first", "second", "third"]


def test_callback_scheduling_new_event_within_window_is_processed_same_advance() -> None:
    """Per spec §5: si un callback programa un evento cuyo at_ns <= target,
    se procesa dentro del mismo `advance()`."""
    clock = SimClockImpl(seed=0)
    out: list[str] = []

    def outer() -> None:
        out.append("outer")
        clock.schedule(at_ns=clock.now_ns() + 10, cb=lambda: out.append("inner"))

    clock.schedule(at_ns=50, cb=outer)
    clock.advance(100)
    assert out == ["outer", "inner"]
    assert clock.now_ns() == 100


def test_callback_scheduling_event_beyond_window_is_deferred() -> None:
    clock = SimClockImpl(seed=0)
    out: list[str] = []

    def outer() -> None:
        out.append("outer")
        clock.schedule(at_ns=200, cb=lambda: out.append("inner_late"))

    clock.schedule(at_ns=50, cb=outer)
    clock.advance(100)
    assert out == ["outer"]
    # Avanzar más para que el inner se dispare
    clock.advance(200)
    assert out == ["outer", "inner_late"]


# ---------------------------------------------------------------------------
# Cancelación
# ---------------------------------------------------------------------------


def test_cancel_before_fire_prevents_callback() -> None:
    clock = SimClockImpl(seed=0)
    out: list[int] = []
    h = clock.schedule(at_ns=100, cb=lambda: out.append(1))
    h.cancel()
    clock.advance(200)
    assert out == []


def test_handle_cancel_is_idempotent() -> None:
    clock = SimClockImpl(seed=0)
    h = clock.schedule(at_ns=100, cb=lambda: None)
    h.cancel()
    h.cancel()  # segundo cancel no debe lanzar
    h.cancel()
    clock.advance(200)  # tampoco rompe el scheduler


def test_cancel_periodic_stops_all_future_firings() -> None:
    """Token compartido: cancelar al primer dispatch detiene rebrotes."""
    clock = SimClockImpl(seed=0)
    counter: list[int] = [0]
    h = clock.schedule_periodic(period_ns=10, cb=lambda: counter.__setitem__(0, counter[0] + 1))
    clock.advance(35)
    assert counter[0] == 4  # firings en t = 0, 10, 20, 30
    h.cancel()
    clock.advance(1000)
    assert counter[0] == 4  # ningún firing posterior


def test_cancel_one_of_many_callbacks_does_not_affect_others() -> None:
    clock = SimClockImpl(seed=0)
    a: list[int] = []
    b: list[int] = []
    c: list[int] = []
    clock.schedule(at_ns=100, cb=lambda: a.append(1))
    hb = clock.schedule(at_ns=100, cb=lambda: b.append(1))
    clock.schedule(at_ns=100, cb=lambda: c.append(1))
    hb.cancel()
    clock.advance(200)
    assert a == [1]
    assert b == []
    assert c == [1]


# ---------------------------------------------------------------------------
# Total-order multi-publisher / multi-subscriber (analog del roadmap T5)
# ---------------------------------------------------------------------------


def test_total_order_3_producers_5_subscribers_like() -> None:
    """Variante para scheduler: tres callbacks coprimos, cinco observadores
    que graban cada firing. Todos los observadores ven la misma secuencia
    total porque el scheduler dispatcha en orden total `(at_ns, sequence)`."""
    clock = SimClockImpl(seed=0)
    observers: list[list[str]] = [[] for _ in range(5)]

    def make_cb(tag: str) -> Callable[[], None]:
        def _cb() -> None:
            for obs in observers:
                obs.append(tag)

        return _cb

    clock.schedule_periodic(period_ns=7 * _MS_NS, cb=make_cb("a"))
    clock.schedule_periodic(period_ns=13 * _MS_NS, cb=make_cb("b"))
    clock.schedule_periodic(period_ns=17 * _MS_NS, cb=make_cb("c"))
    clock.advance(100 * _MS_NS)

    # Todos los observadores ven la misma traza
    assert all(obs == observers[0] for obs in observers[1:])
    # Y la traza no está vacía
    assert len(observers[0]) > 0
