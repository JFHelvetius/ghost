"""Hardware Abstraction Layer.

Protocols, mensajes, capability discovery y conformance.
Implementacion incremental en Fase 1 (T2 del roadmap, ver docs/specs/hal.md):

- `hal.messages.sensors` (T2.a.1, implementado): dataclasses de muestras
  sensoricas y sus payloads.
- `hal.messages.actuators` (T2.a.2, implementado): jerarquia de comandos,
  CommandAck, RejectReason, SafetyEnvelope, ActuatorSpec.
- `hal.protocols` (T2.a.4, pendiente): SimulationBackend, RuntimeBackend,
  SensorProvider, ActuatorSink Protocols + Capabilities.

`HAL_PROTOCOL_VERSION` se incrementa cuando se rompe compatibilidad
binaria del HAL (hal.md §9).
"""

HAL_PROTOCOL_VERSION: int = 1
