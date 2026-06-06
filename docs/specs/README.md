# Specifications

Especificaciones detalladas de los componentes congelados en Fase 0. Cada documento es contrato vinculante; cambios requieren ADR.

| Documento | Cubre |
|---|---|
| [hal.md](hal.md) | Hardware Abstraction Layer: backends, Protocols, capability discovery, conformance |
| [sensors.md](sensors.md) | Sensor API: IMU, RGB, depth, GPS, altímetro, formato `SensorSample`, sincronía |
| [actuators.md](actuators.md) | Actuator API: jerarquía de comandos, `CommandAck`, `SafetyEnvelope` |
| [state.md](state.md) | Vehicle State: `VehicleState`, convenciones de marco y cuaternión |
| [clock.md](clock.md) | Simulation / System Clock: integer-ns, scheduler, `RandomSource`, replay |
| [telemetry.md](telemetry.md) | Telemetry: MCAP, sinks, Rerun, manifest |
| [events.md](events.md) | Event System: schema, severidades, persistencia, replay |
| [uncertainty.md](uncertainty.md) | Uncertainty model: `Estimate[T]`, `Validity`, catálogo de `PerceptionMode`, inflación de covarianza |
| [perception.md](perception.md) | Perception layer: productores perceptuales, `PerceptionModeDetector`, FSM |
| [mission.md](mission.md) | Mission layer: `MissionSpec`, `Goal`, `UncertaintyBudget`, planning consciente de incertidumbre |
