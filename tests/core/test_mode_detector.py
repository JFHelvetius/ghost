"""Tests del FSM `PerceptionModeDetector` (U1.b).

Cubre el subconjunto de transiciones del alcance U1.b:

- NOMINAL ↔ MOTION_AGGRESSIVE (entry, recovery, no-oscilación, requisito de
  productor degradado).
- MOTION_AGGRESSIVE → LOW_TEXTURE (timeout forzado de ADR-0010 §1).
- NOMINAL ↔ LOW_TEXTURE.

Estrategia de tiempos: la `_FAST` config usa ventanas en orden de cientos de
nanosegundos para mantener los tests legibles. Los thresholds matemáticos
(rate / accel / features) son los de defaults para que la validación de
threshold-at-boundary sea significativa.
"""

from __future__ import annotations

import pytest

from project_ghost.core.uncertainty import (
    DetectorConfig,
    PerceptionMode,
    PerceptionModeDetector,
    RecordingModeEventSink,
)

# ---------------------------------------------------------------------------
# Config compacta para tests — mantiene defaults de thresholds, encoge tiempos
# ---------------------------------------------------------------------------

_FAST = DetectorConfig(
    nominal_hold_ns=100,
    nominal_k_consecutive=2,
    aggressive_rate_threshold_rps=3.0,
    aggressive_accel_threshold_mps2=12.0,
    aggressive_window_ns=100,
    aggressive_k_consecutive=2,
    aggressive_recovery_timeout_ns=10_000,
    aggressive_recovery_threshold_factor=0.7,
    low_texture_min_features=10,
    low_texture_recovery_factor=1.5,
    low_texture_window_ns=100,
    low_texture_k_consecutive=2,
)


# ---------------------------------------------------------------------------
# Helpers — empujan la FSM por sus transiciones esperadas
# ---------------------------------------------------------------------------


def _new_detector(
    *,
    sink: RecordingModeEventSink | None = None,
    config: DetectorConfig | None = None,
    initial_mode: PerceptionMode = PerceptionMode.NOMINAL,
) -> tuple[PerceptionModeDetector, RecordingModeEventSink]:
    sink = sink if sink is not None else RecordingModeEventSink()
    det = PerceptionModeDetector(
        config=config or _FAST,
        sink=sink,
        initial_mode=initial_mode,
        initial_stamp_ns=0,
    )
    return det, sink


def _push_motion_entry(det: PerceptionModeDetector, *, t_start: int = 0) -> int:
    """Inyecta `aggressive_k_consecutive` observaciones de entrada espaciadas."""
    cfg = det.config
    step = cfg.aggressive_window_ns // cfg.aggressive_k_consecutive
    t = t_start
    for _ in range(cfg.aggressive_k_consecutive):
        t += step
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=cfg.aggressive_rate_threshold_rps,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=("vo.front",),
        )
    return t


def _enter_motion_aggressive(det: PerceptionModeDetector, *, t_start: int = 0) -> int:
    """Lleva el detector NOMINAL → MOTION_AGGRESSIVE. Devuelve el `now_ns` del tick."""
    cfg = det.config
    _push_motion_entry(det, t_start=t_start)
    step = cfg.aggressive_window_ns // cfg.aggressive_k_consecutive
    tick_ns = t_start + step + cfg.aggressive_window_ns
    det.tick(tick_ns)
    assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE, (
        f"helper falló: modo actual {det.current_mode}"
    )
    return tick_ns


def _push_motion_recovery(det: PerceptionModeDetector, *, t_start: int, window_ns: int) -> int:
    """Inyecta `nominal_k_consecutive` observaciones limpias y devuelve el último stamp."""
    cfg = det.config
    step = window_ns // cfg.nominal_k_consecutive
    t = t_start
    for _ in range(cfg.nominal_k_consecutive):
        t += step
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=0.0,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=(),
        )
    return t


# ---------------------------------------------------------------------------
# DetectorConfig — validación de constructor
# ---------------------------------------------------------------------------


def test_detector_config_defaults_are_valid() -> None:
    DetectorConfig()  # no lanza


def test_detector_config_rejects_nonpositive_nominal_hold() -> None:
    with pytest.raises(ValueError, match="nominal_hold_ns"):
        DetectorConfig(nominal_hold_ns=0)


def test_detector_config_rejects_k_less_than_one() -> None:
    with pytest.raises(ValueError, match="nominal"):
        DetectorConfig(nominal_k_consecutive=0)


def test_detector_config_rejects_nonpositive_aggressive_thresholds() -> None:
    with pytest.raises(ValueError, match="aggressive_"):
        DetectorConfig(aggressive_rate_threshold_rps=0.0)


def test_detector_config_rejects_recovery_factor_out_of_range() -> None:
    with pytest.raises(ValueError, match="recovery_threshold_factor"):
        DetectorConfig(aggressive_recovery_threshold_factor=1.0)
    with pytest.raises(ValueError, match="recovery_threshold_factor"):
        DetectorConfig(aggressive_recovery_threshold_factor=0.0)


def test_detector_config_rejects_low_texture_recovery_factor_le_one() -> None:
    """Recovery factor debe ser > 1 (histeresis anti-oscilación)."""
    with pytest.raises(ValueError, match="low_texture_recovery_factor"):
        DetectorConfig(low_texture_recovery_factor=1.0)


def test_detector_config_rejects_nonpositive_low_texture_min_features() -> None:
    with pytest.raises(ValueError, match="low_texture_min_features"):
        DetectorConfig(low_texture_min_features=0)


# ---------------------------------------------------------------------------
# PerceptionModeDetector — construcción
# ---------------------------------------------------------------------------


def test_detector_starts_in_nominal_by_default() -> None:
    det, _ = _new_detector()
    assert det.current_mode == PerceptionMode.NOMINAL


def test_detector_accepts_explicit_initial_mode() -> None:
    det, _ = _new_detector(initial_mode=PerceptionMode.LOW_TEXTURE)
    assert det.current_mode == PerceptionMode.LOW_TEXTURE


def test_detector_rejects_negative_initial_stamp() -> None:
    with pytest.raises(ValueError, match="initial_stamp_ns"):
        PerceptionModeDetector(initial_stamp_ns=-1)


def test_detector_uses_null_sink_when_unspecified() -> None:
    det = PerceptionModeDetector(config=_FAST)
    _enter_motion_aggressive(det)  # no debe lanzar aunque no haya sink
    assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE


def test_detector_config_property_returns_active_config() -> None:
    det, _ = _new_detector()
    assert det.config is _FAST


# ---------------------------------------------------------------------------
# Validación de argumentos en `record_*`
# ---------------------------------------------------------------------------


def test_record_motion_rejects_non_tuple_degraded() -> None:
    det, _ = _new_detector()
    with pytest.raises(TypeError, match="degraded_producers_in_window"):
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=1,
            commanded_rate_rps_max=0.0,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=["vo.front"],  # type: ignore[arg-type]
        )


def test_record_motion_rejects_negative_stamp() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=-1,
            commanded_rate_rps_max=0.0,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=(),
        )


def test_record_motion_rejects_empty_producer_id() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="producer_id"):
        det.record_motion_observation(
            producer_id="",
            stamp_sim_ns=1,
            commanded_rate_rps_max=0.0,
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=(),
        )


def test_record_feature_rejects_negative_feature_count() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="feature_count"):
        det.record_feature_observation(
            producer_id="vo.front",
            stamp_sim_ns=1,
            feature_count=-1,
        )


def test_record_feature_rejects_negative_stamp() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        det.record_feature_observation(
            producer_id="vo.front",
            stamp_sim_ns=-5,
            feature_count=20,
        )


def test_record_feature_rejects_empty_producer_id() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="producer_id"):
        det.record_feature_observation(
            producer_id="",
            stamp_sim_ns=1,
            feature_count=20,
        )


def test_tick_rejects_negative_now_ns() -> None:
    det, _ = _new_detector()
    with pytest.raises(ValueError, match="now_ns"):
        det.tick(-1)


# ---------------------------------------------------------------------------
# Tests obligatorios per spec U1.b
# ---------------------------------------------------------------------------


def test_perception_mode_event_published() -> None:
    """Al cruzar a MOTION_AGGRESSIVE, el sink recibe `PerceptionModeChanged`."""
    det, sink = _new_detector()
    tick_ns = _enter_motion_aggressive(det)

    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.from_mode == PerceptionMode.NOMINAL
    assert ev.to_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert ev.reason == "motion_aggressive_entry_criterion_met"
    assert isinstance(ev.producer_ids, tuple)
    # Debe contener al menos el productor de la observación + el degraded.
    assert "imu.0" in ev.producer_ids
    assert "vo.front" in ev.producer_ids
    assert ev.stamp_sim_ns == tick_ns
    assert ev.schema_version == 1


def test_motion_aggressive_entry_at_threshold() -> None:
    """Tasa **exactamente** al threshold con productor degradado dispara entry."""
    det, sink = _new_detector()
    cfg = det.config
    step = cfg.aggressive_window_ns // cfg.aggressive_k_consecutive

    t = 0
    for _ in range(cfg.aggressive_k_consecutive):
        t += step
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=cfg.aggressive_rate_threshold_rps,  # exactamente
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=("vo.front",),
        )
    det.tick(t + cfg.aggressive_window_ns)
    assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert len(sink.events) == 1


def test_motion_aggressive_no_entry_below_threshold() -> None:
    """Tasa y accel ambos bajo threshold no disparan entry."""
    det, sink = _new_detector()
    cfg = det.config
    step = cfg.aggressive_window_ns // cfg.aggressive_k_consecutive

    t = 0
    for _ in range(cfg.aggressive_k_consecutive + 2):
        t += step
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=cfg.aggressive_rate_threshold_rps - 0.5,
            measured_accel_mps2_excl_g=cfg.aggressive_accel_threshold_mps2 - 0.5,
            degraded_producers_in_window=("vo.front",),
        )
    det.tick(t + cfg.aggressive_window_ns)
    assert det.current_mode == PerceptionMode.NOMINAL
    assert sink.events == []


def test_motion_aggressive_requires_degraded_producer() -> None:
    """Aún con rate y accel muy sobre threshold, sin degraded no hay entry."""
    det, sink = _new_detector()
    cfg = det.config
    step = cfg.aggressive_window_ns // cfg.aggressive_k_consecutive

    t = 0
    for _ in range(cfg.aggressive_k_consecutive + 2):
        t += step
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=cfg.aggressive_rate_threshold_rps * 3,
            measured_accel_mps2_excl_g=cfg.aggressive_accel_threshold_mps2 * 3,
            degraded_producers_in_window=(),  # <-- vacío, no hay degraded
        )
    det.tick(t + cfg.aggressive_window_ns)
    assert det.current_mode == PerceptionMode.NOMINAL
    assert sink.events == []


def test_fsm_no_oscillation_under_alternating_signal() -> None:
    """Señal alternante envelope/no-envelope no acumula racha → no transición."""
    det, sink = _new_detector()
    cfg = det.config
    # Alternar observaciones en envelope y fuera; espaciado pequeño.
    for i in range(40):
        t = (i + 1) * 10
        in_envelope = i % 2 == 0
        det.record_motion_observation(
            producer_id="imu.0",
            stamp_sim_ns=t,
            commanded_rate_rps_max=(cfg.aggressive_rate_threshold_rps if in_envelope else 0.0),
            measured_accel_mps2_excl_g=0.0,
            degraded_producers_in_window=("vo.front",) if in_envelope else (),
        )
        det.tick(t)
    assert det.current_mode == PerceptionMode.NOMINAL
    assert sink.events == []


def test_motion_aggressive_recovery_requires_hold() -> None:
    """Recovery exige `nominal_hold_ns × 2` AND `nominal_k_consecutive` muestras."""
    det, sink = _new_detector()
    t = _enter_motion_aggressive(det)
    sink.clear()
    cfg = det.config

    # Una sola observación limpia (insuficiente: k_consecutive=2).
    t += 50
    det.record_motion_observation(
        producer_id="imu.0",
        stamp_sim_ns=t,
        commanded_rate_rps_max=0.0,
        measured_accel_mps2_excl_g=0.0,
        degraded_producers_in_window=(),
    )
    # Tick lejos en el tiempo (ventana sobrada), pero sin acumular K → no recovery.
    # No tan lejos como para gatillar timeout (10_000 ns).
    det.tick(t + cfg.nominal_hold_ns * 2 + 1)
    assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert sink.events == []


def test_motion_aggressive_recovery_completes_when_sustained() -> None:
    """Con K observaciones limpias y ventana×2 satisfecha, recovery → NOMINAL."""
    det, sink = _new_detector()
    t = _enter_motion_aggressive(det)
    sink.clear()
    cfg = det.config

    # K observaciones limpias.
    last_stamp = _push_motion_recovery(det, t_start=t, window_ns=cfg.nominal_hold_ns * 2)
    # Tick con ventana×2 cumplida desde el inicio de la racha.
    tick_ns = last_stamp + cfg.nominal_hold_ns * 2
    det.tick(tick_ns)

    assert det.current_mode == PerceptionMode.NOMINAL
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.from_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert ev.to_mode == PerceptionMode.NOMINAL
    assert ev.reason == "motion_aggressive_recovery_sustained"


def test_motion_aggressive_timeout_to_low_texture() -> None:
    """Sin recovery, transcurrido `aggressive_recovery_timeout_ns` → LOW_TEXTURE."""
    det, sink = _new_detector()
    t = _enter_motion_aggressive(det)
    sink.clear()
    cfg = det.config

    # No alimentamos observaciones de recovery; sólo dejamos pasar el tiempo.
    timeout_tick = t + cfg.aggressive_recovery_timeout_ns + 1
    det.tick(timeout_tick)

    assert det.current_mode == PerceptionMode.LOW_TEXTURE
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.from_mode == PerceptionMode.MOTION_AGGRESSIVE
    assert ev.to_mode == PerceptionMode.LOW_TEXTURE
    assert ev.reason == "motion_aggressive_recovery_timeout"
    assert ev.stamp_sim_ns == timeout_tick


def test_tick_without_observations_is_noop() -> None:
    """`tick` sin observaciones acumuladas mantiene modo y no emite eventos."""
    det, sink = _new_detector()
    det.tick(0)
    det.tick(50)
    det.tick(1_000_000_000)  # 1 segundo simulado
    assert det.current_mode == PerceptionMode.NOMINAL
    assert sink.events == []


# ---------------------------------------------------------------------------
# LOW_TEXTURE — entry y recovery (alcance U1.b)
# ---------------------------------------------------------------------------


def test_low_texture_entry_from_nominal() -> None:
    det, sink = _new_detector()
    cfg = det.config
    step = cfg.low_texture_window_ns // cfg.low_texture_k_consecutive

    t = 0
    for _ in range(cfg.low_texture_k_consecutive):
        t += step
        det.record_feature_observation(
            producer_id="vo.front",
            stamp_sim_ns=t,
            feature_count=cfg.low_texture_min_features - 1,
        )
    det.tick(t + cfg.low_texture_window_ns)
    assert det.current_mode == PerceptionMode.LOW_TEXTURE
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.reason == "low_texture_entry_criterion_met"
    assert ev.producer_ids == ("vo.front",)


def test_low_texture_recovery_to_nominal() -> None:
    det, sink = _new_detector(initial_mode=PerceptionMode.LOW_TEXTURE)
    cfg = det.config

    # Recovery requiere feature_count >= min_features × recovery_factor (≥15).
    recovery_count = int(cfg.low_texture_min_features * cfg.low_texture_recovery_factor)
    step = cfg.nominal_hold_ns // cfg.nominal_k_consecutive

    t = 0
    for _ in range(cfg.nominal_k_consecutive):
        t += step
        det.record_feature_observation(
            producer_id="vo.front",
            stamp_sim_ns=t,
            feature_count=recovery_count,
        )
    det.tick(t + cfg.nominal_hold_ns)
    assert det.current_mode == PerceptionMode.NOMINAL
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.reason == "low_texture_recovery_sustained"


def test_low_texture_no_recovery_below_factor() -> None:
    """feature_count entre min_features y min_features × factor no dispara recovery."""
    det, sink = _new_detector(initial_mode=PerceptionMode.LOW_TEXTURE)
    cfg = det.config

    # Justo por debajo del threshold de recuperación.
    borderline = cfg.low_texture_min_features  # < min × 1.5 = 15
    step = cfg.nominal_hold_ns // cfg.nominal_k_consecutive
    t = 0
    for _ in range(cfg.nominal_k_consecutive + 2):
        t += step
        det.record_feature_observation(
            producer_id="vo.front",
            stamp_sim_ns=t,
            feature_count=borderline,
        )
    det.tick(t + cfg.nominal_hold_ns * 2)
    assert det.current_mode == PerceptionMode.LOW_TEXTURE
    assert sink.events == []


# ---------------------------------------------------------------------------
# Modos fuera de alcance U1.b son no-op en tick
# ---------------------------------------------------------------------------


def test_tick_in_deferred_mode_is_noop() -> None:
    """Iniciar en un modo fuera de alcance (e.g. VIO_LOST) deja FSM congelada."""
    det, sink = _new_detector(initial_mode=PerceptionMode.VIO_LOST)
    det.tick(1_000)
    det.tick(1_000_000_000)
    assert det.current_mode == PerceptionMode.VIO_LOST
    assert sink.events == []


# ---------------------------------------------------------------------------
# Trackers se resetean entre transiciones (no se arrastra racha vieja)
# ---------------------------------------------------------------------------


def test_trackers_reset_on_transition() -> None:
    """Tras transitar a MOTION_AGGRESSIVE, las observaciones viejas no cuentan
    para una recuperación inmediata. Caller debe acumular fresh."""
    det, sink = _new_detector()
    tick_after_entry = _enter_motion_aggressive(det)
    sink.clear()

    # Una observación limpia inmediatamente después de la transición + tick:
    # NO debe recuperar (racha=1 < k=2).
    det.record_motion_observation(
        producer_id="imu.0",
        stamp_sim_ns=tick_after_entry + 10,
        commanded_rate_rps_max=0.0,
        measured_accel_mps2_excl_g=0.0,
        degraded_producers_in_window=(),
    )
    det.tick(tick_after_entry + _FAST.nominal_hold_ns * 2 + 20)
    assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE
