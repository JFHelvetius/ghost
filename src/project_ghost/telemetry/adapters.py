"""Adapters de Protocols externos a `TelemetrySink`.

Patrón análogo a `events.adapters.SchedulerErrorToEventBusAdapter`: una
clase pequeña que implementa estructuralmente el Protocol del productor
y forwardea cada mensaje al sink de persistencia en el canal
correspondiente.

**Dirección de dependencia.** Las clases que viven aquí importan tipos
del productor (e.g., `core.uncertainty.mode_events.PerceptionModeChanged`)
y los publican en un `TelemetrySink`. Telemetry conoce los tipos del
productor; el productor NO conoce telemetry. Esto preserva la regla
arquitectónica: `telemetry -> core.uncertainty` (one-way).

Adapters incluidos:

- ``ModeEventToTelemetryAdapter`` — implementa
  ``core.uncertainty.mode_events.ModeEventSink``; publica cada
  ``PerceptionModeChanged`` en ``CHANNEL_PERCEPTION_MODE``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .channels import CHANNEL_PERCEPTION_MODE

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.mode_events import PerceptionModeChanged

    from .sink import TelemetrySink


class ModeEventToTelemetryAdapter:
    """Implementa ``ModeEventSink`` reenviando al ``TelemetrySink``.

    Uso típico (alimentar la persistencia del detector U1.b):

    .. code-block:: python

        from project_ghost.core.uncertainty import PerceptionModeDetector
        from project_ghost.telemetry import (
            MCAPFileSink, ModeEventToTelemetryAdapter,
        )

        with MCAPFileSink(path) as mcap:
            adapter = ModeEventToTelemetryAdapter(mcap)
            detector = PerceptionModeDetector(sink=adapter)
            ...  # detector emite a adapter, adapter persiste en /perception/mode

    Contrato:

    - ``publish(event)`` toma el ``stamp_sim_ns`` del propio evento como
      ``log_time`` del MCAP. No lee reloj de pared (ADR-0002).
    - Si el sink falla, la excepción se propaga. El detector U1.b
      documenta que un sink defectuoso no debe colapsar la FSM, así
      que en la práctica el adapter debería envolverse en un sink
      defensivo si esa garantía se quiere preservar — no es
      responsabilidad de este adapter.
    - El canal se puede sobrescribir vía constructor; el default es
      ``CHANNEL_PERCEPTION_MODE``.
    """

    def __init__(
        self,
        sink: TelemetrySink,
        channel: str = CHANNEL_PERCEPTION_MODE,
    ) -> None:
        if not channel.startswith("/"):
            raise ValueError(
                f"channel debe empezar con '/'; recibido {channel!r}"
            )
        self._sink: TelemetrySink = sink
        self._channel: str = channel

    @property
    def channel(self) -> str:
        return self._channel

    def publish(self, event: PerceptionModeChanged) -> None:
        self._sink.publish(self._channel, event.stamp_sim_ns, event)


__all__ = ["ModeEventToTelemetryAdapter"]
