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
- ``SelfAssessmentToTelemetryAdapter`` — publica cada
  ``BeliefSelfAssessment`` en ``CHANNEL_SELF_ASSESSMENT``
  (ADR-0020).
- ``DecisionToTelemetryAdapter`` — implementa
  ``core.decisions.DecisionSink``; publica cada `(decision,
  rationale)` en ``CHANNEL_DECISIONS`` como ``DecisionRationale``
  (ADR-0021).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .channels import (
    CHANNEL_DECISIONS,
    CHANNEL_PERCEPTION_MODE,
    CHANNEL_SELF_ASSESSMENT,
)

if TYPE_CHECKING:
    from project_ghost.core.decisions.types import (
        Decision,
        DecisionRationale,
    )
    from project_ghost.core.uncertainty.mode_events import PerceptionModeChanged
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )

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


class SelfAssessmentToTelemetryAdapter:
    """Publica ``BeliefSelfAssessment`` al ``TelemetrySink``.

    Uso típico — wiring del agente runtime de introspección (ADR-0020):

    .. code-block:: python

        from project_ghost.core.uncertainty.self_assessment import (
            assess_belief, AssessmentThresholds,
        )
        from project_ghost.telemetry import (
            MCAPFileSink, SelfAssessmentToTelemetryAdapter,
        )

        thresholds = AssessmentThresholds(...)
        with MCAPFileSink(path) as mcap:
            adapter = SelfAssessmentToTelemetryAdapter(mcap)
            for vehicle_state in belief_stream:
                assessment = assess_belief(vehicle_state, thresholds)
                adapter.publish(assessment)

    Contrato:

    - ``publish(assessment)`` toma ``assessment.belief_stamp_sim_ns``
      como ``log_time`` del MCAP. No lee reloj de pared (ADR-0002).
    - Si el sink falla, la excepción se propaga. El caller decide
      el envoltorio defensivo.
    - El canal se puede sobrescribir vía constructor; el default es
      ``CHANNEL_SELF_ASSESSMENT``.
    """

    def __init__(
        self,
        sink: TelemetrySink,
        channel: str = CHANNEL_SELF_ASSESSMENT,
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

    def publish(self, assessment: BeliefSelfAssessment) -> None:
        self._sink.publish(
            self._channel, assessment.belief_stamp_sim_ns, assessment
        )


class DecisionToTelemetryAdapter:
    """Implementa ``core.decisions.DecisionSink`` reenviando al
    ``TelemetrySink`` (ADR-0021).

    Publica el ``DecisionRationale`` como record en
    ``CHANNEL_DECISIONS``. El ``Decision`` viaja dentro del rationale
    (``rationale.decision``); no se publica por separado — el contrato
    de ADR-0021 requiere que toda decisión publicada lleve rationale
    adjunto, y publicar el rationale satisface ambos al mismo tiempo.

    Uso típico — wiring de un agente runtime con decisiones:

    .. code-block:: python

        from project_ghost.core.decisions import (
            UncertaintyAwareReferencePolicy, decide_and_publish,
        )
        from project_ghost.telemetry import (
            MCAPFileSink, DecisionToTelemetryAdapter,
        )

        policy = UncertaintyAwareReferencePolicy()
        with MCAPFileSink(path) as mcap:
            sink = DecisionToTelemetryAdapter(mcap)
            for context in agent_context_stream:
                decide_and_publish(policy, context, sink)

    Contrato:

    - ``publish(decision, rationale)`` valida que ``rationale.decision
      == decision``. Si no matchea, raise ``ValueError`` (no se
      publica nada — falla loud).
    - ``decision.decision_stamp_sim_ns`` se usa como ``log_time``
      de MCAP. No lee reloj de pared (ADR-0002).
    - El canal se puede sobrescribir vía constructor; default es
      ``CHANNEL_DECISIONS``.
    """

    def __init__(
        self,
        sink: TelemetrySink,
        channel: str = CHANNEL_DECISIONS,
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

    def publish(
        self,
        decision: Decision,
        rationale: DecisionRationale,
    ) -> None:
        if rationale.decision != decision:
            raise ValueError(
                "DecisionToTelemetryAdapter.publish: rationale.decision "
                "must equal decision"
            )
        self._sink.publish(
            self._channel,
            decision.decision_stamp_sim_ns,
            rationale,
        )


__all__ = [
    "DecisionToTelemetryAdapter",
    "ModeEventToTelemetryAdapter",
    "SelfAssessmentToTelemetryAdapter",
]
