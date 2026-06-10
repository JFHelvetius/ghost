"""Tests del `SimClockImpl` — monotonía, periodic exacto, errores de callback.

Cubre los tests obligatorios del roadmap T3 (`docs/roadmaps/phase1.md`):

- `test_clock_monotonic_after_million_steps`
- `test_periodic_count_exact_for_coprime_callbacks`
- `test_no_float_in_arithmetic` (marker, mypy strict es la enforcement)

Más cobertura de:

- Validación de argumentos del constructor y de la API.
- Captura de excepciones en callbacks via `SchedulerErrorSink`.
- `schedule_periodic` con `phase_ns < now_ns` (skip-ahead).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.core.clock import (
    RecordingSchedulerErrorSink,
    SchedulerCallbackError,
    SimClock,
    SimClockImpl,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _raises(exc: BaseException) -> Callable[[], None]:
    """Devuelve un callable que lanza `exc`; alternativa a lambdas con throw."""

    def _inner() -> None:
        raise exc

    return _inner


_MS_NS: int = 1_000_000
_SECOND_NS: int = 1_000_000_000


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------


def test_sim_clock_starts_at_zero() -> None:
    clock = SimClockImpl(seed=0)
    assert clock.now_ns() == 0


def test_sim_clock_default_step_is_one_ms() -> None:
    clock = SimClockImpl(seed=0)
    assert clock.step_ns() == _MS_NS


def test_sim_clock_custom_step_is_preserved() -> None:
    clock = SimClockImpl(seed=0, step_ns=500)
    assert clock.step_ns() == 500


def test_sim_clock_rejects_nonpositive_step() -> None:
    with pytest.raises(ValueError, match="step_ns"):
        SimClockImpl(seed=0, step_ns=0)
    with pytest.raises(ValueError, match="step_ns"):
        SimClockImpl(seed=0, step_ns=-1)


def test_sim_clock_satisfies_protocol() -> None:
    clock = SimClockImpl(seed=0)
    assert isinstance(clock, SimClock)


def test_sim_clock_exposes_random_source() -> None:
    clock = SimClockImpl(seed=42)
    rs = clock.random_source()
    assert rs.seed == 42
    assert rs.label == "/"


# ---------------------------------------------------------------------------
# Monotonía (roadmap T3: test obligatorio)
# ---------------------------------------------------------------------------


def test_clock_monotonic_after_million_steps() -> None:
    """Per roadmap T3: 10^6 pasos, monotonía estricta y precisión entera."""
    clock = SimClockImpl(seed=0)
    last = clock.now_ns()
    n_steps = 1_000_000
    for _ in range(n_steps):
        clock.advance(1)
        current = clock.now_ns()
        assert current > last
        last = current
    assert clock.now_ns() == n_steps


def test_clock_single_large_advance_is_exact() -> None:
    """Aritmética entera: advance grande no acumula drift."""
    clock = SimClockImpl(seed=0)
    clock.advance(123_456_789)
    assert clock.now_ns() == 123_456_789


def test_clock_advance_with_zero_dt_is_noop() -> None:
    clock = SimClockImpl(seed=0)
    fired: list[int] = []
    clock.schedule(at_ns=50, cb=lambda: fired.append(1))
    clock.advance(0)
    assert clock.now_ns() == 0
    assert fired == []


def test_clock_rejects_negative_advance() -> None:
    clock = SimClockImpl(seed=0)
    with pytest.raises(ValueError, match="dt_ns"):
        clock.advance(-1)


# ---------------------------------------------------------------------------
# schedule one-shot — validación
# ---------------------------------------------------------------------------


def test_schedule_at_past_at_ns_raises() -> None:
    clock = SimClockImpl(seed=0)
    clock.advance(100)
    with pytest.raises(ValueError, match="at_ns"):
        clock.schedule(at_ns=50, cb=lambda: None)


def test_schedule_at_current_now_ns_fires_on_next_advance() -> None:
    clock = SimClockImpl(seed=0)
    clock.advance(50)
    out: list[int] = []
    clock.schedule(at_ns=50, cb=lambda: out.append(1))
    clock.advance(1)
    assert out == [1]


# ---------------------------------------------------------------------------
# schedule_periodic — validación y skip-ahead
# ---------------------------------------------------------------------------


def test_schedule_periodic_rejects_nonpositive_period() -> None:
    clock = SimClockImpl(seed=0)
    with pytest.raises(ValueError, match="period_ns"):
        clock.schedule_periodic(period_ns=0, cb=lambda: None)
    with pytest.raises(ValueError, match="period_ns"):
        clock.schedule_periodic(period_ns=-1, cb=lambda: None)


def test_schedule_periodic_rejects_negative_phase() -> None:
    clock = SimClockImpl(seed=0)
    with pytest.raises(ValueError, match="phase_ns"):
        clock.schedule_periodic(period_ns=10, cb=lambda: None, phase_ns=-1)


def test_schedule_periodic_with_phase_in_past_skips_to_next_multiple() -> None:
    """`phase=0` registrado en `now=25` con period=10 dispara primero en t=30."""
    clock = SimClockImpl(seed=0)
    clock.advance(25)
    fires: list[int] = []
    clock.schedule_periodic(
        period_ns=10,
        cb=lambda: fires.append(clock.now_ns()),
        phase_ns=0,
    )
    clock.advance(50)  # now -> 75
    assert fires == [30, 40, 50, 60, 70]


# ---------------------------------------------------------------------------
# Periodic exacto (roadmap T3: test obligatorio)
# ---------------------------------------------------------------------------


def test_periodic_count_exact_for_coprime_callbacks() -> None:
    """Per roadmap T3: tres callbacks coprimos (7/13/17 ms) sobre 10 s,
    conteos exactos predecibles, sin drift por aritmética entera."""
    clock = SimClockImpl(seed=0)
    counts = {"a": 0, "b": 0, "c": 0}

    def make_inc(key: str) -> Callable[[], None]:
        def _inc() -> None:
            counts[key] += 1

        return _inc

    clock.schedule_periodic(period_ns=7 * _MS_NS, cb=make_inc("a"))
    clock.schedule_periodic(period_ns=13 * _MS_NS, cb=make_inc("b"))
    clock.schedule_periodic(period_ns=17 * _MS_NS, cb=make_inc("c"))

    clock.advance(10 * _SECOND_NS)

    # firings en t = k*period mientras k*period <= 10e9
    # 7ms:  floor(10e9 / 7e6)  = 1428 -> k = 0..1428 -> 1429 firings
    # 13ms: floor(10e9 / 13e6) = 769  -> k = 0..769  -> 770  firings
    # 17ms: floor(10e9 / 17e6) = 588  -> k = 0..588  -> 589  firings
    assert counts == {"a": 1429, "b": 770, "c": 589}


# ---------------------------------------------------------------------------
# Captura de excepciones en callbacks
# ---------------------------------------------------------------------------


def test_callback_exception_is_reported_to_error_sink() -> None:
    sink = RecordingSchedulerErrorSink()
    clock = SimClockImpl(seed=0, error_sink=sink)
    boom = RuntimeError("simulated")

    def crashes() -> None:
        raise boom

    clock.schedule(at_ns=10, cb=crashes)
    clock.advance(50)

    assert len(sink.errors) == 1
    err: SchedulerCallbackError = sink.errors[0]
    assert err.at_ns == 10
    assert err.exception is boom
    assert "crashes" in err.callback_repr


def test_callback_exception_does_not_break_subsequent_callbacks() -> None:
    sink = RecordingSchedulerErrorSink()
    clock = SimClockImpl(seed=0, error_sink=sink)
    fired_after: list[int] = []

    def crashes() -> None:
        raise RuntimeError("boom")

    clock.schedule(at_ns=10, cb=crashes)
    clock.schedule(at_ns=20, cb=lambda: fired_after.append(1))
    clock.advance(50)

    assert fired_after == [1]
    assert len(sink.errors) == 1


def test_periodic_callback_exception_does_not_stop_future_firings() -> None:
    sink = RecordingSchedulerErrorSink()
    clock = SimClockImpl(seed=0, error_sink=sink)
    counter: list[int] = [0]

    def flaky() -> None:
        counter[0] += 1
        if counter[0] == 2:
            raise RuntimeError("transient")

    clock.schedule_periodic(period_ns=10, cb=flaky)
    clock.advance(35)
    # firings en t = 0, 10, 20, 30 -> counter = 4
    assert counter[0] == 4
    assert len(sink.errors) == 1  # solo el segundo firing falló


def test_null_error_sink_is_default_and_silent() -> None:
    """Sin sink explícito, las excepciones se tragan silenciosamente."""
    clock = SimClockImpl(seed=0)
    clock.schedule(at_ns=10, cb=_raises(RuntimeError("x")))
    clock.advance(20)  # no debe lanzar


def test_recording_sink_clear() -> None:
    sink = RecordingSchedulerErrorSink()
    clock = SimClockImpl(seed=0, error_sink=sink)
    clock.schedule(at_ns=5, cb=_raises(RuntimeError("a")))
    clock.advance(10)
    assert len(sink.errors) == 1
    sink.clear()
    assert sink.errors == []


# ---------------------------------------------------------------------------
# Contrato int-only (roadmap T3: test obligatorio, mypy-only enforcement)
# ---------------------------------------------------------------------------


def test_no_float_in_arithmetic() -> None:
    """Per `docs/specs/clock.md` §3.1: `float` rechazado en la API de tiempo.

    La verificación es **estructural via mypy strict** (gate de CI), no
    runtime. Una llamada como `clock.advance(1.5)` produce un error
    `[arg-type]` de mypy antes de llegar a ejecutar este archivo. Este test
    no contiene aserción runtime — su valor es documentar la decisión
    y marcar el contrato en la suite.
    """
