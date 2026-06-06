# SPEC — Event System

- **Estado:** congelado en Fase 0
- **ADR principal:** ADR-0006

## 1. Responsabilidades

- Transportar mensajes **discretos semánticos** entre módulos.
- Garantizar orden total y entrega determinista.
- Soportar prioridades (severidades) y correlación de eventos.
- Persistir todos los eventos en el canal `/events` del MCAP.

**No es responsabilidad del Event System:**

- Transportar streams periódicos de sensor o estado (eso son channels del bus de telemetría con su política propia).
- Implementar reintentos, ack o lógica de transporte de red.

## 2. Distinción: eventos vs streams

| Característica | Eventos | Streams |
|---|---|---|
| Frecuencia | Baja (≤ 1 Hz típico) | Alta (10–1000 Hz) |
| Semántica | Discreta, con significado | Continua, datos |
| Prioridad | Tienen severity | No |
| Ejemplos | takeoff, sensor_fault, mission_start | /sensors/imu0, /state/nav |
| Drop | Nunca dropea (excepto BACKPRESSURE explícito) | Drop policy por sink |

## 3. Schema

```python
class EventSeverity(IntEnum):
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40
    CRITICAL = 50

class EventType(StrEnum):
    # Lifecycle
    ARMED = "armed"
    DISARMED = "disarmed"
    TAKEOFF = "takeoff"
    LANDED = "landed"
    KILL = "kill"
    # Mission
    MISSION_START = "mission_start"
    MISSION_END = "mission_end"
    WAYPOINT_REACHED = "waypoint_reached"
    GOAL_UPDATED = "goal_updated"
    # Safety
    SAFETY_VIOLATION = "safety_violation"
    GEOFENCE_BREACH = "geofence_breach"
    COLLISION_WARNING = "collision_warning"
    COLLISION = "collision"
    RECOVERY_TRIGGERED = "recovery_triggered"
    # Sensors / system
    SENSOR_FAULT = "sensor_fault"
    SENSOR_RECOVERED = "sensor_recovered"
    BATTERY_LOW = "battery_low"
    # Infra
    TELEMETRY_BACKPRESSURE = "telemetry_backpressure"
    SCHEDULER_CALLBACK_FAILED = "scheduler_callback_failed"

@dataclass(frozen=True)
class Event:
    type: EventType
    severity: EventSeverity
    source: str                     # p.ej. "control.attitude", "sim.pybullet"
    stamp_sim_ns: int
    stamp_wall_ns: int
    sequence: int                   # global, monotónico, asignado por el bus
    payload: Mapping[str, Any]      # JSON-serializable
    correlation_id: str | None
    schema_version: int = 1
```

## 4. Bus de eventos

Implementación en `ghost.events`:

```python
class EventBus:
    def publish(self, ev: Event) -> None: ...
    def subscribe(self, types: Iterable[EventType],
                  cb: Callable[[Event], None],
                  min_severity: EventSeverity = EventSeverity.DEBUG) -> Subscription: ...
    def subscribe_all(self, cb: Callable[[Event], None],
                      min_severity: EventSeverity = EventSeverity.DEBUG) -> Subscription: ...
```

Reglas:

- Cada `publish()` asigna `sequence` global atómico y entrega a subscribers en orden total.
- `CRITICAL`: entrega **sincrónica** al subscriber registrado como `safety_handler` antes de continuar.
- Resto: entrega asíncrona desde un dispatcher en thread propio.
- Subscribers que toman > N ms de wall (configurable) emiten `TELEMETRY_BACKPRESSURE`.
- Un subscriber no puede publicar eventos `CRITICAL` desde otro `CRITICAL` (evita cadenas).

## 5. Convención de `correlation_id`

- Cadenas de eventos relacionados comparten `correlation_id` (string opaco).
- Generador estándar: `f"mission-{uuid7()}"`.
- Permite reconstruir secuencias: `MISSION_START → WAYPOINT_REACHED × n → MISSION_END` con mismo id.

## 6. Persistencia

Todos los eventos van al canal `/events` del MCAP via el `TelemetryBus`. La persistencia es responsabilidad de telemetría; el event bus solo coordina entrega in-process.

## 7. Replay

`EventReplay`:

- Lee `/events` del MCAP.
- Reinjecta cada evento en el `EventBus` con su `stamp_sim_ns` y `sequence` original.
- Tests pueden comparar cadenas de eventos esperadas vs producidas.

## 8. Casos de uso

### 8.1 Publicación

```python
events.publish(Event(
    type=EventType.SAFETY_VIOLATION,
    severity=EventSeverity.WARN,
    source="actuators.sink",
    stamp_sim_ns=clock.now_ns(),
    stamp_wall_ns=time.monotonic_ns(),
    sequence=0,                     # asignado por el bus
    payload={"reason": "max_tilt_exceeded", "value_rad": 0.85},
    correlation_id=None,
))
```

### 8.2 Suscripción del safety handler

```python
def on_critical(ev: Event) -> None:
    if ev.type == EventType.KILL:
        actuators.send(emergency_stop(), ev.stamp_sim_ns)
events.subscribe_all(on_critical, min_severity=EventSeverity.CRITICAL)
```

### 8.3 Correlación de misión

```python
mid = f"mission-{uuid7()}"
events.publish(Event(MISSION_START, INFO, "mission.fsm", ...,
                     correlation_id=mid))
# ...
events.publish(Event(WAYPOINT_REACHED, INFO, "mission.fsm", ...,
                     correlation_id=mid, payload={"idx": 3}))
```

## 9. Prioridades operativas

| Severity | Política |
|---|---|
| `DEBUG` | Logueado a MCAP, ignorado por consola |
| `INFO` | Logueado a MCAP, no consola |
| `WARN` | Logueado a MCAP + consola |
| `ERROR` | MCAP + consola + se llama a `on_error` handlers |
| `CRITICAL` | MCAP + consola + entrega sincrónica al safety handler antes de seguir |

## 10. Errores comunes a evitar

- **Usar eventos para datos periódicos.** Saturan el canal y rompen la semántica.
- **Subscribers que bloquean.** El dispatcher mide tiempos; bloqueos largos producen backpressure.
- **Crear nuevos `EventType` ad-hoc.** El enum es centralizado; añadir un tipo es decisión consciente y va con changelog.
- **Olvidar `correlation_id`** en cadenas largas (misión, recovery). Dificulta análisis post-mortem.
- **Publicar `CRITICAL` para condiciones recuperables.** `CRITICAL` debe disparar respuesta inmediata; abusar lo desensibiliza.

## 11. Evolución futura

- Persistencia separada para eventos críticos en archivo aparte (más fácil de auditar).
- Filtros configurables por suscriptor (regex en `source`).
- Integración con sistema de notificaciones externo en HW (Telegram/email).
