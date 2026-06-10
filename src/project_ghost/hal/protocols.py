"""Protocols del HAL — `SimulationBackend`, `RuntimeBackend`, `SensorProvider`,
`ActuatorSink`.

Cubre `docs/specs/hal.md` §2 (interfaces). Los Protocols son estructurales:
cualquier clase concreta (un `PyBulletBackend`, un `HardwareBackend`, un
mock en tests) satisface el Protocol si tiene los atributos/métodos
declarados con tipos compatibles. No se requiere herencia explícita.

`Subscription` es un handle simple devuelto por `SensorProvider.subscribe`,
análogo a `events.Subscription` pero independiente — la dirección de
dependencia `hal -> events` está prohibida por `hal.md` §4 (que limita las
importaciones del HAL a `numpy`, `typing`, `dataclasses`, `enum`, `core`).
Los dos tipos hacen el mismo trabajo en distintos dominios.

Decisión de diseño cerrada: `SensorProvider` es `Protocol[T_Payload]`
genérico, donde `T_Payload` es el tipo de payload (IMU/RGB/Depth/etc.).
Esto permite que mypy detecte `provider.poll() -> list[SensorSample[IMUPayload]]`
con seguridad de tipo. A runtime el genérico se borra; `runtime_checkable`
solo verifica presencia de métodos/atributos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from project_ghost.core.clock import SimClock, SystemClock

    from .messages.actuators import ActuatorCommand, ActuatorSpec, CommandAck
    from .messages.runtime import (
        Capabilities,
        GroundTruth,
        ScenarioSpec,
        StepReport,
    )
    from .messages.sensors import SensorId, SensorSample, SensorSpec


# ---------------------------------------------------------------------------
# Subscription handle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subscription:
    """Handle devuelto por `SensorProvider.subscribe`.

    `unsubscribe()` debe ser idempotente y nunca lanzar (mismo contrato
    que `events.Subscription`).
    """

    unsubscribe: Callable[[], None]


# ---------------------------------------------------------------------------
# SensorProvider
# ---------------------------------------------------------------------------


T_Payload = TypeVar("T_Payload")


@runtime_checkable
class SensorProvider(Protocol[T_Payload]):
    """Provider de muestras de un sensor concreto (hal.md §2).

    Modo pull (`poll()`) es el primario en Fase 1; `subscribe()` es push
    y se materializa típicamente a partir de Fase 2 (sensors.md §7.2).
    Backends en Fase 1 pueden implementar `subscribe()` con una lista
    interna de callbacks llamados sincrónicamente al final de cada
    `step()`, o lanzar `NotImplementedError` si todavía no soportan push.
    """

    spec: SensorSpec

    def poll(self) -> list[SensorSample[T_Payload]]: ...
    def subscribe(self, cb: Callable[[SensorSample[T_Payload]], None]) -> Subscription: ...


# ---------------------------------------------------------------------------
# ActuatorSink
# ---------------------------------------------------------------------------


@runtime_checkable
class ActuatorSink(Protocol):
    """Sink de comandos al actuador (hal.md §2, actuators.md §3-§4).

    `send()` aplica el orden estricto de validaciones de
    `actuators.md` §4 y siempre retorna `CommandAck` (nunca `None`,
    nunca lanza por input mal formado).
    """

    spec: ActuatorSpec

    def send(self, cmd: ActuatorCommand, stamp_ns: int) -> CommandAck: ...


# ---------------------------------------------------------------------------
# SimulationBackend / RuntimeBackend
# ---------------------------------------------------------------------------


@runtime_checkable
class SimulationBackend(Protocol):
    """Backend de simulación (PyBullet, Gazebo, replay, mock para tests).

    En backends con `capabilities.deterministic=True`: `reset(scenario,
    seed)` + N llamadas `step(dt_ns)` con mismos inputs produce mismos
    samples y groundtruth (hal.md §3.1).
    """

    capabilities: Capabilities

    def reset(self, scenario: ScenarioSpec, seed: int) -> None: ...
    def step(self, dt_ns: int) -> StepReport: ...
    def shutdown(self) -> None: ...

    @property
    def clock(self) -> SimClock: ...

    def sensors(self) -> Mapping[SensorId, SensorProvider[Any]]: ...
    def actuators(self) -> ActuatorSink: ...
    def ground_truth(self) -> GroundTruth | None: ...


@runtime_checkable
class RuntimeBackend(Protocol):
    """Backend de hardware o sim free-running (hal.md §2, §5.4).

    No tiene `step()`: el mundo avanza solo. Usa `SystemClock` (clock de
    pared / sensor PTP) en lugar de `SimClock`.
    """

    capabilities: Capabilities

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def clock(self) -> SystemClock: ...

    def sensors(self) -> Mapping[SensorId, SensorProvider[Any]]: ...
    def actuators(self) -> ActuatorSink: ...


__all__ = [
    "ActuatorSink",
    "RuntimeBackend",
    "SensorProvider",
    "SimulationBackend",
    "Subscription",
]
