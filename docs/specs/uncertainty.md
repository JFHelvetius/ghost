# SPEC — Uncertainty Model

- **Estado:** congelado en Fase 0
- **ADRs principales:** ADR-0008, ADR-0009, ADR-0010 (catálogo revisado y disciplina de acoplamiento de parámetros)
- **Versión del contrato:** `UNCERTAINTY_PROTOCOL_VERSION = 1`

## 1. Responsabilidades

Este documento es el contrato vinculante para todo lo relacionado con incertidumbre en Project Ghost. Define:

- Los tipos canónicos que envuelven cualquier estimación que cruce una frontera de módulo (`Estimate[T]`, `Validity`, `EstimateSource`).
- El catálogo de identificadores de modo de fallo (`PerceptionMode`) y sus criterios cuantitativos por defecto.
- Los modelos de **inflación de covarianza** que productores y estimadores deben aplicar al degradarse la entrada.
- Las reglas de composición cuando dos `Estimate` se combinan.
- Los helpers obligatorios en `core.uncertainty`.

**No es responsabilidad de este spec:**

- Decidir la respuesta conductual por modo (eso es ADR-0009).
- Implementar VO, EKF o SLAM (eso es Fase 3+).
- Elegir el algoritmo concreto de detección de fallo perceptual.

## 2. Tipos congelados

```python
class Validity(IntEnum):
    INVALID  = 0
    STALE    = 1
    DEGRADED = 2
    VALID    = 3
    # Orden total: VALID > DEGRADED > STALE > INVALID (mayor = mejor)

@dataclass(frozen=True)
class EstimateSource:
    module_id: str          # p.ej. "vo.front", "ekf.nav", "altimeter.gt"
    kind: Literal["sensor", "filter", "vo", "slam", "groundtruth", "fused"]
    schema_version: int

@dataclass(frozen=True)
class Estimate(Generic[T]):
    value: T
    covariance: np.ndarray | None
    validity: Validity
    stamp_sim_ns: int
    source: EstimateSource
    confidence: float | None = None
    # Invariantes verificados en __post_init__:
    #   - covariance is None  iff  source.kind == "groundtruth"
    #   - covariance, si existe, es 2-D, simétrica, dtype float64
    #   - validity == VALID exige covariance dentro de envelope nominal del producer

@dataclass(frozen=True)
class NavUncertainty:
    """Envelope adjunto a `NavigationState`."""
    validity: Validity
    pos_sigma_m: np.ndarray         # (3,) sigma marginal de posición ENU
    vel_sigma_mps: np.ndarray       # (3,) sigma marginal de velocidad
    att_sigma_rad: np.ndarray       # (3,) sigma marginal en tangente del cuaternión
    horizon_ns: int                 # horizonte hasta el cual estas sigmas son válidas
    age_ns: int                     # edad de la observación más antigua que contribuyó

class PerceptionMode(StrEnum):
    NOMINAL            = "nominal"
    LOW_TEXTURE        = "low_texture"
    LOW_LIGHT          = "low_light"
    IMU_SATURATION     = "imu_saturation"
    VIO_LOST           = "vio_lost"
    MAP_AMBIGUOUS      = "map_ambiguous"
    MOTION_AGGRESSIVE  = "motion_aggressive"   # añadido en ADR-0010
    PERCEPTION_DEAD    = "perception_dead"
```

Los nombres del enum `PerceptionMode` son **frozen**. Añadir o renombrar requiere ADR que enmiende o supersede ADR-0008 (ver ADR-0010 como ejemplo de enmienda al catálogo). Modos considerados y rechazados (DUST, WATER_DROP_ON_LENS, HORIZON_GLARE, THERMAL_SHIMMER, EM_INTERFERENCE, MULTIPATH_VIO) están documentados en ADR-0010 §2 con su razón de rechazo.

## 3. Contratos vinculantes

1. **Wrapping obligatorio.** Toda salida perceptual o de estimación que cruce una frontera de módulo es un `Estimate[T]`. Devolver `T` "pelado" está prohibido fuera de implementación interna del productor.
2. **Sealing recursivo de arrays.** El constructor de `Estimate` aplica `flags.writeable=False` no solo a `value` y `covariance` si son `np.ndarray`, sino también recursivamente a cualquier `np.ndarray` accesible por traversal de los campos de `value` cuando este es una dataclass (consistente con ADR-0005). Productores que envuelvan tipos compuestos (p.ej. `Estimate[Pose]`) deben tener constructor que selle internamente; el `Estimate` verifica el sealing tras construcción y rechaza con `ValueError` si encuentra un array escribible. Esta regla cierra el agujero de sealing superficial identificado en `docs/reviews/uncertainty_red_team_review.md` §3.2.
3. **Covarianza simétrica.** Toda matriz `covariance` cumple `‖C − Cᵀ‖_F / ‖C‖_F < 1e-9`. El constructor verifica y simetriza si la diferencia es menor que tolerancia; rechaza con `ValueError` si excede.
4. **Covarianza semidefinida positiva.** Toda matriz `covariance` cumple `min(eig(C)) ≥ -eps_psd` (con `eps_psd = 1e-12`). El constructor verifica; rechaza si falla.
5. **Stamp del productor.** `stamp_sim_ns` es el instante en que el productor terminó de producir, no el de consumo. El consumidor calcula `age_ns = now - stamp_sim_ns` y aplica §4 si es relevante.
6. **`validity == VALID` exige covarianza dentro de envelope nominal.** Cada productor declara su `nominal_covariance_envelope` en su spec/config; emitir `VALID` con covarianza fuera del envelope es bug.
7. **Sin upgrade silencioso.** En cualquier composición de `Estimate`, la `validity` de salida es el mínimo (más restrictivo) de las entradas. Solo un productor puede emitir un `VALID` original.
8. **Groundtruth tiene covariance None.** Por construcción `kind == "groundtruth"` implica `covariance is None`. Cualquier otro `kind` con `covariance is None` es bug. Esta asimetría hace explícito que GT no existe en hardware.
9. **`confidence` no reemplaza covarianza.** Si un productor solo expone `confidence`, debe traducirlo a una covarianza diagonal documentada antes de emitir `Estimate`.
10. **Validity y covariance son consistentes, no independientes.** El productor no puede emitir simultáneamente `validity == VALID` con covarianza inflada (fuera de envelope nominal), ni `validity == DEGRADED` con covarianza nominal. El constructor verifica la consistencia: dado el `validity` declarado y el `nominal_covariance_envelope` declarado por el productor (vía `EstimateSource.module_id`), la covarianza debe estar dentro del rango esperado para ese nivel de validez (nominal para `VALID`; inflada por §5 para `DEGRADED`/`STALE`). Inconsistencias rechazadas con `ValueError`. Esta regla cierra el agujero identificado en `docs/reviews/uncertainty_red_team_review.md` §3.1.

## 4. Reglas de envejecimiento (STALE)

Cada `EstimateSource` declara un `max_age_ns` aceptable para su canal. Reglas:

| Edad | Validity efectiva |
|---|---|
| `age ≤ max_age_ns` | sin cambio |
| `max_age_ns < age ≤ 3 · max_age_ns` | downgrade a `STALE`; aplicar inflación de §5.4 |
| `age > 3 · max_age_ns` | downgrade a `INVALID`; valor no usable |

Consumidores deben evaluar edad usando el `SimClock` activo, no `time.time()`.

## 5. Modelos de inflación de covarianza

Cuando un productor emite `validity in (DEGRADED, STALE)`, la covarianza no es la nominal: se **infla** según un modelo documentado. Los modelos por defecto son los siguientes; pueden ser sobreescritos por config pero no eliminados.

> **Estado de calibración de los valores numéricos de esta sección.** Todos los parámetros (`α`, factores direccionales, `Q_sat`, `Q_dr`) son **valores iniciales por ingeniería de orden de magnitud, no calibrados**. Vienen de literatura general de VIO/EKF y de intuición sobre PyBullet; no de un experimento. Se recalibran en U2 contra dataset PyBullet y en U6 contra hardware (ver `docs/roadmaps/research_track_uncertainty.md`). Hasta entonces, tratar cualquier número de esta sección como hipótesis. Cambios deben actualizar también los pares acoplados listados en ADR-0010 §3.

### 5.1 Inflación isotrópica (default para sensores escalares)

```
C_eff = (1 + α · severity)² · C_nominal,    severity ∈ [0, 1]
```

`severity` es producido por la lógica de detección (p.ej. `(min_features - features) / min_features`, clipado a `[0, 1]`). `α` es el factor de penalización, declarado por el productor; default `α = 2.0`.

### 5.2 Inflación direccional (default para VO/cámara)

VO degrada típicamente más en una dirección (la del eje óptico, o la dirección de menor textura). La inflación se aplica por eje:

```
C_eff = R · diag(s_x², s_y², s_z²) · Rᵀ · C_nominal · R · diag(s_x², s_y², s_z²) · Rᵀ
```

donde `R` es la rotación de cámara a mundo y `(s_x, s_y, s_z)` son factores de inflación por eje (default `(1.0, 1.0, 3.0)` para eje óptico hacia delante en FLU).

### 5.3 Inflación dinámica (default para IMU bajo saturación)

Si un eje IMU está saturado, la covarianza del bias correspondiente crece linealmente con el tiempo de saturación:

```
C_b(t) = C_b(0) + Q_sat · t_sat
```

con `Q_sat = diag(5e-2, 5e-2, 5e-2) (m/s²)² / s` para acelerómetro y `Q_sat = diag(5e-3, 5e-3, 5e-3) (rad/s)² / s` para giroscopio, hasta `validity` cae a `STALE`.

### 5.4 Inflación de stale (dead reckoning)

Para estimados marcados `STALE`, la covarianza crece con la edad según:

```
C_eff(age) = C_last + Q_dr · age_s²
```

donde `Q_dr` por canal está en `configs/uncertainty/dead_reckoning.yaml`. Defaults (sigma equivalente al final del horizonte `STALE`):

| Canal | `Q_dr` por eje |
|---|---|
| Posición ENU | `0.5 (m/s)²` |
| Velocidad | `0.2 (m/s²)²` |
| Cuaternión tangente | `0.01 (rad/s)²` |

Estos números son conservadores para PyBullet; en hardware se recalibran (ADR-0008 lo permite por config).

## 6. Reglas de composición

Dado `Estimate[A]` y `Estimate[B]` combinados en `Estimate[C]` (p.ej. fusión EKF, transformación entre marcos):

1. **Validity:** `out.validity = min(in_a.validity, in_b.validity)`.
2. **Source:** `out.source.kind = "fused"`; `out.source.module_id` identifica al fusor; `out.source.schema_version` es el del fusor, no el de los inputs.
3. **Stamp:** `out.stamp_sim_ns = max(in_a.stamp_sim_ns, in_b.stamp_sim_ns)`.
4. **Covarianza:** computada por el método del fusor (Kalman update, transformación lineal con jacobiana, etc.). Si cualquier input es `DEGRADED` o `STALE`, la covarianza del input correspondiente debe estar ya inflada según §5 antes de la composición.
5. **Confidence:** si ambos inputs lo proveen, se compone como producto; si solo uno lo provee, se descarta del output.

Composición con un `Estimate.validity == INVALID` es bug; debe detectarse y manejarse como fallo perceptual antes de invocar al fusor.

## 7. Catálogo de modos perceptuales — thresholds por defecto

Los nombres del catálogo están frozen en ADR-0008 y enmendados en ADR-0010 (8 modos). Los thresholds son defaults aplicados cuando una config no los sobreescribe. Esta tabla es la **única** fuente autoritativa para los defaults; configs scenario-específicas heredan estos valores cuando no los redefinen.

> **Estado de calibración:** mismo disclaimer que §5. Todos los valores son hipótesis iniciales; calibración real es responsabilidad de U2/U6. Cualquier ajuste debe respetar la **disciplina de acoplamiento** de ADR-0010 §3 (mecanismo↔policy en revisión conjunta).

> **Doble condición de transición FSM.** Cada modo declara dos parámetros que actúan **conjuntamente** para gobernar las transiciones: `window_ms` (hold temporal) y `k_consecutive` (número de muestras consecutivas dentro del envelope). Ambos deben cumplirse antes de declarar el modo activo o liberado. Esta doble condición cierra el agujero de oscilación bajo señal realista identificado en `docs/reviews/uncertainty_red_team_review.md` §2.3 y en `docs/specs/perception.md` §4. Detalles operativos de cómo el `PerceptionModeDetector` aplica esta regla viven en `perception.md` §4.

```yaml
perception_mode_defaults:
  nominal_hold_ms: 200
  nominal_k_consecutive: 6              # muestras seguidas dentro de envelope
  low_texture:
    min_features: 30
    low_texture_window_ms: 500
    low_texture_k_consecutive: 8
    min_track_length: 5
    severity_alpha: 2.0
  low_light:
    min_luminance: 0.05
    low_light_window_ms: 1000
    low_light_k_consecutive: 4
    agc_at_max_gain_required: true      # criterio original
    agc_at_min_gain_required: true      # añadido vía ADR-0010 §2 (subsume HORIZON_GLARE)
    recovery_timeout_ms: 5000
    slow_ascend_mps: 0.3
    recovery_altitude_m: 2.0
  imu_saturation:
    saturation_threshold_frac: 0.90
    saturation_window_ms: 50
    saturation_k_consecutive: 3
    recovery_threshold_frac: 0.70
    kill_threshold_ms: 1000
  vio_lost:
    innovation_fail_count: 5
    vio_timeout_ms: 200
    vio_lost_k_consecutive: 5            # equivalente al innovation_fail_count para el detector
    dr_hover_window_ms: 3000
    dr_abort_covariance_pos_m: 5.0
  map_ambiguous:
    ambiguity_margin: 0.10
    ambiguity_window_ms: 500
    ambiguity_k_consecutive: 5
  motion_aggressive:                     # añadido por ADR-0010 §1
    aggressive_rate_threshold_rps: 3.0
    aggressive_accel_threshold_mps2: 12.0
    aggressive_window_ms: 200
    aggressive_k_consecutive: 4
    aggressive_recovery_timeout_ms: 2000
    cap_factor: 0.6                      # cap aplicado por T2; acoplado con threshold (ADR-0010 §3)
  perception_dead:
    descent_mps: 0.5
    kill_altitude_m: 0.3
    dead_k_consecutive: 4                # productores en INVALID consecutivo
```

## 8. Helpers obligatorios en `core.uncertainty`

```python
def make_estimate(
    value: T,
    *,
    covariance: np.ndarray | None,
    validity: Validity,
    stamp_sim_ns: int,
    source: EstimateSource,
    confidence: float | None = None,
) -> Estimate[T]:
    """Construye `Estimate[T]` aplicando sealing, simetrización y validaciones de §3."""

def inflate_isotropic(C: np.ndarray, severity: float, alpha: float = 2.0) -> np.ndarray: ...
def inflate_directional(C: np.ndarray, R_cam_world: np.ndarray, scales: np.ndarray) -> np.ndarray: ...
def inflate_stale(C: np.ndarray, age_ns: int, Q_dr: np.ndarray) -> np.ndarray: ...
def compose_validity(*validities: Validity) -> Validity:  # min over inputs
def age_ns(estimate: Estimate[T], now_ns: int) -> int: ...
def downgrade_by_age(estimate: Estimate[T], now_ns: int, max_age_ns: int) -> Estimate[T]: ...
```

Toda implementación de estimador o productor consume estos helpers; reimplementar localmente es violación de spec.

## 9. Telemetría obligatoria

- Canal `/perception/mode`: `PerceptionModeChanged` event en cada transición, con `from`, `to`, `reason` (cadena humana), `producer_ids` (qué productores contribuyeron), `stamp_sim_ns`.
- Canal `/nav/uncertainty`: muestreo de `NavUncertainty` a la misma tasa que `/state/nav` (50 Hz). Persistido en MCAP.
- Canal `/perception/{producer_id}/validity`: serie temporal de `Validity` por productor; muestreado a la tasa nominal del productor.

Estos canales son obligatorios desde Fase 3 (cuando aparecen estimadores reales); en Fases 1–2 quedan declarados pero vacíos.

## 10. Restricciones

- Prohibido emitir `Estimate.validity == VALID` con `covariance == None` salvo `source.kind == "groundtruth"`.
- Prohibido pasar `np.random` global como fuente de ruido a cualquier productor (ADR-0002). Toda aleatoriedad viene de `RandomSource.child(...)`.
- Prohibido modificar la enumeración `PerceptionMode` sin ADR que enmiende o supersede ADR-0008 (precedente: ADR-0010).
- Prohibido `time.time()` o `time.monotonic()` en lógica de envejecimiento. Solo `SimClock`/`SystemClock` activos.
- Consumidores no pueden inferir `validity` por inspección del valor; deben leer `estimate.validity`.
- Prohibido el uso de colecciones con orden de iteración inestable (`set`, `frozenset`, `dict.keys()` sin ordenar explícitamente, `collections.Counter`) dentro de productores en `perception/`, fusores en `state/`, y planners en `mission/`. El linter `scripts/check_no_unstable_collections.py` (a implementar en U1; especificación en este §) verifica la regla en CI y pre-commit. Mitiga el riesgo identificado en `docs/reviews/uncertainty_red_team_review.md` §3.3 sobre determinismo de RANSAC y similares; no lo elimina (algoritmos como RANSAC pueden romper determinismo por razones fuera del alcance del linter), pero cierra la mayor parte de la superficie. Excepciones por archivo con `# noqa: stable-collection` y razón en comentario, revisable en code review.
- Prohibido modificar un parámetro listado en ADR-0010 §3 (parámetros acoplados mecanismo↔policy) sin actualizar o justificar explícitamente el parámetro acoplado en el mismo PR.

## 11. Pruebas obligatorias

| Test | Cubre |
|---|---|
| `test_estimate_rejects_asymmetric_covariance` | §3.3 |
| `test_estimate_rejects_non_psd_covariance` | §3.4 |
| `test_estimate_seals_arrays_recursively` | §3.2 (sealing recursivo sobre dataclasses anidadas) |
| `test_estimate_rejects_validity_covariance_inconsistency` | §3.10 (VALID con covarianza inflada, DEGRADED con nominal) |
| `test_groundtruth_iff_covariance_none` | §3.8 |
| `test_compose_validity_is_min` | §6.1 |
| `test_stale_inflation_monotonic_in_age` | §5.4 |
| `test_isotropic_inflation_recovers_nominal_at_zero_severity` | §5.1 |
| `test_downgrade_by_age_thresholds` | §4 |
| `test_perception_mode_change_event_published` | §9 |
| `test_no_global_random_in_producers` | §10 + scripts/check_no_global_random.py |
| `test_no_unstable_collections_in_perception_state_mission` | §10 + scripts/check_no_unstable_collections.py |
| `test_motion_aggressive_entry_at_threshold` | ADR-0010 §1 + §7 |
| `test_fsm_no_oscillation_under_alternating_signal` | §7 + perception.md §4; señal sintética alternante a 0.45 × window_ms no produce más de 2 transiciones por minuto |

Cobertura objetivo del módulo `core.uncertainty`: > 90 %.
