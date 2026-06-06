# SPEC — Mission Layer

- **Estado:** congelado en Fase 0 (interfaces y obligaciones)
- **ADRs principales:** ADR-0009 (especialmente §3 — uncertainty-aware planning)
- **Versión del contrato:** `MISSION_PROTOCOL_VERSION = 1`
- **Implementación:** desde Fase 5; el contrato debe estar fijado antes para que las fases anteriores no acumulen suposiciones implícitas.

## 1. Responsabilidades

El módulo `mission/` decide **qué** debe hacer el vehículo dado el `VehicleState` actual, el `PerceptionMode` activo y los goals declarados por el operador. Sus responsabilidades:

- Mantener una **mission specification** (`MissionSpec`) cargada desde config.
- Generar y mantener un plan de goals (`MissionPlan`) consistente con la `MissionSpec` y con el `PerceptionMode` actual.
- Exponer la goal activa al **deliberative layer (T3)** o, ante degradación, ceder autoridad a T2 según ADR-0009.
- Razonar explícitamente sobre la incertidumbre: planes son rechazados si violan un `uncertainty_budget` declarado.
- Publicar telemetría de progreso y de decisiones de planning.

**No es responsabilidad de `mission/`:**

- Implementar VO, EKF o SLAM (Fase 3–4).
- Generar trayectorias suaves o comandos de bajo nivel (`control/`, `actuators/`).
- Detectar el `PerceptionMode` (eso es `perception.mode_detector`).
- Decidir comportamiento reactivo per `PerceptionMode` (ADR-0009 §2; lo aplica T2).
- Forzar invariantes de safety (T0, ver `docs/specs/actuators.md`).

## 2. Tipos congelados

```python
class GoalKind(StrEnum):
    WAYPOINT          = "waypoint"
    AREA_COVERAGE     = "area_coverage"
    EXPLORE_FRONTIER  = "explore_frontier"
    ACTIVE_PERCEPTION = "active_perception"  # yaw scan, ascent, revisit landmark
    RETURN_HOME       = "return_home"
    LAND              = "land"

@dataclass(frozen=True)
class UncertaintyBudget:
    max_pos_sigma_m: float          # sigma máxima tolerada de posición ENU
    max_blind_segment_m: float      # longitud máxima de tramo con validity < VALID
    min_validity: Validity          # validity mínima exigida durante el goal
    horizon_ns: int                 # horizonte temporal del presupuesto

@dataclass(frozen=True)
class Goal:
    goal_id: str
    kind: GoalKind
    params: Mapping[str, Any]       # ej. {"target_enu_m": [x, y, z]} para WAYPOINT
    uncertainty_budget: UncertaintyBudget
    parent_goal_id: str | None = None  # set para sub-goals de ACTIVE_PERCEPTION

@dataclass(frozen=True)
class MissionSpec:
    mission_id: str
    goals: tuple[Goal, ...]         # orden lógico declarado por el operador
    default_budget: UncertaintyBudget
    home_enu_m: np.ndarray          # (3,)
    geofence_polygon: np.ndarray | None  # (N, 2)

@dataclass(frozen=True)
class MissionPlan:
    plan_id: str
    spec: MissionSpec
    sequence: tuple[Goal, ...]      # incluye sub-goals insertados por el planner
    rationale: str                  # texto humano de por qué este orden
    schema_version: int = 1

@dataclass(frozen=True)
class MissionStatus:
    plan_id: str | None
    active_goal_id: str | None
    active_tier: Literal["T0", "T1", "T2", "T3"]
    progress_frac: float            # [0, 1] del goal activo
    budget_remaining: UncertaintyBudget | None
    last_replan_reason: str | None
    last_replan_stamp_ns: int | None
```

## 3. Contratos vinculantes

1. **Plan = función pura del state observado.** Dado el mismo `MissionSpec`, mismo `VehicleState` snapshot, mismo `PerceptionMode` y mismo seed, el planner produce el mismo `MissionPlan`. Aleatoriedad solo via `RandomSource.child("mission.planner")`.
2. **Presupuesto explícito por goal.** Ningún goal entra al plan sin un `UncertaintyBudget` resuelto (heredado de `MissionSpec.default_budget` si no se sobreescribe).
3. **Rechazo de planes que violen el presupuesto.** Si la simulación forward del plan predice un tramo de longitud > `max_blind_segment_m` con `validity < min_validity`, el plan se rechaza y el planner inserta un sub-goal `ACTIVE_PERCEPTION` antes de re-evaluar.
4. **Sub-goals de active perception.** Cuando un goal requiere reducir incertidumbre antes de progresar (paso por área texturada, revisita de landmark conocido, ascenso lento para reorientar), el planner inserta un `Goal(kind=ACTIVE_PERCEPTION, parent_goal_id=...)`. El sub-goal debe completarse antes de retomar el padre.
5. **Cesión de autoridad bajo degradación.** Cuando el `PerceptionMode` activo deja de ser `NOMINAL`, `mission/` deja de emitir nuevos goals y publica `AUTHORITY_YIELDED` con `to_tier="T2"`. T2 ejecuta el behavior del modo (ADR-0009 §2). `mission/` no reasume hasta que el modo vuelva a `NOMINAL` y T2 reporte `AUTHORITY_RELEASED`.
6. **Replan provoca evento.** Toda decisión de replanificar publica `MISSION_REPLAN` con `reason ∈ {budget_exceeded, mode_change, new_information, operator_request, goal_unreachable}`. Replans silenciosos son bug.
7. **Geofence respetada en planning.** Todo waypoint y todo tramo del plan vive estrictamente dentro de `geofence_polygon`. Geofence ausente en scenarios distintos de `empty_room` es violación de spec.
8. **`MissionStatus` siempre publicado.** A 10 Hz en `/mission/status`. Persistido en MCAP.
9. **No control de bajo nivel.** El planner emite metas; no emite `ActuatorCommand`. La conversión goal→trayectoria→comando vive en `control/` y `actuators/`.

## 4. Modelo de incertidumbre forward

Para evaluar el presupuesto, el planner mantiene un modelo simplificado de evolución de incertidumbre a lo largo del plan. Reglas:

> **Estado de calibración:** el `k_vio` y las constantes de §4.2–§4.4 son hipótesis iniciales; calibración por escenario es responsabilidad de U3 y U5 (ver `docs/roadmaps/research_track_uncertainty.md`). El proxy es **estructuralmente sesgado hacia el optimismo** en escenas adversariales (ver `uncertainty_red_team_review.md` §2.4); por eso esta sección impone un factor de pesimismo escenario-específico (§4.5) que el planner aplica obligatoriamente cuando opera sobre escenas no caracterizadas.

### 4.1 Crecimiento nominal

Dado un tramo de longitud `L` con `validity == VALID`, la posición sigma esperada al final del tramo es:

```
σ_pos_end² = σ_pos_start² + (k_vio_eff · L)²
```

con `k_vio_eff = k_vio_nominal · pessimism_factor` (ver §4.5). `k_vio_nominal = 0.005 m/m` por defecto, conservador de VO ideal sobre escena texturada. El parámetro vive en `configs/mission/uncertainty_forward.yaml`.

### 4.2 Crecimiento bajo degradación

Para tramos con `validity == DEGRADED`, se aplica la inflación dirigida de `uncertainty.md` §5.2 sobre el `k_vio` efectivo, con factores por defecto `(1.0, 1.0, 3.0)` FLU.

### 4.3 Tramos `STALE`

Si el plan exige avanzar bajo `STALE` (dead reckoning), el crecimiento se rige por `uncertainty.md` §5.4. El planner usa `Q_dr.position` para predecir sigma final del tramo y verificar el presupuesto.

### 4.4 Recuperación tras `ACTIVE_PERCEPTION`

Tras completar un sub-goal `ACTIVE_PERCEPTION` exitoso, la sigma se resetea a la nominal del productor responsable (typically VO + loop closure). Si el sub-goal falla, la sigma no se resetea y el planner reevalúa el padre.

### 4.5 Factor de pesimismo escenario-específico

El proxy forward de §4.1–§4.4 modela VO ideal. En escenas adversariales (textura pobre, repetición visual, transiciones luz–sombra) el crecimiento real de sigma es altamente no-lineal y el modelo lineal subestima. Para mitigar el sesgo optimista, el planner aplica un `pessimism_factor` multiplicativo sobre `k_vio_nominal` que depende del nivel de caracterización de la escena:

| Estado de caracterización | `pessimism_factor` |
|---|---|
| Escena con perfil de textura caracterizado en `registries/scene_profiles.yaml` (poblado por U3/U5) | 1.0 |
| Escena con caracterización parcial (algunos sub-tramos sí, otros no) | 1.5 sobre los sub-tramos no caracterizados |
| Escena no caracterizada (default para mundo nuevo) | 2.0 |
| Escena marcada explícitamente como adversarial en config | 3.0 |

Reglas de aplicación:

- El default es **escena no caracterizada** (factor 2.0). El planner solo aplica 1.0 cuando puede asociar el tramo evaluado a un perfil del registro.
- El `pessimism_factor` se aplica solo al término `k_vio`, no a las inflaciones de §4.2–§4.4 (que ya tienen su propia justificación).
- El `pessimism_factor` se reporta en `MissionStatus.budget_remaining` para que el operador entienda por qué un plan fue rechazado.
- Inflar `pessimism_factor` por encima de 3.0 (o introducir un valor nuevo) requiere actualizar este §4.5 y revisar si el modo `MAP_AMBIGUOUS` o `LOW_TEXTURE` debe disparar antes.

El registro `registries/scene_profiles.yaml` se puebla durante U3 (escenas sintéticas controladas) y U5 (escenas adversariales con benchmarks). Hasta que existan entradas allí, **todos los escenarios usan factor 2.0** por construcción. Esto cierra (en docs) el riesgo identificado en `uncertainty_red_team_review.md` §2.4; la calibración real del factor es deuda explícita de U3.

Estos modelos son **proxies**, no estimadores. Su único uso es scoring de planes en tiempo de planning. El estimador real (EKF/VIO en runtime) es la fuente autoritativa de sigma observado.

## 5. Replanning — disparadores

El planner replanifica cuando, y solo cuando:

| Disparador | Detección |
|---|---|
| `budget_exceeded` | sigma observada de `NavUncertainty` excede `active_goal.uncertainty_budget.max_pos_sigma_m` durante > `budget_violation_ms` (default 1000 ms). |
| `mode_change` | `PerceptionModeChanged` recibido y nuevo modo no es `NOMINAL`. En realidad esto cede autoridad (§3.5); el replan ocurre al retornar a `NOMINAL`. |
| `new_information` | Loop closure aceptado modifica posición esperada > `new_info_threshold_m` (default 1.0 m). |
| `operator_request` | Operador externo publica `MISSION_REPLAN_REQUEST` en el bus. |
| `goal_unreachable` | Forward simulation indica que el goal activo no puede cumplirse dentro del horizonte sin violar geofence o budget. |

Cualquier otro motivo de replan es bug; el planner debe emitir el evento con `reason` exactamente del enum anterior.

## 6. Interfaz entre `mission/` y otros módulos

| Consume de | Qué |
|---|---|
| `state/` | `VehicleState` y `NavUncertainty` actuales |
| `perception.mode_detector` | `PerceptionMode` activo, eventos de cambio |
| `events/` | `MISSION_REPLAN_REQUEST`, `OPERATOR_*` |
| `core.clock` | `now_ns()` para timestamps y horizontes |

| Publica a | Qué |
|---|---|
| `/mission/status` | `MissionStatus` a 10 Hz |
| `/mission/plan` | `MissionPlan` actual en cada cambio |
| `/mission/active_goal` | `Goal` activo en cada cambio |
| `events/` | `MISSION_REPLAN`, `AUTHORITY_YIELDED`, `AUTHORITY_RELEASED`, `GOAL_STARTED`, `GOAL_COMPLETED`, `GOAL_ABORTED` |
| `control/` (consumer) | El goal activo es leído por `control/` para sintetizar trayectoria; `mission/` no llama a `control/` directamente. |

## 7. Restricciones

- Prohibido importar `actuators/` o backends de simulación desde `mission/`.
- Prohibido modificar `VehicleState` o `NavUncertainty`; son inputs read-only.
- Prohibido emitir comandos de bajo nivel desde el planner.
- Prohibido replans sin evento — debe haber `MISSION_REPLAN` con `reason` válida.
- Prohibido `ACTIVE_PERCEPTION` sub-goals sin `parent_goal_id` correcto.
- Prohibido planning con goals que no estén en `MissionSpec.goals` o derivados como `ACTIVE_PERCEPTION` sub-goals.

## 8. Pruebas obligatorias

| Test | Cubre |
|---|---|
| `test_planner_deterministic_with_seed` | §3.1 |
| `test_plan_rejects_excess_blind_segment` | §3.3, §4 |
| `test_planner_inserts_active_perception_subgoal` | §3.4 |
| `test_authority_yielded_on_mode_change` | §3.5 |
| `test_replan_only_with_named_reason` | §3.6, §5 |
| `test_geofence_violation_rejected_in_plan` | §3.7 |
| `test_mission_status_published_at_10hz` | §3.8 |
| `test_forward_uncertainty_growth_monotonic_in_length` | §4.1 |
| `test_stale_forward_growth_uses_dead_reckoning_Q` | §4.3 |
| `test_pessimism_factor_defaults_to_2_for_uncharacterized_scene` | §4.5 |
| `test_pessimism_factor_reported_in_mission_status` | §4.5 |

Cobertura objetivo del módulo `mission/`: > 85 % a partir de Fase 5.

## 9. Lo que NO está en este spec

- Algoritmos concretos de planning (A*, RRT*, MPC al nivel de mission). Se eligen en Fase 5 con ADR específico.
- Política de retries cuando `ACTIVE_PERCEPTION` falla repetidamente — se aborta a `RETURN_HOME` o `LAND` según `MissionSpec.fallback_policy`, definido en una ADR posterior.
- Interacción multi-misión (varias misiones encoladas) — no comprometido.
- Coordinación multi-vehículo — fuera del scope del proyecto en su forma actual.

## 10. Compatibilidad con Fases tempranas

En Fases 1–4, `mission/` está **inactivo**:

- `MissionStatus.active_tier` reporta `"T2"` (manual) o `"T1"` (passthrough).
- `MissionPlan` es `None`; `MissionStatus.plan_id is None`.
- El canal `/mission/status` se mantiene para preservar el esquema en replay, con campos None/0.0.

Esta presencia esquelética garantiza que los logs de Fase 1 son compatibles con los lectores que se construyan en Fase 5.
