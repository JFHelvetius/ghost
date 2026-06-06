"""`hal.messages` — dataclasses canónicas del HAL (T2 del roadmap).

Submódulos (incrementales por sub-tarea de T2.a):

- ``sensors`` (T2.a.1, implementado): `SensorHealth`, `SensorSample[T]`,
  `SensorSpec`, payloads (`IMUPayload`, `RGBImagePayload`,
  `DepthImagePayload`, `GpsPayload`, `AltimeterPayload`) y `NoiseModel`
  marker.
- ``actuators`` (T2.a.2, pendiente): `ActuatorLevel`, comandos jerárquicos,
  `CommandAck`, `SafetyEnvelope`, `RejectReason`.

Las definiciones se re-exportan desde aquí para que los consumidores
escriban ``from project_ghost.hal.messages import SensorSample, ...``.
"""

from __future__ import annotations

from .sensors import (
    AltimeterPayload,
    AltimeterReference,
    CameraIntrinsics,
    DepthImagePayload,
    DistortionModel,
    GpsFix,
    GpsPayload,
    IMUPayload,
    NoiseModel,
    RGBImagePayload,
    SensorHealth,
    SensorId,
    SensorMeta,
    SensorSample,
    SensorSpec,
)

__all__ = [
    "AltimeterPayload",
    "AltimeterReference",
    "CameraIntrinsics",
    "DepthImagePayload",
    "DistortionModel",
    "GpsFix",
    "GpsPayload",
    "IMUPayload",
    "NoiseModel",
    "RGBImagePayload",
    "SensorHealth",
    "SensorId",
    "SensorMeta",
    "SensorSample",
    "SensorSpec",
]
