"""Vehicle state canonico, convenciones de marco, transformaciones.

ENU mundo, FLU cuerpo, cuaternion Hamilton w-first. Ver docs/specs/state.md.

Submódulos:

- `state.messages` (T2.a.3, implementado): dataclasses canónicas de pose,
  twist, navigation, sensor health, flight, mission y `VehicleState`
  top-level.
- `state.transforms` (T2.a.5, pendiente): helpers quaternion ↔ rotation
  matrix ↔ Euler, ENU↔NED, FLU↔FRD.

`VehicleState` se publica al canal `/state/nav` (state.md §5.3) por el
agregador de T9.
"""

from __future__ import annotations

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
]
