"""Hardware Abstraction Layer.

Protocols, mensajes, capability discovery y conformance.

Implementacion incremental en Fase 1 (T2 del roadmap, ver docs/specs/hal.md):

- `hal.messages.sensors` (T2.a.1, implementado): muestras sensoricas y
  payloads.
- `hal.messages.actuators` (T2.a.2, implementado): jerarquia de comandos,
  CommandAck, RejectReason, SafetyEnvelope, ActuatorSpec.
- `hal.messages.runtime` (T2.a.4, implementado): Capabilities, ScenarioSpec,
  GroundTruth, StepReport.
- `hal.protocols` (T2.a.4, implementado): SimulationBackend, RuntimeBackend,
  SensorProvider, ActuatorSink, Subscription.

`HAL_PROTOCOL_VERSION` se incrementa cuando se rompe compatibilidad
binaria del HAL (hal.md §9).
"""

from __future__ import annotations

from .protocols import (
    ActuatorSink,
    RuntimeBackend,
    SensorProvider,
    SimulationBackend,
    Subscription,
)

HAL_PROTOCOL_VERSION: int = 1

__all__ = [
    "HAL_PROTOCOL_VERSION",
    "ActuatorSink",
    "RuntimeBackend",
    "SensorProvider",
    "SimulationBackend",
    "Subscription",
]
