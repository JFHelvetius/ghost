"""`hal.messages` — dataclasses canónicas del HAL (T2 del roadmap).

Submódulos:

- ``sensors`` (T2.a.1, implementado): `SensorHealth`, `SensorSample[T]`,
  `SensorSpec`, payloads (`IMUPayload`, `RGBImagePayload`,
  `DepthImagePayload`, `GpsPayload`, `AltimeterPayload`) y `NoiseModel`
  marker.
- ``actuators`` (T2.a.2, implementado): `ActuatorLevel`, `ActuatorCommand`
  Protocol + 6 niveles concretos, `CommandAck`, `RejectReason`,
  `SafetyEnvelope`, `ActuatorSpec`.
- ``runtime`` (T2.a.4, implementado): `Capabilities`, `ScenarioSpec`,
  `GroundTruth`, `StepReport`.

Las definiciones se re-exportan desde aquí para que los consumidores
escriban ``from project_ghost.hal.messages import SensorSample, ...``.
"""

from __future__ import annotations

from .actuators import (
    ActuatorCommand,
    ActuatorLevel,
    ActuatorSpec,
    AttitudeCommand,
    BodyRateCommand,
    CommandAck,
    DirectMotorCommand,
    PositionCommand,
    RejectReason,
    SafetyEnvelope,
    TrajectoryCommand,
    VelocityCommand,
    VelocityFrame,
)
from .runtime import Capabilities, GroundTruth, ScenarioSpec, StepReport
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
    "ActuatorCommand",
    "ActuatorLevel",
    "ActuatorSpec",
    "AltimeterPayload",
    "AltimeterReference",
    "AttitudeCommand",
    "BodyRateCommand",
    "CameraIntrinsics",
    "Capabilities",
    "CommandAck",
    "DepthImagePayload",
    "DirectMotorCommand",
    "DistortionModel",
    "GpsFix",
    "GpsPayload",
    "GroundTruth",
    "IMUPayload",
    "NoiseModel",
    "PositionCommand",
    "RGBImagePayload",
    "RejectReason",
    "SafetyEnvelope",
    "ScenarioSpec",
    "SensorHealth",
    "SensorId",
    "SensorMeta",
    "SensorSample",
    "SensorSpec",
    "StepReport",
    "TrajectoryCommand",
    "VelocityCommand",
    "VelocityFrame",
]
