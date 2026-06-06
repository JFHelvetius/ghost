# SPEC — Sensor API

- **Estado:** congelado en Fase 0

## 1. Responsabilidades

- Definir el formato canónico de muestra sensórica: `SensorSample[T]`.
- Definir payloads específicos por tipo de sensor.
- Establecer las reglas de timestamping, sincronización y reporte de salud.

**No es responsabilidad del Sensor API:**

- Sincronizar sensores entre sí (eso es responsabilidad del consumidor: estimador).
- Filtrar, procesar o re-muestrear (eso es percepción / estimación).
- Conocer la dinámica del vehículo.

## 2. Estructura común

```python
class SensorHealth(IntEnum):
    OK = 0
    DEGRADED = 1
    FAULTY = 2
    OFFLINE = 3

@dataclass(frozen=True)
class SensorMeta:
    frame_id: str
    calibration_id: str | None      # referencia a `configs/calibration/<id>.yaml`
    extensions: Mapping[str, Any]

@dataclass(frozen=True)
class SensorSample(Generic[T]):
    sensor_id: SensorId             # str estable, p.ej. "imu0", "cam_front"
    seq: int                        # monotónico por sensor
    stamp_sensor_ns: int            # reloj del sensor (puede driftear)
    stamp_sim_ns: int               # reloj de simulación al publicar
    stamp_wall_ns: int              # reloj de pared (debug)
    health: SensorHealth
    payload: T
    meta: SensorMeta
    schema_version: int = 1

@dataclass(frozen=True)
class SensorSpec:
    sensor_id: SensorId
    payload_type: str               # "imu" | "rgb" | "depth" | "gps" | "altimeter" | ...
    nominal_rate_hz: float
    frame_id: str
    noise_model: NoiseModel | None
    latency_ns: int = 0
```

## 3. Payloads específicos

### 3.1 IMU

```python
@dataclass(frozen=True)
class IMUPayload:
    accel_mps2: np.ndarray          # (3,) float64, FLU body
    gyro_rps: np.ndarray            # (3,) float64, FLU body
    temperature_c: float | None
```

- Rate por defecto: 200 Hz. Mínimo aceptable: 100 Hz.
- Frame: cuerpo FLU.
- Ruido modelado por `NoiseModel.imu`: bias estable + bias random walk + ruido blanco gaussiano, ambos en accel y gyro.

### 3.2 Cámara RGB

```python
@dataclass(frozen=True)
class CameraIntrinsics:
    width: int; height: int
    fx: float; fy: float
    cx: float; cy: float
    distortion_model: Literal["none", "plumb_bob", "equidistant"]
    distortion_coeffs: np.ndarray   # variable según modelo

@dataclass(frozen=True)
class RGBImagePayload:
    image: np.ndarray               # (H, W, 3) uint8, sRGB
    intrinsics: CameraIntrinsics
    exposure_ns: int
    encoding: Literal["rgb8"]
```

- Rate por defecto: 30 Hz. Mínimo aceptable: 10 Hz.
- Sin ruido en Fase 1; se introduce en Fase 3 (motion blur, exposure, dropout).
- Frame: cuerpo, pero el campo `meta.frame_id` debe indicar el frame específico de la cámara (`cam_front`), no el cuerpo entero.

### 3.3 Cámara de profundidad

```python
@dataclass(frozen=True)
class DepthImagePayload:
    depth_m: np.ndarray             # (H, W) float32, metros, NaN = inválido
    intrinsics: CameraIntrinsics
    min_range_m: float
    max_range_m: float
```

- Rate por defecto: 15 Hz. Mínimo aceptable: 5 Hz.
- `NaN` reservado para píxeles inválidos. Consumidores deben manejar NaN.

### 3.4 GPS (presente pero no consumido por navegación; ver ADR-0000)

```python
class GpsFix(IntEnum):
    NO_FIX = 0; FIX_2D = 1; FIX_3D = 2; RTK = 3

@dataclass(frozen=True)
class GpsPayload:
    lat_deg: float; lon_deg: float; alt_m: float
    enu_local_m: np.ndarray         # (3,) en marco local del mundo
    fix_type: GpsFix
    hacc_m: float; vacc_m: float
```

- Rate por defecto: 5 Hz.
- **Política:** el estimador de navegación principal **no** consume `GpsPayload`. Solo se usa en evaluación y como groundtruth opcional cuando esté disponible.

### 3.5 Altímetro

```python
@dataclass(frozen=True)
class AltimeterPayload:
    altitude_m: float
    reference: Literal["AMSL", "AGL", "LOCAL"]
    variance_m2: float
```

- Rate por defecto: 50 Hz.

### 3.6 Sensores futuros

Cada tipo nuevo:

1. Define su `Payload` dataclass en `ghost.hal.messages.<tipo>`.
2. Registra el `payload_type` string en una tabla central.
3. No modifica payloads existentes.

Previstos: LiDAR (PointCloudPayload), magnetómetro, barómetro, optical flow, event camera.

## 4. Frecuencias

Configuradas, no hardcodeadas. Reside en `configs/vehicles/<name>.yaml`. Defaults razonables tabulados en `docs/architecture.md`.

Cada `SensorProvider` publica independientemente a su rate. **El sistema no asume sincronía entre sensores.**

## 5. Timestamps y sincronización

Tres relojes por muestra:

- **`stamp_sensor_ns`** — tiempo según el sensor; en sim ideal coincide con `stamp_sim_ns`, pero `NoiseModel.clock_drift_ppm` puede simular deriva.
- **`stamp_sim_ns`** — tiempo de simulación en el momento de publicación.
- **`stamp_wall_ns`** — tiempo de pared del proceso (debug, no se usa para algoritmos).

Sincronización entre sensores es **responsabilidad del consumidor**, típicamente el estimador. El HAL no alinea ni interpola.

Latencia: modelada como retraso entre captura y publicación. Documentada en `SensorSpec.latency_ns`.

## 6. Gestión de errores

| Situación | Manifestación |
|---|---|
| Sensor desconectado / no disponible | `health=OFFLINE`; `poll()` retorna `[]` |
| Lectura corrupta (NaN inesperado, valor fuera de rango) | Muestra publicada con `health=FAULTY` y `meta.extensions["error"]` describiendo |
| Sobrecarga / drop interno | Salto en `seq`; el consumidor detecta por gap |
| Calibración faltante | `meta.calibration_id = None`; consumidor decide |
| Excepción interna del backend | Encapsulada en `health=FAULTY` + evento `SENSOR_FAULT` en `/events` |

**Regla:** un sensor que falla nunca debe tumbar el bucle de control.

## 7. Casos de uso

### 7.1 Pulling determinista

```python
provider = backend.sensors()["imu0"]
samples = provider.poll()           # cero o más muestras desde el último poll
for s in samples:
    bus.publish(f"/sensors/{s.sensor_id}", s)
```

### 7.2 Suscripción push (Fase 2+)

```python
sub = backend.sensors()["imu0"].subscribe(
    lambda s: estimator.handle_imu(s)
)
# ... más tarde
sub.unsubscribe()
```

### 7.3 Detección de gap

```python
last_seq[sid] = -1
for s in samples:
    if last_seq[sid] >= 0 and s.seq != last_seq[sid] + 1:
        events.publish(Event(type=EventType.SENSOR_FAULT,
                             severity=EventSeverity.WARN,
                             payload={"sensor_id": sid,
                                      "expected": last_seq[sid]+1,
                                      "got": s.seq}))
    last_seq[sid] = s.seq
```

## 8. Errores comunes a evitar

- **Comparar `stamp_sensor_ns` entre sensores distintos** asumiendo igualdad. Cada sensor tiene su propio reloj.
- **Asumir rate fijo** y derivar `dt` de él. Usar la diferencia real entre `stamp_sim_ns`.
- **Modificar el `np.ndarray` interno** del payload. Es frozen lógicamente.
- **Lanzar excepciones desde el proveedor.** Reportar via health.

## 9. Evolución futura

- Compresión nativa de imagen en payload (campo `encoding="jpeg"`) para Fase 4+.
- Sincronización hardware en HW real: `stamp_sensor_ns` proviene de PTP/timestamping de cámara con IMU.
- Esquema extendido para sensores de evento (event-based cameras) que no son frame-rate.
