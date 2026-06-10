"""Tests del `ModeEventToTelemetryAdapter` — adapter U1.b -> telemetry.

Cubre tres niveles:

1. **Protocol structural**: el adapter satisface ``ModeEventSink`` a
   nivel runtime (isinstance) y se puede pasar al constructor de
   ``PerceptionModeDetector`` sin error.
2. **Forwarding**: cada ``PerceptionModeChanged`` se publica en el
   canal correcto con el ``stamp_sim_ns`` del evento como ``log_time``.
3. **Round-trip**: un evento persistido al MCAP via el adapter se
   reconstruye correctamente vía ``decode_message`` (catálogo del
   decoder en ``replay.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.core.uncertainty import (
    ModeEventSink,
    PerceptionMode,
    PerceptionModeChanged,
)
from project_ghost.telemetry import (
    CHANNEL_PERCEPTION_MODE,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    ModeEventToTelemetryAdapter,
    decode_message,
)


def _event(
    *,
    from_mode: PerceptionMode = PerceptionMode.NOMINAL,
    to_mode: PerceptionMode = PerceptionMode.MOTION_AGGRESSIVE,
    reason: str = "motion_aggressive_entry_criterion_met",
    stamp_sim_ns: int = 1_000,
    producer_ids: tuple[str, ...] = ("imu.0", "vo.front"),
) -> PerceptionModeChanged:
    return PerceptionModeChanged(
        from_mode=from_mode,
        to_mode=to_mode,
        reason=reason,
        producer_ids=producer_ids,
        stamp_sim_ns=stamp_sim_ns,
    )


# ---------------------------------------------------------------------------
# Protocol structural
# ---------------------------------------------------------------------------


def test_adapter_satisfies_mode_event_sink_protocol() -> None:
    adapter = ModeEventToTelemetryAdapter(InMemorySink())
    assert isinstance(adapter, ModeEventSink)


def test_adapter_default_channel_is_perception_mode() -> None:
    adapter = ModeEventToTelemetryAdapter(InMemorySink())
    assert adapter.channel == CHANNEL_PERCEPTION_MODE


def test_adapter_accepts_custom_channel() -> None:
    adapter = ModeEventToTelemetryAdapter(InMemorySink(), channel="/custom/mode")
    assert adapter.channel == "/custom/mode"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    with pytest.raises(ValueError, match="'/'"):
        ModeEventToTelemetryAdapter(InMemorySink(), channel="perception/mode")


# ---------------------------------------------------------------------------
# Forwarding to TelemetrySink
# ---------------------------------------------------------------------------


def test_adapter_forwards_event_to_underlying_sink() -> None:
    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink)
    ev = _event(stamp_sim_ns=1_000)

    adapter.publish(ev)

    assert len(sink.captured) == 1
    captured = sink.captured[0]
    assert captured.channel == CHANNEL_PERCEPTION_MODE
    assert captured.stamp_sim_ns == 1_000
    assert captured.message is ev


def test_adapter_preserves_event_identity_no_copy() -> None:
    """El adapter no debe hacer copia: el sink recibe el mismo objeto."""
    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink)
    ev = _event()
    adapter.publish(ev)
    assert sink.captured[0].message is ev


def test_adapter_uses_event_stamp_as_log_time() -> None:
    """ADR-0002: no clock reads. log_time viene del evento, no del reloj."""
    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink)

    for stamp in (0, 100, 12345, 10**9):
        adapter.publish(_event(stamp_sim_ns=stamp))

    timestamps = [m.stamp_sim_ns for m in sink.captured]
    assert timestamps == [0, 100, 12345, 10**9]


def test_adapter_multiple_publishes_preserve_order() -> None:
    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink)

    events = [_event(reason=f"reason_{i}", stamp_sim_ns=i * 100) for i in range(5)]
    for ev in events:
        adapter.publish(ev)

    assert [m.message.reason for m in sink.captured] == [f"reason_{i}" for i in range(5)]


def test_adapter_with_custom_channel_publishes_to_that_channel() -> None:
    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink, channel="/x/y")
    adapter.publish(_event())
    assert sink.captured[0].channel == "/x/y"


# ---------------------------------------------------------------------------
# Round-trip end-to-end: adapter -> MCAP -> read -> decode
# ---------------------------------------------------------------------------


def test_round_trip_through_mcap_via_adapter(tmp_path: Path) -> None:
    """End-to-end: adapter persiste evento al MCAP; lectura + decode
    reconstruye una instancia equivalente que pasa __post_init__."""
    p = tmp_path / "modes.mcap"
    original = _event(
        from_mode=PerceptionMode.NOMINAL,
        to_mode=PerceptionMode.MOTION_AGGRESSIVE,
        reason="motion_aggressive_entry_criterion_met",
        stamp_sim_ns=1_500,
        producer_ids=("imu.0", "vo.front"),
    )

    with MCAPFileSink(p) as mcap:
        adapter = ModeEventToTelemetryAdapter(mcap)
        adapter.publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.channel == CHANNEL_PERCEPTION_MODE
    assert msg.log_time_sim_ns == 1_500

    decoded = decode_message(msg)
    assert isinstance(decoded, PerceptionModeChanged)
    assert decoded == original


def test_round_trip_preserves_producer_ids_tuple(tmp_path: Path) -> None:
    """`producer_ids: tuple[str, ...]` debe sobrevivir el JSON round-trip
    como tuple, no como list (rule de uncertainty.md §10)."""
    p = tmp_path / "modes.mcap"
    original = _event(producer_ids=("a", "b", "c", "d"))

    with MCAPFileSink(p) as mcap:
        ModeEventToTelemetryAdapter(mcap).publish(original)

    with MCAPReplayReader(p) as reader:
        decoded = decode_message(next(iter(reader.iter_messages())))

    assert isinstance(decoded.producer_ids, tuple)
    assert decoded.producer_ids == ("a", "b", "c", "d")


def test_round_trip_preserves_perception_mode_enums(tmp_path: Path) -> None:
    """from_mode / to_mode son StrEnum; deben reconstruirse como enum,
    no como str crudo."""
    p = tmp_path / "modes.mcap"
    original = _event(
        from_mode=PerceptionMode.MOTION_AGGRESSIVE,
        to_mode=PerceptionMode.LOW_TEXTURE,
    )

    with MCAPFileSink(p) as mcap:
        ModeEventToTelemetryAdapter(mcap).publish(original)

    with MCAPReplayReader(p) as reader:
        decoded = decode_message(next(iter(reader.iter_messages())))

    assert decoded.from_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert decoded.to_mode == PerceptionMode.LOW_TEXTURE
    assert isinstance(decoded.from_mode, PerceptionMode)


def test_round_trip_triggers_post_init_validation_on_corrupt_data(
    tmp_path: Path,
) -> None:
    """Si el JSON del MCAP estuviera corrupto, el decoder debe fallar
    porque __post_init__ se re-ejecuta en la reconstrucción."""
    from project_ghost.telemetry import from_json_dict

    bad_dict = {
        "from_mode": "nominal",
        "to_mode": "motion_aggressive",
        "reason": "",  # __post_init__ rechaza reason vacío
        "producer_ids": ["imu.0"],
        "stamp_sim_ns": 0,
        "schema_version": 1,
    }
    with pytest.raises(ValueError, match="reason"):
        from_json_dict(PerceptionModeChanged, bad_dict)


# ---------------------------------------------------------------------------
# Integration: detector real -> adapter -> InMemorySink
# ---------------------------------------------------------------------------


def test_detector_emits_through_adapter_to_telemetry_sink() -> None:
    """Loop completo: detector U1.b -> adapter -> sink. Verifica que el
    detector acepta el adapter como ModeEventSink y que cuando emite
    transición la captura llega al sink."""
    from project_ghost.core.uncertainty import (
        DetectorConfig,
        PerceptionModeDetector,
    )

    config = DetectorConfig(
        nominal_hold_ns=100,
        nominal_k_consecutive=2,
        aggressive_window_ns=100,
        aggressive_k_consecutive=2,
        aggressive_recovery_timeout_ns=10_000,
    )

    sink = InMemorySink()
    adapter = ModeEventToTelemetryAdapter(sink)
    detector = PerceptionModeDetector(config=config, sink=adapter)

    # Fuerza una transición NOMINAL -> MOTION_AGGRESSIVE.
    step = 50
    for i in range(2):
        detector.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=(i + 1) * step,
            commanded_rate_rps_max=config.aggressive_rate_threshold_rps,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=("vo.front",),
        )
    detector.tick(2 * step + config.aggressive_window_ns)

    assert len(sink.captured) == 1
    captured = sink.captured[0]
    assert captured.channel == CHANNEL_PERCEPTION_MODE
    assert isinstance(captured.message, PerceptionModeChanged)
    assert captured.message.to_mode == PerceptionMode.MOTION_AGGRESSIVE


# ---------------------------------------------------------------------------
# Determinism — re-publicar el mismo evento produce el mismo MCAP bytes
# ---------------------------------------------------------------------------


def test_adapter_yields_byte_deterministic_mcap(tmp_path: Path) -> None:
    """Mismo evento publicado en dos MCAPs idénticos produce bytes
    idénticos (regla T4 + adapter es puro forwarding)."""

    def write(p: Path) -> None:
        with MCAPFileSink(p) as mcap:
            ModeEventToTelemetryAdapter(mcap).publish(
                _event(stamp_sim_ns=1_000, reason="det-check")
            )

    a = tmp_path / "a.mcap"
    b = tmp_path / "b.mcap"
    write(a)
    write(b)
    assert a.read_bytes() == b.read_bytes()
