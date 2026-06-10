"""Eventos de cambio de modo perceptual y sus sinks (U1.b).

Define el tipo de evento que el `PerceptionModeDetector` emite en cada
transición y los Protocols/implementaciones de sink usados por tests y
(eventualmente) por el `EventBus` real de T5.

El tipo vive aquí, no en `events/`, porque el evento pertenece al **dominio
de incertidumbre**, no al transporte. La dirección de dependencia
correcta es ``events/ → core.uncertainty``; nunca al revés.

Schema canónico: ``docs/specs/uncertainty.md`` §9 (canal ``/perception/mode``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# `PerceptionMode` se importa a runtime (no en TYPE_CHECKING) para que
# `typing.get_type_hints(PerceptionModeChanged)` pueda resolver las
# anotaciones — `telemetry.serialization.from_json_dict` lo necesita para
# round-trip decoding (T7 / decoder catalog en replay.py).
from .types import PerceptionMode  # noqa: TC001


@dataclass(frozen=True)
class PerceptionModeChanged:
    """Evento emitido en `/perception/mode` ante cada transición de la FSM.

    Schema per `docs/specs/uncertainty.md` §9. Los campos son obligatorios:

    - ``from_mode`` / ``to_mode``: nombres del catálogo cerrado
      (``PerceptionMode``; modificarlo exige ADR per ADR-0010).
    - ``reason``: cadena humana corta del estilo "rate_threshold_exceeded".
      Su contrato es: humanamente leíble, libre de timestamps embebidos
      (esos viven en ``stamp_sim_ns``).
    - ``producer_ids``: identificadores de los productores que contribuyeron
      a la decisión. **Tupla, no set** (regla de colecciones estables en
      `uncertainty.md` §10).
    - ``stamp_sim_ns``: instante de la transición en tiempo de simulación.
    - ``schema_version``: versión del schema; default 1 hasta que un ADR
      futuro lo cambie aditivamente.
    """

    from_mode: PerceptionMode
    to_mode: PerceptionMode
    reason: str
    producer_ids: tuple[str, ...]
    stamp_sim_ns: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.producer_ids, tuple):
            raise TypeError(
                "PerceptionModeChanged.producer_ids debe ser tuple "
                "(uncertainty.md §10 prohíbe colecciones inestables); "
                f"recibido {type(self.producer_ids).__name__}"
            )
        if not self.reason:
            raise ValueError("PerceptionModeChanged.reason no puede ser vacío")
        if self.stamp_sim_ns < 0:
            raise ValueError(
                f"PerceptionModeChanged.stamp_sim_ns debe ser ≥ 0; recibido {self.stamp_sim_ns}"
            )
        if self.schema_version < 1:
            raise ValueError(
                f"PerceptionModeChanged.schema_version debe ser ≥ 1; recibido {self.schema_version}"
            )


@runtime_checkable
class ModeEventSink(Protocol):
    """Sink de eventos de modo perceptual.

    El `PerceptionModeDetector` recibe un sink en su constructor y llama
    ``publish`` ante cada transición. En T5 (EventBus real) el adapter al
    bus implementará este Protocol. Para tests, ver `RecordingModeEventSink`.

    Contractualmente:

    - ``publish`` NO debe lanzar excepciones controlables del sink al detector
      (un sink defectuoso no debe colapsar la FSM). Esto se documenta aquí;
      no se enforza con `try/except` general en el detector porque tragar
      errores genéricos esconde bugs reales.
    - ``publish`` debe tratar el evento como inmutable (lo es por
      construcción; el sink no debe intentar mutarlo).
    """

    def publish(self, event: PerceptionModeChanged) -> None: ...


class NullModeEventSink:
    """Sink no-op. Default cuando el detector se construye sin sink explícito."""

    def publish(self, event: PerceptionModeChanged) -> None:  # noqa: ARG002
        return None


@dataclass
class RecordingModeEventSink:
    """Sink que acumula eventos en orden. Para tests deterministas.

    No-frozen porque acumula estado mutable interno (la lista de eventos).
    Los eventos en sí son frozen.
    """

    events: list[PerceptionModeChanged] = field(default_factory=list)

    def publish(self, event: PerceptionModeChanged) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


__all__ = [
    "ModeEventSink",
    "NullModeEventSink",
    "PerceptionModeChanged",
    "RecordingModeEventSink",
]
