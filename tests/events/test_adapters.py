"""Tests del `SchedulerErrorToEventBusAdapter` — adapter clock -> bus.

Cubre dos niveles:

1. **Unit:** el adapter recibe `SchedulerCallbackError` y publica el
   `Event(SCHEDULER_CALLBACK_FAILED)` correctamente formado.
2. **Integration:** un `SimClockImpl` con el adapter como `error_sink`,
   un callback que lanza, un subscriber al bus que escucha
   `SCHEDULER_CALLBACK_FAILED`. Verifica end-to-end que la cláusula de
   `clock.md` §5 ("se publica `Event(SCHEDULER_CALLBACK_FAILED)`") se
   materializa correctamente ahora que ambos sistemas existen.
"""

from __future__ import annotations

import pytest

from project_ghost.core.clock import (
    SchedulerCallbackError,
    SchedulerErrorSink,
    SimClockImpl,
)
from project_ghost.events import (
    Event,
    EventBus,
    EventSeverity,
    EventType,
    SchedulerErrorToEventBusAdapter,
)

# ---------------------------------------------------------------------------
# Unit — adapter aislado
# ---------------------------------------------------------------------------


def test_adapter_satisfies_scheduler_error_sink_protocol() -> None:
    bus = EventBus()
    adapter = SchedulerErrorToEventBusAdapter(bus)
    assert isinstance(adapter, SchedulerErrorSink)


def test_adapter_rejects_empty_source() -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="source"):
        SchedulerErrorToEventBusAdapter(bus, source="")


def test_adapter_translates_error_to_event_on_bus() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe((EventType.SCHEDULER_CALLBACK_FAILED,), received.append)

    adapter = SchedulerErrorToEventBusAdapter(bus)
    err = SchedulerCallbackError(
        callback_repr="<function tick at 0x123>",
        at_ns=42,
        exception=RuntimeError("boom"),
    )
    adapter.report(err)

    assert len(received) == 1


def test_adapter_event_has_correct_type_and_severity() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    SchedulerErrorToEventBusAdapter(bus).report(
        SchedulerCallbackError(callback_repr="x", at_ns=0, exception=RuntimeError("x"))
    )
    ev = received[0]
    assert ev.type == EventType.SCHEDULER_CALLBACK_FAILED
    assert ev.severity == EventSeverity.ERROR


def test_adapter_uses_at_ns_as_stamp_sim_ns() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    SchedulerErrorToEventBusAdapter(bus).report(
        SchedulerCallbackError(callback_repr="cb", at_ns=12345, exception=RuntimeError("x"))
    )
    assert received[0].stamp_sim_ns == 12345


def test_adapter_payload_carries_error_details_in_jsonable_form() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)

    class CustomError(ValueError):
        pass

    SchedulerErrorToEventBusAdapter(bus).report(
        SchedulerCallbackError(
            callback_repr="<function tick>",
            at_ns=999,
            exception=CustomError("detailed message"),
        )
    )
    payload = dict(received[0].payload)
    assert payload == {
        "callback_repr": "<function tick>",
        "at_ns": 999,
        "exception_type": "CustomError",
        "exception_message": "detailed message",
    }


def test_adapter_default_source_is_core_clock_scheduler() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    SchedulerErrorToEventBusAdapter(bus).report(
        SchedulerCallbackError(callback_repr="x", at_ns=0, exception=Exception("x"))
    )
    assert received[0].source == "core.clock.scheduler"


def test_adapter_custom_source_is_preserved() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    SchedulerErrorToEventBusAdapter(bus, source="custom.subsystem").report(
        SchedulerCallbackError(callback_repr="x", at_ns=0, exception=Exception("x"))
    )
    assert received[0].source == "custom.subsystem"


def test_adapter_events_have_monotonic_sequence_across_reports() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    adapter = SchedulerErrorToEventBusAdapter(bus)
    for i in range(5):
        adapter.report(
            SchedulerCallbackError(
                callback_repr=f"cb_{i}",
                at_ns=i * 10,
                exception=RuntimeError(f"err_{i}"),
            )
        )
    assert [ev.sequence for ev in received] == [0, 1, 2, 3, 4]


def test_adapter_event_correlation_id_is_none() -> None:
    """El adapter no sabe de cadenas de eventos; correlation_id es None."""
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)
    SchedulerErrorToEventBusAdapter(bus).report(
        SchedulerCallbackError(callback_repr="x", at_ns=0, exception=Exception("x"))
    )
    assert received[0].correlation_id is None


# ---------------------------------------------------------------------------
# Integration — SimClock + adapter + bus + subscriber
# ---------------------------------------------------------------------------


def test_simclock_callback_failure_reaches_event_bus_subscriber() -> None:
    """End-to-end: el callback falla en el scheduler, el adapter traduce
    a Event y el subscriber del bus lo recibe.

    Materializa la cláusula de clock.md §5 ahora que T3 + T5.a + adapter
    existen los tres.
    """
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(
        (EventType.SCHEDULER_CALLBACK_FAILED,),
        received.append,
        min_severity=EventSeverity.ERROR,
    )

    adapter = SchedulerErrorToEventBusAdapter(bus)
    clock = SimClockImpl(seed=0, error_sink=adapter)

    boom = RuntimeError("callback crashed")

    def failing_callback() -> None:
        raise boom

    clock.schedule(at_ns=100, cb=failing_callback)
    clock.advance(200)

    assert len(received) == 1
    ev = received[0]
    assert ev.type == EventType.SCHEDULER_CALLBACK_FAILED
    assert ev.severity == EventSeverity.ERROR
    assert ev.stamp_sim_ns == 100
    assert ev.payload["exception_type"] == "RuntimeError"
    assert ev.payload["exception_message"] == "callback crashed"


def test_simclock_periodic_failure_produces_one_event_per_failure() -> None:
    """Un callback periódico que falla cada vez genera un Event por firing.

    Confirma que el adapter no acumula ni deduplica — cada `report()`
    produce un publish independiente con sequence monotónico."""
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe_all(received.append)

    clock = SimClockImpl(seed=0, error_sink=SchedulerErrorToEventBusAdapter(bus))
    counter: list[int] = [0]

    def always_fails() -> None:
        counter[0] += 1
        raise RuntimeError(f"failure #{counter[0]}")

    clock.schedule_periodic(period_ns=10, cb=always_fails)
    clock.advance(35)  # firings en t = 0, 10, 20, 30 -> 4 fallos

    assert counter[0] == 4
    assert len(received) == 4
    # Mensajes únicos en cada Event preservan la identidad del fallo
    messages = [ev.payload["exception_message"] for ev in received]
    assert messages == [
        "failure #1",
        "failure #2",
        "failure #3",
        "failure #4",
    ]
    # Sequences monotónicos
    assert [ev.sequence for ev in received] == [0, 1, 2, 3]


def test_simclock_with_adapter_other_callbacks_keep_firing_after_failure() -> None:
    """El aislamiento del scheduler sigue intacto: otros callbacks no se
    ven afectados, y además los eventos de fallo viajan al bus."""
    bus = EventBus()
    events_seen: list[Event] = []
    bus.subscribe((EventType.SCHEDULER_CALLBACK_FAILED,), events_seen.append)

    clock = SimClockImpl(seed=0, error_sink=SchedulerErrorToEventBusAdapter(bus))
    healthy_fires: list[int] = []

    def healthy() -> None:
        healthy_fires.append(1)

    def bad() -> None:
        raise RuntimeError("bad")

    clock.schedule(at_ns=10, cb=bad)
    clock.schedule(at_ns=20, cb=healthy)
    clock.schedule(at_ns=30, cb=bad)
    clock.schedule(at_ns=40, cb=healthy)
    clock.advance(100)

    assert healthy_fires == [1, 1]
    assert len(events_seen) == 2
    assert {ev.stamp_sim_ns for ev in events_seen} == {10, 30}
