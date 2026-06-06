# SPEC — Actuator API

- **Estado:** congelado en Fase 0

## 1. Responsabilidades

- Definir la jerarquía de comandos del vehículo.
- Definir el ack model (`CommandAck`) para todos los comandos.
- Definir el `SafetyEnvelope` aplicable en frontera.

**No es responsabilidad del Actuator API:**

- Implementar control (eso es `control/`).
- Conocer la dinámica del vehículo más allá de los límites declarados.

## 2. Jerarquía de comandos

Cinco niveles, ordenados de bajo a alto. Reflejan PX4 offboard mode para facilitar migración a hardware.

| Nivel | Nombre | Contenido | Fase típica |
|---|---|---|---|
| 0 | `DirectMotorCommand` | throttle por motor `[0, 1]` | Fase 1 (control manual, ID) |
| 1 | `BodyRateCommand` | body rates (rps) + thrust normalizado | Fase 2 (inner loop) |
| 2 | `AttitudeCommand` | cuaternión target + thrust | Fase 2 |
| 3 | `VelocityCommand` | velocidad (body o world) + yaw | Fase 3+ |
| 4 | `PositionCommand` | posición ENU + yaw | Fase 5+ |
| 5 | `TrajectoryCommand` | trayectoria parametrizada (sample times + setpoints) | Fase 6+ |

Cada nivel implementa `ActuatorCommand`:

```python
class ActuatorLevel(IntEnum):
    DIRECT_MOTOR = 0
    BODY_RATE = 1
    ATTITUDE = 2
    VELOCITY = 3
    POSITION = 4
    TRAJECTORY = 5

class ActuatorCommand(Protocol):
    level: ActuatorLevel
    stamp_ns: int
    schema_version: int
```

### Ejemplos

```python
@dataclass(frozen=True)
class DirectMotorCommand:
    level: ActuatorLevel = ActuatorLevel.DIRECT_MOTOR
    throttle: np.ndarray            # (N,) float64 en [0, 1]
    stamp_ns: int = 0
    schema_version: int = 1

@dataclass(frozen=True)
class AttitudeCommand:
    level: ActuatorLevel = ActuatorLevel.ATTITUDE
    q_target: np.ndarray            # (4,) Hamilton w-first
    thrust_normalized: float        # [0, 1]
    yaw_rate_rps: float | None = None
    stamp_ns: int = 0
    schema_version: int = 1

@dataclass(frozen=True)
class PositionCommand:
    level: ActuatorLevel = ActuatorLevel.POSITION
    position_enu_m: np.ndarray      # (3,)
    yaw_rad: float | None = None
    stamp_ns: int = 0
    schema_version: int = 1
```

## 3. Ack model

Todo `send()` retorna `CommandAck`:

```python
class RejectReason(StrEnum):
    INVALID_VALUE = "invalid_value"
    OUT_OF_RANGE = "out_of_range"
    STALE_STAMP = "stale_stamp"
    NOT_ARMED = "not_armed"
    UNSUPPORTED_LEVEL = "unsupported_level"
    SAFETY_VIOLATION = "safety_violation"
    BACKEND_BUSY = "backend_busy"

@dataclass(frozen=True)
class CommandAck:
    accepted: bool
    reason: RejectReason | None
    applied_stamp_ns: int           # tiempo en que se aplicó (o intentó)
    saturated: bool                 # se hizo clipping
    extensions: Mapping[str, Any]
```

Reglas:

- Nunca retornar `None`; siempre `CommandAck`.
- Nunca lanzar por entrada mal formada; reportar `accepted=False`.
- `saturated=True` cuando hubo clipping pero el comando se aceptó (p. ej. thrust pedido > max, se aplicó max).

## 4. Validaciones (orden de aplicación)

En `ActuatorSink.send()`, en este orden estricto:

1. **Tipo y finitud.** Shapes correctas, sin NaN, sin Inf.
2. **Rangos físicos.** `thrust ∈ [0, 1]`, `|rate| ≤ max_rate`, ángulos finitos.
3. **Tasa de mando.** Si `stamp_ns` retrocede o es más antiguo que `command_timeout_ns` respecto a `clock.now_ns()`, rechazar con `STALE_STAMP`.
4. **Soporte de nivel.** Si el backend no soporta `cmd.level`, rechazar con `UNSUPPORTED_LEVEL`. Documentar capability.
5. **Estado armado.** Si `require_arm=True` y no está armado, rechazar con `NOT_ARMED`.
6. **Safety envelope.** Ver §5.
7. **Saturación.** Clipping a límites; marcar `saturated=True`.

## 5. Safety envelope

```python
@dataclass(frozen=True)
class SafetyEnvelope:
    max_tilt_rad: float
    max_climb_rate_mps: float
    max_horiz_speed_mps: float
    max_yaw_rate_rps: float
    altitude_min_m: float
    altitude_max_m: float
    geofence_polygon: list[tuple[float, float]] | None
    command_timeout_ns: int
    require_arm: bool = True
```

- Configurada por vehículo/misión en `configs/vehicles/<name>.yaml`.
- Aplicada en cada `send()` antes de despachar al backend.
- Violación: `accepted=False, reason=SAFETY_VIOLATION` + evento `SAFETY_VIOLATION` en `/events` con severity ≥ WARN.

En sim, las violaciones son educativas. En hardware real (Fase 9+) la envelope se duplica con kill switch hardware y geofence PX4 nativa.

## 6. Casos de uso

### 6.1 Comando manual (Fase 1)

```python
cmd = DirectMotorCommand(throttle=np.array([0.5, 0.5, 0.5, 0.5]),
                         stamp_ns=clock.now_ns())
ack = actuators.send(cmd, cmd.stamp_ns)
if not ack.accepted:
    logger.warn("rejected: %s", ack.reason)
```

### 6.2 Cascada attitude → motor (Fase 2)

El backend acepta `BodyRateCommand`; internamente el backend (o un mixer en `actuators/`) traduce a throttles. El controlador superior no se entera.

### 6.3 Offboard PX4 (Fase 4+ SITL)

```python
cmd = PositionCommand(position_enu_m=goal, yaw_rad=0.0,
                      stamp_ns=clock.now_ns())
ack = actuators.send(cmd, cmd.stamp_ns)
# Backend traduce a SET_POSITION_TARGET_LOCAL_NED vía MAVLink (con conversión ENU→NED)
```

## 7. Errores comunes a evitar

- **Hardcodear N=4 motores.** El API es N-rotor agnóstico; usar `len(throttle)`.
- **Asumir que el backend acepta cualquier nivel.** Consultar `capabilities.actuator_levels`.
- **Reusar el mismo objeto comando entre frames.** Frozen, pero crear nuevo por claridad de logs.
- **Aplicar safety envelope en el controller superior.** Es responsabilidad del sink, no del controller.

## 8. Evolución futura

- Niveles adicionales: `TorqueCommand` y `WrenchCommand` para investigación de control no lineal.
- Soporte de mezcla configurable (X, +, H, octo) en un `mixer.py` aparte.
- Comandos de actuadores auxiliares (gimbal, payload release) bajo un Sink separado para no contaminar el vuelo.
