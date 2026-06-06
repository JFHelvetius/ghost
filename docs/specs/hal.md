# SPEC — Hardware Abstraction Layer

- **Estado:** congelado en Fase 0
- **Versión del contrato:** `HAL_PROTOCOL_VERSION = 1`

## 1. Responsabilidades

El HAL es la única capa que conoce **qué cosa concreta** produce sensores y consume actuadores. Su responsabilidad es:

- Exponer Protocols estables (`SimulationBackend`, `RuntimeBackend`, `SensorProvider`, `ActuatorSink`).
- Definir las dataclasses tipadas (`SensorSample`, `ActuatorCommand`, `CommandAck`, `Capabilities`, etc.).
- Definir la conformance test suite que cualquier backend debe pasar.
- Proveer un mecanismo de descubrimiento de capabilities.

**No es responsabilidad del HAL:**

- Implementar simuladores.
- Procesar imágenes, ejecutar filtros, planificar.
- Conocer el modelo del vehículo (eso es `state/`).

## 2. Interfaces

Las firmas mostradas son **especificación**; la implementación final puede añadir docstrings, validaciones y helpers.

```python
HAL_PROTOCOL_VERSION: int = 1

class SimulationBackend(Protocol):
    capabilities: Capabilities
    def reset(self, scenario: ScenarioSpec, seed: int) -> None: ...
    def step(self, dt_ns: int) -> StepReport: ...
    def shutdown(self) -> None: ...
    @property
    def clock(self) -> SimClock: ...
    def sensors(self) -> Mapping[SensorId, SensorProvider]: ...
    def actuators(self) -> ActuatorSink: ...
    def ground_truth(self) -> GroundTruth | None: ...

class RuntimeBackend(Protocol):
    capabilities: Capabilities
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def clock(self) -> SystemClock: ...
    def sensors(self) -> Mapping[SensorId, SensorProvider]: ...
    def actuators(self) -> ActuatorSink: ...

class SensorProvider(Protocol, Generic[T]):
    spec: SensorSpec
    def poll(self) -> list[SensorSample[T]]: ...
    def subscribe(self, cb: Callable[[SensorSample[T]], None]) -> Subscription: ...

class ActuatorSink(Protocol):
    spec: ActuatorSpec
    def send(self, cmd: ActuatorCommand, stamp_ns: int) -> CommandAck: ...

@dataclass(frozen=True)
class Capabilities:
    hal_version: int
    sensor_ids: tuple[SensorId, ...]
    actuator_levels: tuple[ActuatorLevel, ...]
    has_ground_truth: bool
    synchronous_step: bool
    deterministic: bool
    supports_replay: bool
    extensions: Mapping[str, Any]
```

## 3. Contratos vinculantes

1. **Determinismo (en backends que declaran `deterministic=True`).** `reset(scenario, seed)` seguido de N llamadas `step(dt_ns)` con la misma entrada produce groundtruth y secuencia de samples bit-idénticos.
2. **Tiempo bajo control.** En `SimulationBackend`, todo `stamp_ns` viene del `SimClock`. Está prohibido `time.time()`, `time.monotonic()` o equivalentes dentro del backend.
3. **Sin estado oculto entre runs.** Tras `reset()` el backend está en estado equivalente a recién creado.
4. **Mensajes inmutables.** Toda dataclass de mensaje es `frozen=True`.
5. **Sin mutación cruzada.** El array `payload.image` o `payload.gyro_rps` entregado al consumidor no es modificado por el backend después.
6. **Sin excepciones en fallos de sensor.** Un sensor caído reporta `health=FAULTY` u `OFFLINE`, no lanza. Excepciones se reservan para violaciones de contrato (tipo incorrecto, argumentos inválidos).
7. **`ActuatorSink.send()` siempre retorna `CommandAck`.** Nunca `None`, nunca lanza por entrada mal formada; reporta `accepted=False, reason=...`.
8. **Capability discovery antes de uso.** Consumidores que dependen de features opcionales consultan `capabilities` y manejan la ausencia.

## 4. Restricciones

- `ghost.hal` solo importa `numpy`, `typing`, `dataclasses`, `enum`, `core`.
- Prohibido importar `pybullet`, `gz`, `mavsdk`, `airsim`, `omni`, `cv2`, `torch`, `rclpy`.
- Validado en CI con `import-linter` o `deptry`.

## 5. Casos de uso

### 5.1 Inicialización de un run en sim (Fase 1)

```python
backend = PyBulletBackend()                 # implementa SimulationBackend
assert backend.capabilities.deterministic
backend.reset(scenario=load("worlds/empty_room.yaml"), seed=42)
clock = backend.clock
sensors = backend.sensors()
actuators = backend.actuators()
```

### 5.2 Loop de simulación determinista

```python
while clock.now_ns() < end_time_ns:
    backend.step(STEP_NS)
    for sid, provider in sensors.items():
        for sample in provider.poll():
            bus.publish(f"/sensors/{sid}", sample)
    cmd = controller.compute()
    ack = actuators.send(cmd, clock.now_ns())
    if not ack.accepted:
        events.publish(Event(type=EventType.SAFETY_VIOLATION, ...))
```

### 5.3 Sustitución de backend

Cambiar de PyBullet a Gazebo+PX4 SITL es construir el backend nuevo y cambiar el factory; el loop anterior no cambia.

### 5.4 Backend de hardware real (Fase 9+)

```python
backend = HardwareBackend(autopilot="px4", port="/dev/ttyACM0")
backend.start()                              # implementa RuntimeBackend
# clock = SystemClock monotónico
# resto del loop idéntico, sin step() porque el mundo corre solo
```

## 6. Capability discovery

Cada consumidor que usa una feature no garantizada debe consultar:

```python
caps = backend.capabilities
if caps.has_ground_truth:
    gt = backend.ground_truth()
    log_metric("ate", compute_ate(estimate, gt))
else:
    log_metric("ate", None)
```

Las extensiones específicas de backend viajan en `capabilities.extensions` (string → opaque) y en `payload.extensions` de mensajes individuales. El consumidor que no entiende una extensión la ignora.

## 7. Conformance test suite

Ubicación: `tests/hal_conformance/`. Tests parametrizados por backend. Mínimo (Fase 1):

- `test_reset_is_deterministic` — dos secuencias `reset(seed=42), step×N` producen groundtruth idéntico.
- `test_clock_is_monotonic` — `clock.now_ns()` nunca retrocede.
- `test_no_shared_mutation` — `payload` retornado por `poll()` no muta tras siguiente `step()`.
- `test_actuator_rejects_nan` — `send()` con NaN retorna `accepted=False, reason=INVALID_VALUE`.
- `test_actuator_accepts_valid_command` — comando bien formado retorna `accepted=True`.
- `test_shutdown_and_recreate` — tras `shutdown()` y nuevo `reset()`, no hay estado residual.
- `test_capabilities_match_observed` — los `sensor_ids` declarados existen en `sensors()`.

Cada backend nuevo añade tests específicos de su propio comportamiento.

## 8. Errores comunes a evitar

- **Importar el backend desde código de aplicación.** Use factories en `core.runtime` o equivalente.
- **Asumir que todos los backends soportan groundtruth.** Consultar capabilities.
- **Almacenar referencias a samples y modificarlos.** Son frozen; tratarlos como inmutables.
- **Hardcodear `dt`.** Tomarlo del `ScenarioSpec` o del `SimClock`.
- **Lanzar excepciones en `poll()` ante un sensor caído.** Retornar `[]` con `health=OFFLINE`.

## 9. Evolución futura

- `HAL_PROTOCOL_VERSION` se incrementa cuando se rompe compatibilidad. Backends viejos deben ser updateados.
- Nuevos tipos de sensores se añaden con nuevos `Payload` dataclasses; los Protocols existentes no cambian.
- Nuevos niveles de actuador se añaden al enum `ActuatorLevel` con `schema_version`.
- ROS 2 entrará como **adaptador opcional** (`ghost.adapters.ros2`) que traduce entre el bus y topics ROS, sin modificar el HAL.
