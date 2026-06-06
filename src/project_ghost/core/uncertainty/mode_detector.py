"""`PerceptionModeDetector` y su configuración (U1.b).

Implementación parcial — alcance U1.b — de la FSM descrita en
`docs/specs/perception.md` §3-§4 con la doble condición de transición
(`window_ns + k_consecutive`) de §4.1 y la recuperación con factor x2 de §4.2.

Transiciones implementadas:

- ``NOMINAL -> MOTION_AGGRESSIVE`` (ADR-0010 §1: rate/accel sobre threshold
  **y** >= 1 productor reportando degradación).
- ``MOTION_AGGRESSIVE -> NOMINAL`` (recuperación sostenida con
  ``nominal_hold_ns * 2`` y ``nominal_k_consecutive``).
- ``MOTION_AGGRESSIVE -> LOW_TEXTURE`` (timeout forzado per ADR-0010 §1 cuando
  la recuperación no llega en ``aggressive_recovery_timeout_ns``).
- ``NOMINAL <-> LOW_TEXTURE`` (entry con ``low_texture_window_ns +
  low_texture_k_consecutive``; recovery con doble condición nominal y
  ``feature_count >= min_features * recovery_factor``).

El resto del catálogo (``LOW_LIGHT``, ``IMU_SATURATION``, ``VIO_LOST``,
``MAP_AMBIGUOUS``, ``PERCEPTION_DEAD``) está marcado como ``# Deferred to
U1.c`` y NO se ejercita ni con stubs parciales: el detector simplemente no
emite ni recibe condiciones para esos modos.

Determinismo (ADR-0002): el detector NO consulta reloj. Todo tiempo entra
por ``stamp_sim_ns`` en las observaciones y ``now_ns`` en `tick`. Caller es
responsable de pasar timestamps en orden no-decreciente; el detector confía
en ese contrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .mode_events import (
    ModeEventSink,
    NullModeEventSink,
    PerceptionModeChanged,
)
from .types import PerceptionMode

_NS_PER_MS: Final[int] = 1_000_000


# ---------------------------------------------------------------------------
# Config (defaults de docs/specs/uncertainty.md §7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectorConfig:
    """Thresholds y ventanas del detector.

    Defaults tomados de ``docs/specs/uncertainty.md`` §7 — etiquetados como
    **valores conjeturados** (ver disclaimer del §5 / §7). Tiempos en
    nanosegundos para consistencia con `core.clock` (cuando llegue) y con
    ``stamp_sim_ns`` en mensajes del HAL.

    Solo los campos necesarios para U1.b están presentes. Resto del catálogo
    queda diferido a U1.c.
    """

    # Doble condición base (uncertainty.md §7 — nominal_*)
    nominal_hold_ns: int = 200 * _NS_PER_MS
    nominal_k_consecutive: int = 6

    # MOTION_AGGRESSIVE (uncertainty.md §7 + ADR-0010 §1)
    aggressive_rate_threshold_rps: float = 3.0
    aggressive_accel_threshold_mps2: float = 12.0
    aggressive_window_ns: int = 200 * _NS_PER_MS
    aggressive_k_consecutive: int = 4
    aggressive_recovery_timeout_ns: int = 2000 * _NS_PER_MS
    aggressive_recovery_threshold_factor: float = 0.7

    # LOW_TEXTURE (uncertainty.md §7 — low_texture_*)
    low_texture_min_features: int = 30
    low_texture_recovery_factor: float = 1.5
    low_texture_window_ns: int = 500 * _NS_PER_MS
    low_texture_k_consecutive: int = 8

    def __post_init__(self) -> None:
        if self.nominal_hold_ns <= 0 or self.nominal_k_consecutive < 1:
            raise ValueError("nominal_hold_ns y nominal_k_consecutive deben ser positivos")
        if self.aggressive_rate_threshold_rps <= 0 or self.aggressive_accel_threshold_mps2 <= 0:
            raise ValueError("aggressive_*_threshold deben ser > 0")
        if self.aggressive_window_ns <= 0 or self.aggressive_k_consecutive < 1:
            raise ValueError("aggressive_window_ns y aggressive_k_consecutive deben ser positivos")
        if self.aggressive_recovery_timeout_ns <= 0:
            raise ValueError("aggressive_recovery_timeout_ns debe ser > 0")
        if not 0.0 < self.aggressive_recovery_threshold_factor < 1.0:
            raise ValueError(
                f"aggressive_recovery_threshold_factor debe estar en (0, 1); "
                f"recibido {self.aggressive_recovery_threshold_factor}"
            )
        if self.low_texture_min_features < 1:
            raise ValueError("low_texture_min_features debe ser ≥ 1")
        if self.low_texture_recovery_factor <= 1.0:
            raise ValueError(
                "low_texture_recovery_factor debe ser > 1.0 (histeresis vs oscilación); "
                f"recibido {self.low_texture_recovery_factor}"
            )
        if self.low_texture_window_ns <= 0 or self.low_texture_k_consecutive < 1:
            raise ValueError(
                "low_texture_window_ns y low_texture_k_consecutive deben ser positivos"
            )


# ---------------------------------------------------------------------------
# Tracker interno — doble condición K + ventana
# ---------------------------------------------------------------------------


@dataclass
class _DoubleConditionTracker:
    """Una sola condición con verificación doble (K consecutivas + window).

    Per ``perception.md`` §4.1. Estado interno:

    - ``streak_count``: cuántas muestras consecutivas dentro del envelope.
    - ``streak_start_ns``: instante de la primera muestra de la racha actual.

    Cualquier muestra fuera de envelope resetea ambos. Esto es lo que cierra
    el agujero de oscilación: si la señal alterna cada N muestras, el contador
    nunca llega a K.
    """

    streak_count: int = 0
    streak_start_ns: int | None = None

    def observe(self, *, in_envelope: bool, stamp_ns: int) -> None:
        if in_envelope:
            if self.streak_count == 0:
                self.streak_start_ns = stamp_ns
            self.streak_count += 1
        else:
            self.reset()

    def met(self, *, now_ns: int, k: int, window_ns: int) -> bool:
        if self.streak_count < k or self.streak_start_ns is None:
            return False
        return (now_ns - self.streak_start_ns) >= window_ns

    def reset(self) -> None:
        self.streak_count = 0
        self.streak_start_ns = None


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class PerceptionModeDetector:
    """FSM perceptual con subconjunto U1.b de transiciones.

    Uso:

    .. code-block:: python

        det = PerceptionModeDetector(sink=RecordingModeEventSink())
        det.record_motion_observation(...)
        det.record_feature_observation(...)
        det.tick(now_ns)
        assert det.current_mode == PerceptionMode.MOTION_AGGRESSIVE

    El detector **no** decide comportamiento — solo nombra el modo activo.
    La política la consume ``mission/`` y los tier T2/T1 (ver `mission.md` y
    ADR-0009), fuera del alcance de U1.b.
    """

    def __init__(
        self,
        config: DetectorConfig | None = None,
        sink: ModeEventSink | None = None,
        initial_mode: PerceptionMode = PerceptionMode.NOMINAL,
        initial_stamp_ns: int = 0,
    ) -> None:
        if initial_stamp_ns < 0:
            raise ValueError(
                f"initial_stamp_ns debe ser ≥ 0; recibido {initial_stamp_ns}"
            )
        self._config: DetectorConfig = config if config is not None else DetectorConfig()
        self._sink: ModeEventSink = sink if sink is not None else NullModeEventSink()
        self._current_mode: PerceptionMode = initial_mode
        self._mode_entered_ns: int = initial_stamp_ns

        # Un tracker por criterio relevante en U1.b.
        self._motion_entry = _DoubleConditionTracker()
        self._motion_recovery = _DoubleConditionTracker()
        self._low_texture_entry = _DoubleConditionTracker()
        self._low_texture_recovery = _DoubleConditionTracker()

        # Última información de productores que contribuye a cada criterio.
        # Usada al construir `producer_ids` en el evento emitido.
        self._last_motion_producer: str = ""
        self._last_motion_degraded: tuple[str, ...] = ()
        self._last_feature_producer: str = ""

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> PerceptionMode:
        return self._current_mode

    @property
    def config(self) -> DetectorConfig:
        return self._config

    def record_motion_observation(
        self,
        *,
        producer_id: str,
        stamp_sim_ns: int,
        commanded_rate_rps_max: float,
        measured_accel_mps2_excl_g: float,
        degraded_producers_in_window: tuple[str, ...],
    ) -> None:
        """Recibe una observación del productor ``motion.aggressive``.

        Schema per ``perception.md`` §5.6. ``degraded_producers_in_window`` es
        tupla por la regla de colecciones estables (uncertainty.md §10).
        """
        if not isinstance(degraded_producers_in_window, tuple):
            raise TypeError(
                "degraded_producers_in_window debe ser tuple "
                "(uncertainty.md §10 prohíbe colecciones inestables); "
                f"recibido {type(degraded_producers_in_window).__name__}"
            )
        if stamp_sim_ns < 0:
            raise ValueError(f"stamp_sim_ns debe ser ≥ 0; recibido {stamp_sim_ns}")
        if not producer_id:
            raise ValueError("producer_id no puede ser vacío")

        self._last_motion_producer = producer_id
        cfg = self._config

        # Entry signal (ADR-0010 §1): rate/accel sobre threshold AND ≥1 degraded.
        rate_or_accel_excess = (
            commanded_rate_rps_max >= cfg.aggressive_rate_threshold_rps
            or measured_accel_mps2_excl_g >= cfg.aggressive_accel_threshold_mps2
        )
        entry_signal = rate_or_accel_excess and len(degraded_producers_in_window) >= 1

        if entry_signal:
            self._last_motion_degraded = degraded_producers_in_window

        self._motion_entry.observe(in_envelope=entry_signal, stamp_ns=stamp_sim_ns)

        # Recovery signal (ADR-0010 §1): rate y accel < factor * threshold AND no degraded.
        f = cfg.aggressive_recovery_threshold_factor
        rate_ok = commanded_rate_rps_max < f * cfg.aggressive_rate_threshold_rps
        accel_ok = measured_accel_mps2_excl_g < f * cfg.aggressive_accel_threshold_mps2
        no_degraded = len(degraded_producers_in_window) == 0
        recovery_signal = rate_ok and accel_ok and no_degraded

        self._motion_recovery.observe(in_envelope=recovery_signal, stamp_ns=stamp_sim_ns)

    def record_feature_observation(
        self,
        *,
        producer_id: str,
        stamp_sim_ns: int,
        feature_count: int,
    ) -> None:
        """Recibe una observación del productor ``vo.front`` (perception.md §5.1)."""
        if stamp_sim_ns < 0:
            raise ValueError(f"stamp_sim_ns debe ser ≥ 0; recibido {stamp_sim_ns}")
        if not producer_id:
            raise ValueError("producer_id no puede ser vacío")
        if feature_count < 0:
            raise ValueError(f"feature_count debe ser ≥ 0; recibido {feature_count}")

        self._last_feature_producer = producer_id
        cfg = self._config

        # Entry signal: feature_count < min_features.
        entry_signal = feature_count < cfg.low_texture_min_features
        self._low_texture_entry.observe(in_envelope=entry_signal, stamp_ns=stamp_sim_ns)

        # Recovery signal: feature_count >= min_features * recovery_factor.
        recovery_threshold = cfg.low_texture_min_features * cfg.low_texture_recovery_factor
        recovery_signal = feature_count >= recovery_threshold
        self._low_texture_recovery.observe(in_envelope=recovery_signal, stamp_ns=stamp_sim_ns)

    def tick(self, now_ns: int) -> None:
        """Avanza el tiempo y evalúa transiciones desde el modo actual.

        No-op si:

        - no hay observaciones acumuladas que cumplan condición
        - el modo actual está fuera del subconjunto U1.b (no debería ocurrir
          si el detector se construye en NOMINAL / LOW_TEXTURE / MOTION_AGGRESSIVE)
        """
        if now_ns < 0:
            raise ValueError(f"tick: now_ns debe ser ≥ 0; recibido {now_ns}")

        cfg = self._config
        mode = self._current_mode

        if mode == PerceptionMode.NOMINAL:
            # Prioridad: MOTION_AGGRESSIVE (más específico: requiere motion + degraded)
            # antes que LOW_TEXTURE (solo feature_count).
            if self._motion_entry.met(
                now_ns=now_ns,
                k=cfg.aggressive_k_consecutive,
                window_ns=cfg.aggressive_window_ns,
            ):
                producer_ids = (self._last_motion_producer, *self._last_motion_degraded)
                self._transition(
                    to=PerceptionMode.MOTION_AGGRESSIVE,
                    reason="motion_aggressive_entry_criterion_met",
                    producer_ids=producer_ids,
                    stamp_sim_ns=now_ns,
                )
                return

            if self._low_texture_entry.met(
                now_ns=now_ns,
                k=cfg.low_texture_k_consecutive,
                window_ns=cfg.low_texture_window_ns,
            ):
                self._transition(
                    to=PerceptionMode.LOW_TEXTURE,
                    reason="low_texture_entry_criterion_met",
                    producer_ids=(self._last_feature_producer,),
                    stamp_sim_ns=now_ns,
                )
                return

        elif mode == PerceptionMode.MOTION_AGGRESSIVE:
            # Prioridad 1: recuperación sostenida -> NOMINAL (window*2, k_consecutive).
            if self._motion_recovery.met(
                now_ns=now_ns,
                k=cfg.nominal_k_consecutive,
                window_ns=cfg.nominal_hold_ns * 2,
            ):
                self._transition(
                    to=PerceptionMode.NOMINAL,
                    reason="motion_aggressive_recovery_sustained",
                    producer_ids=(self._last_motion_producer or "detector",),
                    stamp_sim_ns=now_ns,
                )
                return

            # Prioridad 2: timeout fuerza degradación a LOW_TEXTURE (ADR-0010 §1).
            elapsed = now_ns - self._mode_entered_ns
            if elapsed >= cfg.aggressive_recovery_timeout_ns:
                self._transition(
                    to=PerceptionMode.LOW_TEXTURE,
                    reason="motion_aggressive_recovery_timeout",
                    producer_ids=(self._last_motion_producer or "detector",),
                    stamp_sim_ns=now_ns,
                )
                return

        elif mode == PerceptionMode.LOW_TEXTURE:
            # Recuperación → NOMINAL (doble condición nominal con feature recovery).
            if self._low_texture_recovery.met(
                now_ns=now_ns,
                k=cfg.nominal_k_consecutive,
                window_ns=cfg.nominal_hold_ns,
            ):
                self._transition(
                    to=PerceptionMode.NOMINAL,
                    reason="low_texture_recovery_sustained",
                    producer_ids=(self._last_feature_producer or "detector",),
                    stamp_sim_ns=now_ns,
                )
                return

        # Modos fuera del alcance U1.b — LOW_LIGHT, IMU_SATURATION, VIO_LOST,
        # MAP_AMBIGUOUS, PERCEPTION_DEAD — no se evalúan aquí.
        # # Deferred to U1.c

    # ------------------------------------------------------------------
    # Transición interna
    # ------------------------------------------------------------------

    def _transition(
        self,
        *,
        to: PerceptionMode,
        reason: str,
        producer_ids: tuple[str, ...],
        stamp_sim_ns: int,
    ) -> None:
        from_mode = self._current_mode
        self._current_mode = to
        self._mode_entered_ns = stamp_sim_ns

        # Limpia todos los trackers para evitar arrastrar rachas pasadas que
        # no aplican al nuevo estado. Las observaciones futuras construirán
        # rachas frescas.
        self._motion_entry.reset()
        self._motion_recovery.reset()
        self._low_texture_entry.reset()
        self._low_texture_recovery.reset()

        event = PerceptionModeChanged(
            from_mode=from_mode,
            to_mode=to,
            reason=reason,
            producer_ids=producer_ids,
            stamp_sim_ns=stamp_sim_ns,
        )
        self._sink.publish(event)


__all__ = ["DetectorConfig", "PerceptionModeDetector"]
