# ADR-0026 — Closed-Loop Feedback v1

## Status
Accepted (2026-06-08).

## Context

Las ADRs 0019-0025 produjeron contratos ortogonales que se apilan
limpiamente: belief, self-assessment, decision, decision-trace, action,
forward-prediction, prediction-outcome. **Hasta aquí, ningún contrato
COMPOSE con otro.** Cada uno es self-contained y se puede emitir,
persistir y auditar sin tocar los demás.

Eso era correcto durante el ramp-up — minimiza acoplamiento mientras
las shapes se estabilizan. Pero la cláusula central de la misión
("saber cuándo no se sabe y actuar en consecuencia") requiere que el
agente APRENDA de sus errores entre ciclos. Sin feedback, cada
`BeliefSelfAssessment` es independiente del anterior; un agente que
emitió cinco veces seguidas `predicted_std=0.01m` y observó
`error=0.5m` cinco veces sigue declarándose KNOWN en el siguiente
ciclo. La auditoría existe en MCAP pero **el agente mismo no la usa**.

ADR-0026 cierra ese gap con la primera **composición** explícita: el
stream de `PredictionOutcome` (ADR-0025) influye el siguiente
`BeliefSelfAssessment` (ADR-0020). El contrato preserva la inmutabilidad
del assessment crudo y añade un envelope que carga la evidencia +
el nivel ajustado + el policy identifier. La adjustment policy es
una pure function que un humano puede inspeccionar y un test puede
verificar.

## Decision

Añadir el paquete `project_ghost.core.feedback` con cinco contratos
puros + un wiring mínimo de telemetría. Stdlib only. Cero nuevas
dependencias.

### 1. `CalibrationHistory` (frozen dataclass)

Snapshot agregado de evidencia derivada de `PredictionOutcome` recientes:

```python
outcomes_considered: int                       # N total, >= 0
count_within_1_std: int                        # >= 0
count_beyond_1_std: int                        # >= 0
count_beyond_3_std: int                        # >= 0
count_beyond_5_std: int                        # >= 0
worst_position_mahalanobis: float              # >= 0, +inf legítimo
worst_orientation_mahalanobis: float           # >= 0, +inf legítimo
most_recent_observed_stamp_sim_ns: int | None  # None sii outcomes_considered == 0
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- Todos los counts `>= 0`.
- `sum(counts) == outcomes_considered`. Sin esa identidad el snapshot
  no es interpretable.
- `worst_position_mahalanobis` y `worst_orientation_mahalanobis`:
  `>= 0`, no-NaN, `+inf` legítimo (consistencia con ADR-0025).
- Cuando `outcomes_considered == 0`, ambos worst son `0.0` y stamp es
  `None`. Cuando `> 0`, stamp es `>= 0`.

### 2. `CalibratedSelfAssessment` (frozen dataclass)

Envelope que ata el assessment crudo a la evidencia y al nivel
ajustado:

```python
raw_assessment: BeliefSelfAssessment           # original, inline
calibration_history: CalibrationHistory        # evidencia
adjusted_overall_level: SelfAssessmentLevel    # post-feedback
adjustment_policy_id: str                      # snake_case taxonomy
adjustment_reason: str                         # snake_case taxonomy
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- `raw_assessment` debe ser `BeliefSelfAssessment` real.
- `calibration_history` debe ser `CalibrationHistory` real.
- `adjustment_policy_id` y `adjustment_reason` matchan
  `^[a-z][a-z0-9_]*$`, longitud 1-64 (taxonomía cerrada por formato,
  como ADR-0023).
- `adjusted_overall_level` debe ser miembro del catálogo cerrado
  `SelfAssessmentLevel`.
- **No** se exige `adjusted_overall_level >= raw_assessment.overall_level`.
  Una policy podría legítimamente *upgrade* (si las predicciones han
  sido consistentemente buenas, la confianza puede subir). v1 reference
  sólo hace passthrough o downgrade; el contrato no lo restringe.

### 3. `CalibrationAdjustmentPolicy` (Protocol, runtime_checkable)

```python
@property
def policy_id(self) -> str: ...

def adjust(
    self,
    raw: BeliefSelfAssessment,
    history: CalibrationHistory,
) -> CalibratedSelfAssessment: ...
```

Pure function shape: misma entrada → mismo output. Sin reloj, sin
random.

### 4. `MahalanobisDowngradePolicy` (reference)

Policy mínima:

- Si `history.count_beyond_3_std + history.count_beyond_5_std >= downgrade_threshold`
  y `history.outcomes_considered >= min_outcomes`: downgrade un nivel
  (KNOWN→UNCERTAIN, UNCERTAIN→UNKNOWN, UNKNOWN stays). Reason:
  `downgrade_from_calibration`.
- Si `history.outcomes_considered == 0`: passthrough, reason
  `no_outcomes_yet`.
- Else: passthrough, reason `calibration_within_tolerance`.

**Por qué tan mínima.** Hasta que existan corridas largas con datos
reales, cualquier policy más sofisticada es overfitting a casos
hipotéticos. Esta valida que el contrato sostiene una composición real
sin pretender ser la respuesta operacional final. Policies futuras
(per-axis, weighted by recency, hysteresis) implementarán el mismo
Protocol sin reabrir el envelope.

### 5. `build_calibration_history` + `assess_with_feedback`

```python
def build_calibration_history(
    outcomes: Iterable[PredictionOutcome],
    max_n: int,
) -> CalibrationHistory: ...

def assess_with_feedback(
    raw: BeliefSelfAssessment,
    outcomes: Iterable[PredictionOutcome],
    adjustment_policy: CalibrationAdjustmentPolicy,
    max_history: int = 32,
) -> CalibratedSelfAssessment: ...
```

Pure functions. `build_calibration_history` toma los últimos `max_n`
outcomes (asumiendo orden cronológico) y construye el snapshot.
`assess_with_feedback` es la orquestación canónica: history + policy
→ calibrated assessment.

### 6. Telemetry plumbing

- `CHANNEL_CALIBRATED_SELF_ASSESSMENT = "/self_assessment/calibrated"`.
- `CalibratedSelfAssessmentToTelemetryAdapter`: usa
  `calibrated.raw_assessment.belief_stamp_sim_ns` como `log_time`
  (instante del belief que originó la cadena).
- Decoder registrado en `replay._DECODERS` → round-trip MCAP completo.

## Scope deliberadamente fuera

- **No** se modifica `BeliefSelfAssessment` ni `assess_belief`. ADR-0020
  permanece intacto. El envelope ajustado COMPOSE, no reemplaza.
- **No** hay ajuste per-axis ni per-block. Sólo overall. Por-axis
  requiere mapear `PredictionOutcome` (que es per-vec3) a axes de
  belief — posible pero más complejo de lo necesario en v1.
- **No** hay matching automático prediction↔outcome. El caller pasa
  los outcomes ordenados; el ordering es responsabilidad del caller.
- **No** se persiste `CalibrationHistory` por separado. Viaja inline
  en `CalibratedSelfAssessment`. Si se necesita historizar histories
  sin context, queda como ADR futura.
- **No** se exige que el adjustment policy sea monotónico
  (downgrade-only). El contrato permite upgrade; la reference no lo
  usa.

## Consequences

**Positive:**

- Primera composición real entre contratos. El stream de outcomes ya
  no es solo audit log — alimenta la creencia del próximo ciclo.
- Un agente que emite predicciones consistentemente overconfident es
  *mecánicamente forzado* a downgrade su self-assessment. La
  "honestidad" deja de ser claim externo y se vuelve property
  enforced por el contrato.
- Policies futuras (mission planner que aprende de errores, attitude
  tracker con feedback adaptativo) tienen un shape estándar contra
  el cual componerse.
- ADRs siguientes (sensor → belief contract, controller real)
  heredan el patrón de composición que esta ADR establece.

**Negative / cost:**

- Nuevo canal + nuevo schema en el catálogo cerrado. Pequeño
  mantenimiento.
- El caller carga la responsabilidad de mantener el ordering de
  outcomes. Documentado, pero es una nueva carga.

**Neutral:**

- `MahalanobisDowngradePolicy` con threshold deliberadamente alto
  (`min_outcomes >= 4`, `downgrade_threshold >= 2`) es conservadora.
  Eso es intencional: prefiere mantener la honestidad estática
  (ADR-0020) cuando la evidencia es escasa.

## Alternatives considered

- **Modificar `BeliefSelfAssessment` añadiendo campos opcionales para
  feedback.** Rechazado: rompe el inmutability contract de ADR-0020.
  El envelope wrapping respeta ese contrato.
- **Hacer que `assess_belief` consuma outcomes directamente.**
  Rechazado: mezcla la responsabilidad de declarar el estado actual
  con la de aprender del pasado. La composición explícita es más
  auditable.
- **Per-axis feedback en v1.** Rechazado: el mapping
  outcome-axis-error → belief-axis requiere asunciones de frame que
  v1 no debe tomar. Overall level es derivable sin asunciones extra.
- **Stream de calibrated assessments con timestamps reservados.**
  Rechazado: el adapter usa `raw_assessment.belief_stamp_sim_ns` por
  consistencia con ADR-0020. Si se necesita timestamp distinto, queda
  como ADR amendment.

## Invariants verified by test

- `CalibrationHistory.__post_init__` rechaza counts negativos, suma
  inconsistente, NaN, stamp negativo, stamp no-None con outcomes=0.
- `CalibratedSelfAssessment.__post_init__` rechaza tipos malos,
  taxonomy mal formada, schema_version incorrecto.
- `build_calibration_history` con N outcomes produce
  `outcomes_considered == min(len, max_n)`, counts correctos,
  worst Mahalanobis correctos.
- `MahalanobisDowngradePolicy`: passthrough con 0 outcomes;
  passthrough con outcomes dentro de tolerance; downgrade con
  outcomes excediendo threshold; KNOWN→UNCERTAIN, UNCERTAIN→UNKNOWN,
  UNKNOWN stays.
- `assess_with_feedback` es pure: misma entrada → mismo output
  byte-equal.
- Round-trip MCAP: calibrated assessment → write → read → decoded
  matchea.
- Cross-process byte determinism del MCAP.

## File map

```
src/project_ghost/core/feedback/
    __init__.py
    types.py                # CalibrationHistory, CalibratedSelfAssessment
    protocols.py            # CalibrationAdjustmentPolicy
    reference_policy.py     # MahalanobisDowngradePolicy
    orchestration.py        # build_calibration_history, assess_with_feedback

src/project_ghost/telemetry/
    channels.py             # + CHANNEL_CALIBRATED_SELF_ASSESSMENT
    adapters.py             # + CalibratedSelfAssessmentToTelemetryAdapter
    replay.py               # + decoder registration
    __init__.py             # + re-exports

tests/core/feedback/
    __init__.py
    test_feedback.py        # types + reference + orchestration

tests/telemetry/
    test_calibrated_assessment_adapter.py  # adapter + MCAP round-trip
```
