# SPEC — Perception

- **Estado:** congelado en Fase 0
- **ADRs principales:** ADR-0008 (mecanismo), ADR-0009 (política), ADR-0010 (catálogo revisado + acoplamiento), ADR-0011 (vetos T0 sobre piloto)
- **Versión del contrato:** `PERCEPTION_PROTOCOL_VERSION = 1`

## 1. Responsabilidades

El módulo `perception/` es la única capa que **observa** el mundo y emite estimaciones derivadas de sensores. Sus responsabilidades:

- Consumir `SensorSample[T]` del HAL.
- Producir `Estimate[T]` con `validity`, `covariance`, `source` y `stamp_sim_ns` correctos (per `docs/specs/uncertainty.md`).
- Detectar y reportar transiciones de `PerceptionMode`.
- Mantener canales de telemetría `/perception/{producer_id}/*` y `/perception/mode`.

**No es responsabilidad de `perception/`:**

- Estimar el estado completo del vehículo (`state.aggregator`, EKF — ver `docs/specs/state.md`).
- Construir o consultar un mapa global (eso es SLAM en Fase 4).
- Decidir qué hace el dron ante degradación (ADR-0009 / `mission/`).
- Sintetizar comandos para actuadores (`actuators/`).

## 2. Productores perceptuales

Cada productor implementa el contrato `PerceptionProducer[T]` y vive en su propio módulo. Los productores de Fase 3–4 son:

```python
class PerceptionProducer(Protocol, Generic[T]):
    producer_id: str
    nominal_rate_hz: float
    nominal_covariance_envelope: np.ndarray
    max_age_ns: int

    def step(self, samples: Sequence[SensorSample[Any]], now_ns: int) -> Estimate[T] | None: ...
    def health(self) -> ProducerHealth: ...
```

| Producer | `producer_id` | Output | Tasa | Fase de aparición |
|---|---|---|---|---|
| Inercial preintegrada | `imu.preint` | `PreintegratedIMU` | 200 Hz | Fase 3 |
| Visual odometry frontal | `vo.front` | `Estimate[Pose]` (delta-pose) | 30 Hz | Fase 3 |
| Profundidad estéreo (si stereo presente) | `depth.stereo` | `Estimate[DepthMap]` | 15 Hz | Fase 4 |
| Altímetro fusionado | `altimeter.fused` | `Estimate[float]` (altitud AGL) | 50 Hz | Fase 3 |
| Detector de features | `features.fast` | `Estimate[FeatureSet]` | 30 Hz | Fase 3 |
| Loop closure | `slam.loop` | `Estimate[LoopHypothesis]` | event-driven | Fase 4 |
| Detector de luminancia | `light.luminance` | `Estimate[float]` | 5 Hz | Fase 3 |
| Detector de motion-aggressive | `motion.aggressive` | `Estimate[AggressiveMetric]` | 50 Hz | Fase 3 (añadido por ADR-0010) |

Cualquier productor nuevo debe declararse en este spec antes de añadir su implementación; producers no documentados están prohibidos en el bus.

## 3. Detección de modos perceptuales

La detección de `PerceptionMode` (ADR-0008 §3) se centraliza en `perception.mode_detector.PerceptionModeDetector`. Este componente:

- Suscribe a los canales de telemetría de cada productor (validity, métricas internas).
- Evalúa, con la cadencia de `nominal_hold_ms` (default 200 ms), las condiciones de entrada/salida de cada modo per `docs/specs/uncertainty.md` §7.
- Mantiene una FSM con las transiciones permitidas (§4).
- Publica `PerceptionModeChanged` en el bus al cambiar de modo.

El detector **no** decide comportamiento; solo nombra el modo. La política la consume `mission/` y `T2/T1` (ver `docs/specs/mission.md`).

## 4. Transiciones permitidas y endurecimiento de FSM

Las transiciones entre modos son una FSM dirigida. No todas las transiciones son legales; el detector las restringe para evitar oscilación y para forzar paso por estados intermedios.

```
                 ┌──────────────────────────────────────────┐
                 │                                          ▼
NOMINAL ───► LOW_TEXTURE ────────► VIO_LOST ────────► PERCEPTION_DEAD
   │            │                       │                    │
   │            ▼                       │                    │
   ├──► LOW_LIGHT ────────────────────┐ │                    │
   │            │                     ▼ ▼                    │
   ├──► IMU_SATURATION ──────────►  (cualquiera)             │
   │                                                          │
   ├──► MOTION_AGGRESSIVE ─► LOW_TEXTURE (degradación)        │
   │                                                          │
   └──► MAP_AMBIGUOUS ◄──────────────► NOMINAL                │
                                                              │
   NOMINAL ◄──── (cualquiera, tras recovery sostenido) ◄──────┘
```

### 4.1 Doble condición de transición (hold + K muestras)

Cada transición legal está gobernada por **dos condiciones simultáneas** que deben cumplirse:

- **Hold temporal:** la condición de entrada (o salida) del modo se sostiene durante `window_ms` (default `nominal_hold_ms = 200 ms`).
- **K muestras consecutivas:** la condición se cumple en al menos `k_consecutive` muestras seguidas del productor relevante, sin gap, sin alternancia. Defaults por modo en `docs/specs/uncertainty.md` §7.

Ambas condiciones operan en **conjunción**. Si la señal cruza el umbral cada 3 frames a 30 Hz, hold se cumple pero K no — la transición no dispara. Esto cierra el agujero de oscilación bajo señal realista identificado en `docs/reviews/uncertainty_red_team_review.md` §2.3.

### 4.2 Reglas adicionales

- De `NOMINAL` a cualquier degradado: doble condición debe cumplirse; default 200 ms + K muestras.
- De un modo degradado a `NOMINAL`: requiere paso por el modo padre menos restrictivo **y** doble condición sobre el envelope nominal (`nominal_hold_ms` + `nominal_k_consecutive`).
- `IMU_SATURATION`, `MOTION_AGGRESSIVE` y `PERCEPTION_DEAD` no pasan a `NOMINAL` en un solo paso; exigen `nominal_hold_ms × 2` (default 400 ms) **y** `nominal_k_consecutive` para evitar histeresis pobre.
- Transiciones a `PERCEPTION_DEAD` son siempre permitidas desde cualquier estado y bypasean la doble condición (input es la única consideración cuando la situación es crítica).
- Salir de `PERCEPTION_DEAD` exige `VALID` sostenido en **todos** los productores durante `nominal_hold_ms × 2` **y** `nominal_k_consecutive × 2`.
- Si `MOTION_AGGRESSIVE` persiste más allá de `aggressive_recovery_timeout_ms` (default 2000), el detector emite transición a `LOW_TEXTURE` por degradación sostenida (per ADR-0010 §1).

### 4.3 Garantía contra oscilación

El detector debe pasar el test `test_fsm_no_oscillation_under_alternating_signal` (especificado en `uncertainty.md` §11): una señal sintética alternante a frecuencia `0.45 / window_ms` no produce más de 2 transiciones por minuto. Cualquier configuración (override de `window_ms` o `k_consecutive`) que rompa esta garantía es rechazada en CI por test parametrizado.

## 5. Métricas mínimas por productor

Cada productor publica las siguientes métricas a `/perception/{producer_id}/metrics` a su tasa nominal. Son las que el detector consume y son obligatorias.

### 5.1 `vo.front`

- `feature_count: int` — features tracked en el último frame.
- `mean_track_length: float` — promedio de longitud de track sobre features activas.
- `innovation_norm: float` — norma de innovación del frame.
- `frames_since_last_keyframe: int`.
- `gate_pass: bool` — si el frame pasó el gate de innovación.

### 5.2 `imu.preint`

- `accel_axis_saturation: tuple[float, float, float]` — fracción de full scale por eje.
- `gyro_axis_saturation: tuple[float, float, float]`.
- `bias_drift_rate: float` — rate de cambio reciente del bias estimado.

### 5.3 `light.luminance`

- `mean_luminance: float ∈ [0, 1]`.
- `agc_gain_frac: float ∈ [0, 1]` — fracción de ganancia AGC en uso.
- `agc_saturated: bool`.

### 5.4 `slam.loop`

- `best_candidate_score: float`.
- `second_best_score: float`.
- `ambiguity_margin: float` — `(best − second) / max(best, eps)`.

### 5.5 `altimeter.fused`

- `agreement_residual_m: float` — desacuerdo entre fuentes de altitud (barómetro, ToF, GT).

### 5.6 `motion.aggressive` (añadido por ADR-0010)

- `commanded_rate_rps_max: float` — máximo absoluto entre ejes del comando de body rate recibido en la última ventana.
- `measured_accel_mps2_excl_g: float` — magnitud de aceleración medida en cuerpo excluyendo gravedad.
- `degraded_producers_in_window: tuple[str, ...]` — IDs de productores que reportaron `DEGRADED` o peor en la misma ventana (`vo.front`, `imu.preint`, etc.).
- `entry_condition_met: bool` — true cuando rate o accel exceden threshold **y** `len(degraded_producers_in_window) ≥ 1`.

Este productor es **derivado**: no consume sensores directamente, lee comandos del bus (`/cmd/*`) y telemetría de otros productores. Su latencia debe ser menor que `aggressive_window_ms / 4` para que el detector pueda actuar dentro del hold.

Productores futuros declaran sus métricas en este spec **antes** de añadirlas al detector.

## 6. Contratos vinculantes

1. **Sin GPS en `perception/`.** Productores que consumen GPS están deshabilitados por default en todos los scenarios (`docs/specs/sensors.md`); habilitarlos requiere flag scenario `enable_gps: true`. No hay productor `gps.*` por defecto en Fase 3+.
2. **Sin estado del vehículo.** Productores no consumen `VehicleState`. Toda la información viene de `SensorSample` y de su propio buffer interno.
3. **Determinismo.** Para un mismo seed y misma secuencia de `SensorSample`, todo productor genera la misma secuencia de `Estimate` bit-a-bit (ADR-0002). Aleatoriedad solo via `RandomSource.child(producer_id)`.
4. **Sealing de arrays.** Aplica regla de `core.uncertainty` (§3.2 de `uncertainty.md`).
5. **Sin asignación de modo.** Un productor reporta su `validity` y sus métricas; no decide el modo global. Eso lo hace `PerceptionModeDetector`.
6. **Telemetría completa.** Toda métrica de §5 que un productor expone es persistida en MCAP. Submuestreo opcional para canales pesados (ej. histogramas de features) documentado en `docs/specs/telemetry.md`.
7. **Latencia documentada.** Cada productor declara su latencia p50/p99 en su docstring y la mide; superar 2× el target documentado emite `WARN`.

## 7. Restricciones

- Prohibido importar `mission/` o `actuators/` desde `perception/`.
- Prohibido publicar `Estimate` con `source.kind == "groundtruth"` desde productores derivados de sensores; GT solo viene del backend de simulación.
- Prohibido `time.time()` o `time.monotonic()`; usar `SimClock` activo.
- Prohibido emitir `validity == VALID` cuando un criterio de §5 está fuera de envelope nominal del productor (sería contradicción con `uncertainty.md` §3.6).
- Prohibido fusionar productores **dentro** de `perception/`. La fusión vive en `state/` (EKF) y el resultado es un único `Estimate[NavigationState]` con `kind="fused"`.

## 8. Pruebas obligatorias

| Test | Cubre |
|---|---|
| `test_producer_outputs_estimate_only` | §6.1, §6.5 |
| `test_producer_deterministic_with_seed` | §6.3 |
| `test_mode_detector_transitions_obey_fsm` | §4 |
| `test_mode_detector_publishes_event_on_change` | §3, ADR-0008 §4 |
| `test_mode_detector_no_oscillation_under_hysteresis` | §4 (recovery time) |
| `test_low_texture_entry_at_threshold` | §3 + uncertainty.md §7 |
| `test_motion_aggressive_requires_command_and_degradation` | §5.6 + ADR-0010 §1 |
| `test_fsm_double_condition_blocks_oscillation` | §4.1 + §4.3 |
| `test_perception_does_not_import_mission_or_actuators` | §7 |
| `test_gps_producer_disabled_by_default` | §6.1 |

Cobertura objetivo del módulo `perception/`: > 85 %.

## 9. Lo que NO está en Fase 0 (pero el spec lo prepara)

- VO real: aparece en Fase 3 (T3 del research track U1–U6, ver `docs/roadmaps/research_track_uncertainty.md`).
- Loop closure y SLAM: Fase 4.
- Productores aprendidos (ML): solo como complemento opt-in en Fase 6+, dentro del mismo envelope `Estimate[T]`.
- Multi-cámara fusionada: no comprometido; sería un productor adicional documentado aquí cuando exista.
