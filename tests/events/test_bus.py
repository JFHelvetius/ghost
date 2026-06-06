"""Tests del `EventBus` síncrono (T5.a)."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest

from project_ghost.events import (
    Event,
    EventBus,
    EventSeverity,
    EventType,
    RecordingSubscriberErrorSink,
    Subscription,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _ev(
    *,
    seq: int = 0,
    type_: EventType = EventType.MISSION_START,
    severity: EventSeverity = EventSeverity.INFO,
    source: str = "test.source",
    stamp_sim_ns: int = 0,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> Event:
    return Event(
        type=type_,
        severity=severity,
        source=source,
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=stamp_sim_ns,
        sequence=seq,
        payload=MappingProxyType(payload or {}),
        correlation_id=correlation_id,
    )


def _recorder() -> tuple[Callable[[Event], None], list[Event]]:
    sink: list[Event] = []

    def _cb(ev: Event) -> None:
        sink.append(ev)

    return _cb, sink


# ---------------------------------------------------------------------------
# publish — asignación de sequence
# ---------------------------------------------------------------------------


def test_bus_publish_assigns_monotonic_sequence_starting_at_zero() -> None:
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe_all(cb)
    for i in range(5):
        bus.publish(_ev(stamp_sim_ns=i))
    seqs = [ev.sequence for ev in received]
    assert seqs == [0, 1, 2, 3, 4]


def test_bus_publish_overwrites_publisher_sequence() -> None:
    """Publisher pasa cualquier valor; el bus lo sobrescribe."""
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe_all(cb)
    # Publisher pasa sequence=0 (convención) — el bus asigna 0, 1, ...
    bus.publish(_ev(seq=0, stamp_sim_ns=10))
    bus.publish(_ev(seq=0, stamp_sim_ns=20))
    assert [ev.sequence for ev in received] == [0, 1]


def test_bus_publish_returns_sealed_event_with_assigned_sequence() -> None:
    """publish() devuelve el evento con sequence ya asignado."""
    bus = EventBus()
    sealed = bus.publish(_ev(stamp_sim_ns=42))
    assert sealed.sequence == 0
    assert sealed.stamp_sim_ns == 42  # otros campos intactos


def test_bus_publish_without_subscribers_still_increments_sequence() -> None:
    bus = EventBus()
    s1 = bus.publish(_ev())
    s2 = bus.publish(_ev())
    assert (s1.sequence, s2.sequence) == (0, 1)


# ---------------------------------------------------------------------------
# subscribe — orden de registro + filtros
# ---------------------------------------------------------------------------


def test_bus_dispatches_in_registration_order() -> None:
    bus = EventBus()
    order: list[str] = []
    bus.subscribe_all(lambda _ev: order.append("a"))
    bus.subscribe_all(lambda _ev: order.append("b"))
    bus.subscribe_all(lambda _ev: order.append("c"))
    bus.publish(_ev())
    assert order == ["a", "b", "c"]


def test_bus_subscribe_filters_by_type() -> None:
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe((EventType.MISSION_START, EventType.MISSION_END), cb)
    bus.publish(_ev(type_=EventType.MISSION_START))
    bus.publish(_ev(type_=EventType.WAYPOINT_REACHED))  # filtrado out
    bus.publish(_ev(type_=EventType.MISSION_END))
    assert [ev.type for ev in received] == [
        EventType.MISSION_START,
        EventType.MISSION_END,
    ]


def test_bus_subscribe_rejects_empty_types_list() -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="types"):
        bus.subscribe([], lambda _ev: None)


def test_bus_subscribe_accepts_any_iterable_of_types() -> None:
    """`subscribe` materializa el iterable a tuple — generadores OK."""
    bus = EventBus()
    cb, received = _recorder()
    types_iter = (t for t in (EventType.KILL,))
    bus.subscribe(types_iter, cb)
    bus.publish(_ev(type_=EventType.KILL, severity=EventSeverity.CRITICAL))
    assert len(received) == 1


# ---------------------------------------------------------------------------
# Filtros de severity
# ---------------------------------------------------------------------------


def test_bus_min_severity_filter_drops_below_threshold() -> None:
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe_all(cb, min_severity=EventSeverity.WARN)
    bus.publish(_ev(severity=EventSeverity.DEBUG))    # filtrado
    bus.publish(_ev(severity=EventSeverity.INFO))     # filtrado
    bus.publish(_ev(severity=EventSeverity.WARN))     # pasa
    bus.publish(_ev(severity=EventSeverity.ERROR))    # pasa
    bus.publish(_ev(severity=EventSeverity.CRITICAL)) # pasa
    assert [ev.severity for ev in received] == [
        EventSeverity.WARN,
        EventSeverity.ERROR,
        EventSeverity.CRITICAL,
    ]


def test_bus_subscribe_with_type_filter_also_respects_severity() -> None:
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe(
        (EventType.SAFETY_VIOLATION,),
        cb,
        min_severity=EventSeverity.ERROR,
    )
    bus.publish(_ev(type_=EventType.SAFETY_VIOLATION, severity=EventSeverity.WARN))
    bus.publish(_ev(type_=EventType.SAFETY_VIOLATION, severity=EventSeverity.ERROR))
    assert len(received) == 1
    assert received[0].severity == EventSeverity.ERROR


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


def test_bus_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    cb, received = _recorder()
    sub = bus.subscribe_all(cb)
    bus.publish(_ev())
    sub.unsubscribe()
    bus.publish(_ev())
    assert len(received) == 1


def test_bus_unsubscribe_is_idempotent() -> None:
    bus = EventBus()
    cb, received = _recorder()
    sub = bus.subscribe_all(cb)
    sub.unsubscribe()
    sub.unsubscribe()
    sub.unsubscribe()
    bus.publish(_ev())
    assert received == []


def test_bus_subscription_is_frozen() -> None:
    bus = EventBus()
    sub = bus.subscribe_all(lambda _ev: None)
    assert isinstance(sub, Subscription)
    # frozen dataclass: no asignación post-construcción
    from dataclasses import FrozenInstanceError  # noqa: PLC0415
    with pytest.raises(FrozenInstanceError):
        sub.unsubscribe = lambda: None  # type: ignore[misc]


def test_bus_unsubscribe_one_does_not_affect_others() -> None:
    bus = EventBus()
    cb1, r1 = _recorder()
    cb2, r2 = _recorder()
    s1 = bus.subscribe_all(cb1)
    bus.subscribe_all(cb2)
    s1.unsubscribe()
    bus.publish(_ev())
    assert r1 == []
    assert len(r2) == 1


# ---------------------------------------------------------------------------
# Orden total — 3 producers / 5 subscribers
# ---------------------------------------------------------------------------


def test_total_order_3_producers_5_subscribers() -> None:
    """En modo sync, 5 subscribers ven la misma secuencia total.

    T5.a no tiene producers concurrentes — el orden total es trivialmente
    consistente porque todo es secuencial. Este test documenta la
    expectativa del contrato; cuando T5.b agregue async para no-CRITICAL,
    este test debe seguir pasando (el orden por `(stamp_sim_ns, sequence)`
    persiste).
    """
    bus = EventBus()
    observers: list[list[int]] = [[] for _ in range(5)]

    def make_observer(target: list[int]) -> Callable[[Event], None]:
        def _record(ev: Event) -> None:
            target.append(ev.sequence)
        return _record

    for obs in observers:
        bus.subscribe_all(make_observer(obs))

    # Tres "producers" publicando en orden round-robin
    producer_tags = ["p1", "p2", "p3"] * 10
    for i, tag in enumerate(producer_tags):
        bus.publish(_ev(source=tag, stamp_sim_ns=i))

    # Cada observador ve la misma secuencia 0..29
    expected = list(range(30))
    for obs in observers:
        assert obs == expected


# ---------------------------------------------------------------------------
# CRITICAL en T5.a — semánticamente sync (no hay async todavía)
# ---------------------------------------------------------------------------


def test_critical_is_dispatched_synchronously() -> None:
    """En T5.a TODO es sync; este test documenta el contrato actual y se
    debe mantener cuando T5.b haga el resto async pero CRITICAL siga sync."""
    bus = EventBus()
    received_before_publish_returns: list[bool] = []

    def cb(ev: Event) -> None:
        received_before_publish_returns.append(ev.severity == EventSeverity.CRITICAL)

    bus.subscribe_all(cb)
    sealed = bus.publish(_ev(type_=EventType.KILL, severity=EventSeverity.CRITICAL))
    # Si publish() retornó, el subscriber YA fue llamado (sync).
    assert received_before_publish_returns == [True]
    assert sealed.severity == EventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Correlation id se preserva
# ---------------------------------------------------------------------------


def test_correlation_id_is_preserved_through_publish() -> None:
    bus = EventBus()
    cb, received = _recorder()
    bus.subscribe_all(cb)
    bus.publish(_ev(correlation_id="mission-xyz"))
    assert received[0].correlation_id == "mission-xyz"


# ---------------------------------------------------------------------------
# Aislamiento de excepciones de subscribers
# ---------------------------------------------------------------------------


def test_subscriber_exception_does_not_break_other_subscribers() -> None:
    bus = EventBus()
    cb_ok, received = _recorder()

    def cb_bad(_ev: Event) -> None:
        raise RuntimeError("boom")

    bus.subscribe_all(cb_bad)
    bus.subscribe_all(cb_ok)
    bus.publish(_ev())
    assert len(received) == 1


def test_subscriber_exception_is_reported_to_error_sink() -> None:
    sink = RecordingSubscriberErrorSink()
    bus = EventBus(error_sink=sink)

    boom = RuntimeError("dispatch error")

    def cb_bad(_ev: Event) -> None:
        raise boom

    bus.subscribe_all(cb_bad)
    bus.publish(_ev())
    assert len(sink.errors) == 1
    err = sink.errors[0]
    assert err.exception is boom
    assert err.event_sequence == 0
    assert "cb_bad" in err.subscriber_repr


def test_default_null_sink_swallows_exception_silently() -> None:
    """Sin error_sink explícito, los errores se tragan sin propagar."""
    bus = EventBus()
    bus.subscribe_all(lambda _ev: (_ for _ in ()).throw(RuntimeError("x")))
    bus.publish(_ev())  # no debe lanzar


def test_recording_sink_clear() -> None:
    sink = RecordingSubscriberErrorSink()
    bus = EventBus(error_sink=sink)
    bus.subscribe_all(lambda _ev: (_ for _ in ()).throw(RuntimeError("a")))
    bus.publish(_ev())
    assert len(sink.errors) == 1
    sink.clear()
    assert sink.errors == []


# ---------------------------------------------------------------------------
# Subscribe/unsubscribe durante un dispatch no rompen el loop
# ---------------------------------------------------------------------------


def test_subscriber_unsubscribing_during_dispatch_does_not_break_loop() -> None:
    bus = EventBus()
    after: list[int] = []
    later: list[int] = []

    def self_cancelling(_ev: Event) -> None:
        sub.unsubscribe()
        after.append(1)

    sub = bus.subscribe_all(self_cancelling)
    bus.subscribe_all(lambda _ev: later.append(1))

    bus.publish(_ev())
    assert after == [1]
    assert later == [1]
    # Segundo publish: self_cancelling ya no recibe
    bus.publish(_ev())
    assert after == [1]
    assert later == [1, 1]


def test_new_subscriber_added_during_dispatch_receives_from_next_publish() -> None:
    """Un subscriber que se registra mid-dispatch NO recibe el evento actual
    pero sí los siguientes."""
    bus = EventBus()
    seen_by_late: list[int] = []

    def adder(_ev: Event) -> None:
        bus.subscribe_all(lambda e: seen_by_late.append(e.sequence))

    bus.subscribe_all(adder)
    bus.publish(_ev())  # adder se ejecuta; late_sub se registra
    # late_sub no recibió el publish actual (registro post-snapshot)
    assert seen_by_late == []
    bus.publish(_ev())
    # late_sub ya está activo; pero adder vuelve a registrar otro late_sub
    # En este publish, el primer late_sub sí recibe.
    assert seen_by_late == [1]
