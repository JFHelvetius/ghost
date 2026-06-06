"""Tests de `hal.protocols` (T2.a.4).

Cubre el `Subscription` handle y verifica que clases concretas satisfacen
los Protocols `SensorProvider`, `ActuatorSink`, `SimulationBackend`,
`RuntimeBackend` estructuralmente.

Los Protocols son `runtime_checkable`: `isinstance()` verifica presencia
de los métodos/atributos requeridos, no su firma exacta. mypy strict
verifica las firmas en el commit del backend real.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest

from project_ghost.core.clock import SimClockImpl
from project_ghost.hal import (
    HAL_PROTOCOL_VERSION,
    ActuatorSink,
    RuntimeBackend,
    SensorProvider,
    SimulationBackend,
    Subscription,
)
from project_ghost.hal.messages import (
    ActuatorCommand,
    ActuatorLevel,
    ActuatorSpec,
    Capabilities,
    CommandAck,
    DirectMotorCommand,
    GroundTruth,
    IMUPayload,
    SafetyEnvelope,
    ScenarioSpec,
    SensorHealth,
    SensorMeta,
    SensorSample,
    SensorSpec,
    StepReport,
)

# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


def test_subscription_is_frozen() -> None:
    sub = Subscription(unsubscribe=lambda: None)
    with pytest.raises(FrozenInstanceError):
        sub.unsubscribe = lambda: None  # type: ignore[misc]


def test_subscription_unsubscribe_is_called() -> None:
    calls: list[int] = []
    sub = Subscription(unsubscribe=lambda: calls.append(1))
    sub.unsubscribe()
    assert calls == [1]


# ---------------------------------------------------------------------------
# Fakes — implementaciones mínimas que satisfacen los Protocols
# ---------------------------------------------------------------------------


_IDENTITY_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _imu_spec() -> SensorSpec:
    return SensorSpec(
        sensor_id="imu0",
        payload_type="imu",
        nominal_rate_hz=200.0,
        frame_id="body",
        noise_model=None,
    )


def _imu_sample() -> SensorSample[IMUPayload]:
    return SensorSample[IMUPayload](
        sensor_id="imu0",
        seq=0,
        stamp_sensor_ns=0,
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        health=SensorHealth.OK,
        payload=IMUPayload(
            accel_mps2=np.zeros(3, dtype=np.float64),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        ),
        meta=SensorMeta(
            frame_id="body",
            calibration_id=None,
            extensions=MappingProxyType({}),
        ),
    )


def _safety_envelope() -> SafetyEnvelope:
    return SafetyEnvelope(
        max_tilt_rad=0.7,
        max_climb_rate_mps=5.0,
        max_horiz_speed_mps=10.0,
        max_yaw_rate_rps=3.0,
        altitude_min_m=0.0,
        altitude_max_m=100.0,
        geofence_polygon=None,
        command_timeout_ns=500_000_000,
    )


def _capabilities() -> Capabilities:
    return Capabilities(
        hal_version=HAL_PROTOCOL_VERSION,
        sensor_ids=("imu0",),
        actuator_levels=(ActuatorLevel.DIRECT_MOTOR,),
        has_ground_truth=True,
        synchronous_step=True,
        deterministic=True,
        supports_replay=False,
        extensions=MappingProxyType({}),
    )


class _FakeImuProvider:
    """SensorProvider[IMUPayload] mínimo para tests estructurales."""

    def __init__(self) -> None:
        self.spec: SensorSpec = _imu_spec()
        self._subscribers: list[Any] = []

    def poll(self) -> list[SensorSample[IMUPayload]]:
        return [_imu_sample()]

    def subscribe(self, cb: Any) -> Subscription:
        self._subscribers.append(cb)
        def _unsub() -> None:
            if cb in self._subscribers:
                self._subscribers.remove(cb)
        return Subscription(unsubscribe=_unsub)


class _FakeActuatorSink:
    """ActuatorSink mínimo. send() retorna ack aceptado, sin validar."""

    def __init__(self) -> None:
        self.spec: ActuatorSpec = ActuatorSpec(
            actuator_id="main_motors",
            supported_levels=(ActuatorLevel.DIRECT_MOTOR,),
            safety_envelope=_safety_envelope(),
        )
        self.sent: list[ActuatorCommand] = []

    def send(self, cmd: ActuatorCommand, stamp_ns: int) -> CommandAck:
        self.sent.append(cmd)
        return CommandAck(
            accepted=True,
            reason=None,
            applied_stamp_ns=stamp_ns,
            saturated=False,
            extensions=MappingProxyType({}),
        )


class _FakeSimBackend:
    """SimulationBackend mínimo para validación estructural del Protocol."""

    def __init__(self) -> None:
        self.capabilities: Capabilities = _capabilities()
        self._clock = SimClockImpl(seed=42)
        self._sensors: dict[str, SensorProvider[Any]] = {"imu0": _FakeImuProvider()}
        self._actuators = _FakeActuatorSink()
        self._has_reset = False

    def reset(self, scenario: ScenarioSpec, seed: int) -> None:
        del scenario, seed
        self._has_reset = True

    def step(self, dt_ns: int) -> StepReport:
        self._clock.advance(dt_ns)
        return StepReport(dt_advanced_ns=dt_ns, extensions=MappingProxyType({}))

    def shutdown(self) -> None:
        self._has_reset = False

    @property
    def clock(self) -> SimClockImpl:
        return self._clock

    def sensors(self) -> dict[str, SensorProvider[Any]]:
        return self._sensors

    def actuators(self) -> _FakeActuatorSink:
        return self._actuators

    def ground_truth(self) -> GroundTruth | None:
        return GroundTruth(
            stamp_sim_ns=self._clock.now_ns(),
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_IDENTITY_Q.copy(),
            linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
            angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
            accel_body_mps2=np.zeros(3, dtype=np.float64),
        )


class _FakeRuntimeBackend:
    """RuntimeBackend mínimo: sin step, clock externo."""

    def __init__(self) -> None:
        self.capabilities: Capabilities = _capabilities()
        # `SimClock` y `SystemClock` son Protocols distintos; en producción
        # un backend de hardware proveería un SystemClock real. Para tests
        # estructurales reutilizamos SimClockImpl como stand-in (no
        # verificamos firma exacta del clock, solo la presencia del
        # atributo).
        self._clock = SimClockImpl(seed=0)
        self._sensors: dict[str, SensorProvider[Any]] = {}
        self._actuators = _FakeActuatorSink()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def clock(self) -> SimClockImpl:
        return self._clock

    def sensors(self) -> dict[str, SensorProvider[Any]]:
        return self._sensors

    def actuators(self) -> _FakeActuatorSink:
        return self._actuators


# ---------------------------------------------------------------------------
# Protocol checks — runtime_checkable
# ---------------------------------------------------------------------------


def test_fake_imu_provider_satisfies_sensor_provider_protocol() -> None:
    provider = _FakeImuProvider()
    assert isinstance(provider, SensorProvider)


def test_fake_actuator_sink_satisfies_actuator_sink_protocol() -> None:
    sink = _FakeActuatorSink()
    assert isinstance(sink, ActuatorSink)


def test_fake_sim_backend_satisfies_simulation_backend_protocol() -> None:
    backend = _FakeSimBackend()
    assert isinstance(backend, SimulationBackend)


def test_fake_runtime_backend_satisfies_runtime_backend_protocol() -> None:
    backend = _FakeRuntimeBackend()
    assert isinstance(backend, RuntimeBackend)


def test_arbitrary_object_does_not_satisfy_sensor_provider_protocol() -> None:
    """Un objeto sin spec/poll/subscribe no es SensorProvider."""

    class _NotProvider:
        def something(self) -> None:
            pass

    assert not isinstance(_NotProvider(), SensorProvider)


def test_arbitrary_object_does_not_satisfy_actuator_sink_protocol() -> None:
    class _NotSink:
        pass

    assert not isinstance(_NotSink(), ActuatorSink)


# ---------------------------------------------------------------------------
# Integration — un loop minimal Fase 1 estilo (hal.md §5.2)
# ---------------------------------------------------------------------------


def test_simulation_backend_can_run_minimal_phase1_loop() -> None:
    """Mini-loop que verifica que las piezas del Protocol encajan."""
    backend = _FakeSimBackend()
    scenario = ScenarioSpec(
        world_id="empty_room",
        vehicle_id="x500",
        duration_ns=None,
        extensions=MappingProxyType({}),
    )
    backend.reset(scenario, seed=42)
    assert backend.clock.now_ns() == 0

    step_ns = 1_000_000  # 1 ms
    samples_collected: list[SensorSample[Any]] = []
    for _ in range(5):
        report = backend.step(step_ns)
        assert report.dt_advanced_ns == step_ns
        for _sid, provider in backend.sensors().items():
            samples_collected.extend(provider.poll())
        cmd = DirectMotorCommand(throttle=np.array([0.5] * 4, dtype=np.float64))
        ack = backend.actuators().send(cmd, backend.clock.now_ns())
        assert ack.accepted

    assert backend.clock.now_ns() == 5 * step_ns
    assert len(samples_collected) == 5  # 1 provider, 1 sample por step

    gt = backend.ground_truth()
    assert gt is not None
    assert gt.stamp_sim_ns == backend.clock.now_ns()

    backend.shutdown()


def test_sensor_provider_subscribe_returns_working_handle() -> None:
    """`subscribe(cb)` debe devolver una `Subscription` cuyo unsubscribe()
    funcione y sea idempotente."""
    provider = _FakeImuProvider()
    received: list[SensorSample[IMUPayload]] = []
    sub = provider.subscribe(received.append)

    # Hasta que el provider emita, el callback no se invoca; pero podemos
    # verificar que el handle es del tipo correcto y unsubscribe no lanza.
    assert isinstance(sub, Subscription)
    sub.unsubscribe()
    sub.unsubscribe()  # idempotente
    assert len(received) == 0  # nunca se emitió nada explícitamente


def test_capabilities_lists_provider_and_actuator_ids_consistent_with_backend() -> None:
    """Spec hal.md §7: 'test_capabilities_match_observed' — los sensor_ids
    declarados existen en `sensors()`."""
    backend = _FakeSimBackend()
    declared_sensors = backend.capabilities.sensor_ids
    actual_sensors = tuple(backend.sensors().keys())
    for sid in declared_sensors:
        assert sid in actual_sensors
