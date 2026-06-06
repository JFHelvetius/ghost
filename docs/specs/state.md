# SPEC — Vehicle State Model

- **Estado:** congelado en Fase 0
- **ADR principal:** ADR-0005

## 1. Responsabilidades

- Definir `VehicleState` como única estructura canónica que describe el estado del dron.
- Fijar convenciones de marco, rotación y unidades.
- Proveer utilidades estables para transformaciones (cuaternión ↔ matriz ↔ Euler, ENU↔NED, FLU↔FRD).

**No es responsabilidad del State:**

- Estimar el estado (eso es `estimation/`).
- Almacenar datos crudos de sensor.
- Conocer cómo se llegó al estado.

## 2. Convenciones congeladas

| Aspecto | Decisión |
|---|---|
| Marco mundo | ENU (East-North-Up); z=0 al suelo |
| Marco cuerpo | FLU (Forward-Left-Up) |
| Cuaternión | Hamilton, `[w, x, y, z]` |
| Rotación de scipy | Documentar permutación: `Rotation.from_quat(q[[1,2,3,0]])` |
| Unidades | SI estrictas (m, m/s, rad, rad/s, kg, N, s) |
| Tiempo | `int` nanosegundos en estructuras del estado |
| Precisión | `float64` para pose, twist, accel, biases, covarianzas |

## 3. Estructura

```python
@dataclass(frozen=True)
class Pose:
    position_enu_m: np.ndarray      # (3,) float64
    orientation_q: np.ndarray       # (4,) Hamilton w-first

@dataclass(frozen=True)
class Twist:
    linear_mps: np.ndarray          # (3,)
    angular_rps: np.ndarray         # (3,)
    frame: Literal["world", "body"]

@dataclass(frozen=True)
class IMUBiases:
    accel_bias_mps2: np.ndarray     # (3,)
    gyro_bias_rps: np.ndarray       # (3,)

@dataclass(frozen=True)
class NavigationState:
    pose: Pose
    twist_world: Twist              # frame="world"
    twist_body: Twist               # frame="body" (redundante por conveniencia)
    accel_body_mps2: np.ndarray     # (3,)
    imu_biases: IMUBiases
    covariance_15x15: np.ndarray | None
    # Orden de las 15 variables: [p(3), v(3), q_tangent(3), b_a(3), b_g(3)]

@dataclass(frozen=True)
class SensorHealthMap:
    by_id: Mapping[SensorId, SensorHealth]

class FlightMode(StrEnum):
    INIT = "init"
    MANUAL = "manual"
    STABILIZE = "stabilize"
    OFFBOARD = "offboard"
    RTL = "rtl"
    LAND = "land"
    KILL = "kill"

@dataclass(frozen=True)
class FlightStatus:
    armed: bool
    flight_mode: FlightMode
    battery_v: float | None
    battery_pct: float | None
    error_flags: int                # bitfield documentado en `core.errors`

class MissionMode(StrEnum):
    IDLE = "idle"
    EXPLORE = "explore"
    NAVIGATE = "navigate"
    RETURN = "return"
    DONE = "done"
    ABORT = "abort"

@dataclass(frozen=True)
class Goal:
    position_enu_m: np.ndarray | None
    yaw_rad: float | None
    metadata: Mapping[str, Any]

@dataclass(frozen=True)
class MissionStatus:
    mode: MissionMode
    current_goal: Goal | None
    progress: float                 # [0, 1] semántica por misión
    started_sim_ns: int | None

@dataclass(frozen=True)
class VehicleState:
    stamp_sim_ns: int
    stamp_wall_ns: int
    nav: NavigationState
    sensors: SensorHealthMap
    flight: FlightStatus
    mission: MissionStatus
    schema_version: int = 1
```

## 4. Contratos

1. **Frozen.** `VehicleState` es inmutable. Cada ciclo produce un nuevo objeto.
2. **No contiene datos crudos.** Imágenes, IMU samples, point clouds no viajan en `VehicleState`.
3. **`schema_version` monótono creciente.** Romper compatibilidad requiere ADR; durante deprecación se mantienen ambos por un release.
4. **Marco declarado explícitamente.** Cualquier vector cuyo frame sea ambiguo lleva el sufijo de frame (`_enu_m`, `_body_mps2`) en el nombre del campo.
5. **Covarianza opcional.** `covariance_15x15` puede ser `None` cuando no se estima (Fase 1 con groundtruth) o cuando no se confía.

## 5. Casos de uso

### 5.1 Construcción en Fase 1 (con groundtruth)

```python
nav = NavigationState(
    pose=Pose(position_enu_m=gt.pos, orientation_q=gt.q),
    twist_world=Twist(linear_mps=gt.vel, angular_rps=gt.omega_world,
                      frame="world"),
    twist_body=Twist(linear_mps=R_body_world(gt.q) @ gt.vel,
                     angular_rps=gt.omega_body, frame="body"),
    accel_body_mps2=gt.accel_body,
    imu_biases=IMUBiases(np.zeros(3), np.zeros(3)),
    covariance_15x15=None,
)
state = VehicleState(stamp_sim_ns=t, stamp_wall_ns=tw,
                    nav=nav, sensors=health, flight=flight,
                    mission=mission)
```

### 5.2 Consumo por controlador

El controlador recibe `VehicleState`, lee `nav.pose` y `nav.twist_world`, computa comando. Nunca modifica `state`.

### 5.3 Consumo por telemetría

Cada `VehicleState` publicado al bus se escribe al canal `/state/nav` del MCAP.

## 6. Utilidades estables (en `state.transforms`)

```python
def quat_hamilton_to_scipy(q: np.ndarray) -> np.ndarray: ...
def quat_scipy_to_hamilton(q: np.ndarray) -> np.ndarray: ...
def R_body_to_world(q_hamilton: np.ndarray) -> np.ndarray: ...
def R_world_to_body(q_hamilton: np.ndarray) -> np.ndarray: ...
def enu_to_ned(v_enu: np.ndarray) -> np.ndarray: ...
def ned_to_enu(v_ned: np.ndarray) -> np.ndarray: ...
def flu_to_frd(v_flu: np.ndarray) -> np.ndarray: ...
def frd_to_flu(v_frd: np.ndarray) -> np.ndarray: ...
```

Estas funciones son la **única** vía permitida para conversiones de frame. Cualquier inversión manual es candidata a bug.

## 7. Errores comunes a evitar

- **Pasar `q` directo a `Rotation.from_quat`.** Scipy usa x,y,z,w; el sistema usa w,x,y,z. Usar siempre la utilidad.
- **Asumir `frame="world"` sin chequear.** El campo `frame` del `Twist` es informativo y vinculante.
- **Mutar `state.nav.pose.position_enu_m`.** Es un array; aunque frozen no impide mutar el ndarray interno. Disciplina: tratar como inmutable.
- **Mezclar grados y radianes.** SI estricto en estructuras; conversiones solo en frontera config/UI.

## 8. Evolución futura

- Añadir `accel_world_mps2` opcional cuando el estimador lo proporcione.
- Añadir campo `frame_id` por defecto si se introduce soporte multi-cuerpo.
- En multi-robot (no en scope), `VehicleState.vehicle_id`.
- Versionado de `schema_version` documentado en `docs/specs/state_changelog.md` cuando exista cambio.
