# ADR-0025 — Prediction-Observation Divergence Check v1

## Status
Accepted (2026-06-08).

## Context

ADR-0024 introdujo el contrato de forward-prediction: el agente se
compromete con `BeliefForwardPrediction(source_belief, predicted_obs,
horizon, pose, std)`. Esa pieza es necesaria pero insuficiente: una
predicción que nadie compara con la observación real es ruido
auditado. Sin closure:

- El agente puede emitir predicciones arbitrariamente confiadas o
  arbitrariamente conservadoras y nadie lo nota.
- La cláusula central de la misión ("saber cuándo no se sabe") sólo
  está parcialmente verificada: el agente declara incertidumbre pero
  nada audita si esa declaración es honesta sobre el futuro.
- ADR-0019 calibra varianza vs residuos sobre el ESTADO ACTUAL.
  No cubre predicciones forward — son objetos distintos con stamps
  distintos y semánticas distintas (commitment vs estado).
- Los predictores que aterricen más tarde (mission planner con
  modelo dinámico, attitude tracker) no tendrán una métrica
  estandarizada para compararse contra el constant-velocity baseline.

ADR-0025 cierra ese gap con **el contrato** de evaluación, no con un
analítico agregado, no con un dashboard. Sólo shapes verificables: un
envelope que ata cada predicción a su observación real con los
residuos computados, un veredicto categórico cerrado, una pure
function que los compone, y el wiring de telemetría.

## Decision

Añadir el módulo `project_ghost.core.prediction.divergence` con tres
contratos puros + un wiring mínimo de telemetría. Stdlib + numpy.
Cero nuevas dependencias.

### 1. `DivergenceVerdict` (StrEnum, closed catalog)

```python
class DivergenceVerdict(StrEnum):
    WITHIN_1_STD = "within_1_std"
    BEYOND_1_STD = "beyond_1_std"
    BEYOND_3_STD = "beyond_3_std"
    BEYOND_5_STD = "beyond_5_std"
```

Catálogo cerrado: modificarlo (añadir/renombrar/borrar) requiere
ADR amendment explícito. Mismo posture que `DecisionKind` y
`PerceptionMode`.

### 2. `PredictionOutcome` (frozen dataclass)

Envelope que ata la predicción original a la observación real y los
residuos computados:

```python
prediction: BeliefForwardPrediction          # commitment original (inline)
actual_belief_stamp_sim_ns: int              # == prediction.predicted_observation_stamp_sim_ns
actual_pose: Pose                            # lo que realmente se observó
position_error_enu_m: np.ndarray             # actual - predicted, shape (3,)
position_error_norm_m: float                 # ||position_error||
orientation_error_rad: np.ndarray            # axis-angle delta, shape (3,)
orientation_error_norm_rad: float            # ||orientation_error||
position_mahalanobis_max: float              # max_i(|err_i| / std_i)
orientation_mahalanobis_max: float           # max_i(|err_i| / std_i)
verdict: DivergenceVerdict
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- `actual_belief_stamp_sim_ns == prediction.predicted_observation_stamp_sim_ns`.
  Sin esta identidad la divergencia no es comparable.
- Errores son float64, shape (3,), todos finitos.
- Normas son finitas y `>= 0`.
- Mahalanobis es finito-o-`+inf` (inf legítimo cuando std=0 y error≠0).
- Verdict consistente con `max(pos_mahal_max, ori_mahal_max)`.

### 3. `compute_divergence` (pure function)

```python
def compute_divergence(
    prediction: BeliefForwardPrediction,
    actual_pose: Pose,
    actual_belief_stamp_sim_ns: int,
) -> PredictionOutcome: ...
```

- Pure: misma entrada → mismo `PredictionOutcome` byte-equal.
- Stdlib + numpy. Sin reloj, sin random.
- Quaternion error vía producto `actual * predicted_conj` →
  axis-angle (atan2 para estabilidad numérica, normalización de
  signo para resolver ambigüedad `q ≡ -q`).
- Per-axis Mahalanobis: para cada eje `i`, `term_i = 0` si
  `err_i == 0` y `std_i == 0`; `term_i = inf` si `err_i != 0` y
  `std_i == 0`; `term_i = |err_i| / std_i` en otro caso.
- Verdict:

| `max(pos_mahal, ori_mahal)` | Verdict |
|---|---|
| `< 1` | `WITHIN_1_STD` |
| `[1, 3)` | `BEYOND_1_STD` |
| `[3, 5)` | `BEYOND_3_STD` |
| `>= 5` (incluye `+inf`) | `BEYOND_5_STD` |

### 4. Telemetry plumbing

- `CHANNEL_PREDICTION_OUTCOMES = "/predictions/outcomes"`.
- `PredictionOutcomeToTelemetryAdapter`: usa
  `outcome.actual_belief_stamp_sim_ns` como `log_time` (el instante
  en que la divergencia es computable).
- Decoder registrado en `replay._DECODERS` → round-trip MCAP completo.

## Scope deliberadamente fuera

- **No** se agregan calibraciones (mean/std/CDF de residuos sobre N
  outcomes). Eso queda como tooling de análisis que compone sobre
  `PredictionOutcome` stream — fuera de este ADR.
- **No** se enchufa a la decisión siguiente. El outcome es un
  artefacto auditable; no realimenta automáticamente la self-assessment
  del próximo ciclo. Eso es ADR-0026+ (closed-loop feedback).
- **No** hay matching automático prediction↔observation. El caller
  pasa ambos. Match infrastructure (correlate por stamp) es tooling.
- **No** se valida que `actual_pose` venga de groundtruth vs estimador
  — el contrato sólo dice "esto es lo que se observó". El caller
  decide la fuente.

## Consequences

**Positive:**

- Cada commitment forward del agente es ahora refutable
  mecánicamente: hay un dataclass que lo dice.
- Predictores futuros (con modelo dinámico) tienen una métrica
  estándar contra constant-velocity baseline: comparar
  distribuciones de verdict.
- El veredicto categórico abre tooling de auditoría sin acoplarlo
  al schema: un dashboard puede agrupar por verdict sin reabrir el
  envelope.
- La cláusula "saber cuándo no se sabe" gana cierre dinámico: si el
  agente declara `predicted_pose_std=0.01m` y observa errores de
  `0.5m`, su verdict será `BEYOND_5_STD` y eso queda en MCAP.

**Negative / cost:**

- Nuevo canal + nuevo schema en el catálogo cerrado. Pequeño
  mantenimiento.
- Per-axis Mahalanobis con std=0 produce inf — es una elección
  semántica, no un bug. Tests cubren ambos casos (inf legítimo y
  0/0=0).

**Neutral:**

- El verdict de 4 niveles es deliberadamente grueso. Los umbrales
  estándar (1σ, 3σ, 5σ) son convenciones reconocibles. Si más
  granularidad se necesita, el campo Mahalanobis bruto está
  disponible.

## Alternatives considered

- **`PredictionResidual` sin verdict (sólo números crudos).**
  Rechazado: el verdict categórico es la decisión de auditoría que
  un consumer puede usar sin re-derivar umbrales. Los números crudos
  también están en el record — no se pierde nada.
- **Verdict booleano (pasa/falla).** Rechazado: pasa/falla colapsa
  la diferencia entre `BEYOND_1_STD` (normal-ish) y `BEYOND_5_STD`
  (catástrofe). Cuatro niveles dan señal sin agregar complejidad.
- **Acoplar al closed-loop (alimentar siguiente self-assessment).**
  Rechazado para esta vuelta: cierra dos contratos a la vez (evaluación
  + feedback). Mantener separados permite que el feedback evolucione
  con más datos.
- **Sólo posición (sin orientación).** Rechazado: la predicción ya
  incluye orientación en ADR-0024; ignorarla aquí dejaría una
  asimetría injustificada.

## Invariants verified by test

- `PredictionOutcome.__post_init__` rechaza stamp mismatch, errores
  no-finitos, normas negativas, verdict inconsistente con Mahalanobis.
- `compute_divergence` es pure: misma entrada → mismo outcome
  byte-equal (verificado vía `encode_to_bytes`).
- Identity case: `actual_pose == predicted_pose` → error cero,
  verdict `WITHIN_1_STD`.
- Verdict thresholds: posición a `0.5σ`, `1.5σ`, `4σ`, `10σ` por
  cada eje producen `WITHIN_1_STD`, `BEYOND_1_STD`, `BEYOND_3_STD`,
  `BEYOND_5_STD` respectivamente.
- Mahalanobis con std=0: `error=0` → 0; `error!=0` → inf con verdict
  `BEYOND_5_STD`.
- Quaternion error: `actual_q = predicted_q` → error angular cero;
  rotación de `pi` alrededor de eje → norma `pi`.
- Round-trip MCAP: outcome → write → read → decoded matchea.
- Cross-process byte determinism del MCAP.

## File map

```
src/project_ghost/core/prediction/
    divergence.py            # DivergenceVerdict, PredictionOutcome, compute_divergence
    __init__.py              # + re-exports

src/project_ghost/telemetry/
    channels.py              # + CHANNEL_PREDICTION_OUTCOMES
    adapters.py              # + PredictionOutcomeToTelemetryAdapter
    replay.py                # + decoder registration
    __init__.py              # + re-exports

tests/core/prediction/
    test_divergence.py       # compute + verdict thresholds + invariants

tests/telemetry/
    test_prediction_outcome_adapter.py  # adapter + MCAP round-trip
```
