"""Vehicle state canonico, convenciones de marco, transformaciones.

ENU mundo, FLU cuerpo, cuaternion Hamilton w-first. Ver docs/specs/state.md.

Submódulos:

- `state.messages` (T2.a.3, implementado): dataclasses canónicas de pose,
  twist, navigation, sensor health, flight, mission y `VehicleState`
  top-level.
- `state.transforms` (T2.a.5, implementado): conjunto exhaustivo y único
  de conversiones de marco — Hamilton↔scipy, body↔world via R, ENU↔NED,
  FLU↔FRD. Cualquier inversión manual fuera de estas funciones es
  candidata a bug (state.md §7).
- `state.aggregator` (T2.a.6, implementado): `vehicle_state_from_ground_truth`
  como vía sim-only para construir un `VehicleState` desde el oráculo del
  simulador. Path de produccion (`from_navigation`) deferido hasta que
  exista un estimador.

`VehicleState` se publica al canal `/state/nav` (state.md §5.3) por el
agregador de T9 cuando aterrice end-to-end con T4 (telemetria) y T6
(backend real).
"""

from __future__ import annotations

from .aggregator import vehicle_state_from_ground_truth
from .messages import (
    FlightMode,
    FlightStatus,
    Goal,
    IMUBiases,
    MissionMode,
    MissionStatus,
    NavigationState,
    Pose,
    SensorHealthMap,
    Twist,
    TwistFrame,
    VehicleState,
)

__all__ = [
    "FlightMode",
    "FlightStatus",
    "Goal",
    "IMUBiases",
    "MissionMode",
    "MissionStatus",
    "NavigationState",
    "Pose",
    "SensorHealthMap",
    "Twist",
    "TwistFrame",
    "VehicleState",
    "vehicle_state_from_ground_truth",
]
