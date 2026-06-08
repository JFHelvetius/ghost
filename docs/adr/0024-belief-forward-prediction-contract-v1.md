# ADR-0024 — Belief Forward-Prediction Contract v1

## Status
Accepted (2026-06-08).

## Context

Tras ADR-0019 a ADR-0023, el agente declara sobre el PRESENTE:

- cuánto cree saber (ADR-0020 — self-assessment),
- qué decide (ADR-0021 — decision),
- cómo se justifica la decisión (ADR-0022 — decision trace),
- qué comanda al actuador (ADR-0023 — actuation directive).

Cuatro declaraciones, cuatro auditables. **Todas estáticas.** El agente
nunca se compromete con una predicción sobre el FUTURO. Consecuencias
para la cláusula central de la misión ("máquinas que saben cuándo no
saben"):

- La calibración (ADR-0019) sólo audita varianza declarada vs residuos
  sobre el estado actual — nunca sobre predicciones forward.
- El ciclo es **epistémicamente open-loop**: emitimos comandos y, cuando
  llega la siguiente observación, no hay artefacto previo que ella
  pueda refutar o confirmar.
- El modelo dinámico interno del agente es **implícito**. Ningún
  observador externo puede inspeccionar "este agente cree que su
  acción produce este efecto".

La asimetría es cara: tenemos honestidad estática (lo que sé ahora) sin
honestidad dinámica (lo que predigo que va a pasar). Sin predicciones
explícitas en MCAP, no hay nada que una futura "Prediction-Observation
Divergence Check" pueda comparar — quedamos bloqueados antes de poder
cerrar el closed loop epistémico.

ADR-0024 cierra ese gap con **el contrato** de forward-prediction —
no con un modelo dinámico realista, no con un mission planner. Sólo
shapes verificables: un envelope que ata cada belief a una predicción
de observación futura, los Protocols correspondientes, un predictor de
referencia mínimo (constant-velocity) que demuestra que el contrato es
sound, y el wiring de telemetría para que cada predicción sea capturable
y refutable.

## Decision

Añadir el paquete `project_ghost.core.prediction` con cinco contratos
puros + un wiring mínimo de telemetría. Patrón idéntico al de
ADR-0021/ADR-0023. Stdlib + numpy (ya transitivo); cero nuevas
dependencias.

### 1. `BeliefForwardPrediction` (frozen dataclass)

Envelope que ata una creencia presente a una predicción de pose en un
horizonte declarado:

```python
source_belief_stamp_sim_ns: int          # belief que originó la predicción
predicted_observation_stamp_sim_ns: int  # source + horizon
horizon_ns: int                          # > 0
predicted_pose: Pose                     # qué pose espera el agente
predicted_pose_std: PoseStd              # con qué incertidumbre
associated_directive_hash: str | None    # link opcional a ActuationDirective
predictor_id: str                        # snake_case identifier estable
schema_version: int = 1
```

Donde `PoseStd` es un dataclass paralelo a `Pose`:

```python
position_std_enu_m: np.ndarray           # shape (3,), >= 0
orientation_std_rad: np.ndarray          # shape (3,), >= 0  (yaw, pitch, roll axis-angle)
```

Invariantes (enforced por `__post_init__`):

- `horizon_ns > 0` (no se predice el presente; eso es self-assessment).
- `predicted_observation_stamp_sim_ns == source_belief_stamp_sim_ns + horizon_ns`.
- `predictor_id` matchea `^[a-z][a-z0-9_]*$`, longitud 1-64.
- `associated_directive_hash` es `None` (predicción standalone) o
  64 chars hex lowercase SHA-256 (link a directive — formato idéntico
  al chain de ADR-0022).
- `PoseStd`: arrays float64 shape (3,), todos los componentes
  finitos y `>= 0`.

### 2. `ForwardPredictor` (Protocol, runtime_checkable)

```python
@property
def predictor_id(self) -> str: ...

def predict(
    self,
    belief: VehicleState,
    horizon_ns: int,
    directive_hash: str | None = None,
) -> BeliefForwardPrediction: ...
```

Pure function shape: mismo `(belief, horizon, directive_hash)` → misma
`BeliefForwardPrediction`. Sin reloj, sin random, sin estado mutable
visible.

### 3. `ForwardPredictionSink` (Protocol, runtime_checkable)

```python
def publish(self, prediction: BeliefForwardPrediction) -> None: ...
```

`NullForwardPredictionSink` (descarta) y
`RecordingForwardPredictionSink` (guarda in-memory) como
implementaciones de referencia para tests.

### 4. `ConstantVelocityForwardPredictor` (reference)

El predictor más simple que demuestra el contrato:

- Posición predicha: `belief.pose.position + belief.twist_world.linear * (horizon_ns / 1e9)`.
- Orientación predicha: `belief.pose.orientation_q` (constant — sin
  modelo de torque).
- Std posicional: derivada del bloque (0:3, 0:3) de
  `nav.covariance_15x15` cuando está presente; fallback fijo si no.
- Std orientacional: derivada del bloque (6:9, 6:9) cuando está
  presente; fallback fijo si no.

**Por qué tan mínima.** Constant-velocity no usa el comando — sólo
propaga la creencia actual. Eso es exactamente el predictor "no asumo
efecto del actuador". Cuando aterricen mission planners con modelo
dinámico, implementarán el mismo Protocol con el mismo shape de salida
y la divergencia entre ambos será mecánicamente comparable.

### 5. `forward_predict_and_publish`

```python
def forward_predict_and_publish(
    predictor: ForwardPredictor,
    belief: VehicleState,
    horizon_ns: int,
    sink: ForwardPredictionSink,
    directive_hash: str | None = None,
) -> BeliefForwardPrediction: ...
```

One-shot canónico, mismo posture que `decide_and_publish` y
`actuate_and_publish`.

### 6. Telemetry plumbing

- `CHANNEL_FORWARD_PREDICTIONS = "/predictions/forward"`.
- `ForwardPredictionToTelemetryAdapter` (usa
  `prediction.source_belief_stamp_sim_ns` como `log_time`).
- Decoder registrado en `replay._DECODERS` → round-trip MCAP completo.

## Scope deliberadamente fuera

- **No** se evalúa la predicción contra observación real. Eso es
  ADR-0025 (Prediction-Observation Divergence Check). Mezclar ambas
  ADRs mezcla "el agente puede comprometerse" con "podemos auditar el
  compromiso"; son separables.
- **No** hay modelo dinámico con torques/thrust. Constant-velocity es
  el predictor más débil posible que demuestra que el contrato es
  sustentable.
- **No** se exige que cada decisión tenga predicción asociada.
  `associated_directive_hash` es nullable — el predictor puede correr
  standalone para forecasting puro.
- **No** se predice incertidumbre de velocidad o de biases — sólo pose
  (posición + orientación). Eso mantiene el shape mínimo. Extensiones
  van en ADRs futuras sin reabrir este shape.

## Consequences

**Positive:**

- El agente emite artefactos falsificables sobre el futuro. Un
  observador externo que tenga `(prediction, actual_observation)` puede
  decidir mecánicamente si el agente fue honesto.
- ADR-0025 (Prediction-Observation Divergence) queda desbloqueada: ya
  hay predicciones en MCAP que comparar.
- El modelo dinámico interno del agente deja de ser implícito. Si dos
  predictores difieren, la diferencia es inspeccionable en MCAP.
- Se mantiene la simetría de patrones: belief side / decision side /
  action side / **prediction side**, todos como Protocols puros con
  reference policy mínima.

**Negative / cost:**

- Nuevo canal en MCAP. Pequeño overhead por publicación.
- Una más para mantener en el catálogo cerrado de schemas.

**Neutral:**

- Constant-velocity no es un buen predictor para drones reales. Es el
  predictor más débil que demuestra que el contrato sostiene. Cuando
  aterricen predictores con modelo dinámico, se beneficiarán del
  mismo shape sin reabrirlo.

## Alternatives considered

- **Acción chain verification (action-side mirror de ADR-0022).**
  Rechazado: cierra una asimetría incremental (tamper evidence
  duplicado) sin abrir capacidad nueva. Forward-prediction abre el
  lado dinámico de la honestidad epistémica.
- **End-to-end replay verification.** Rechazado para esta vuelta:
  valuable pero ortogonal a la misión central ("knowing when you
  don't know"). Reservar para una iteración futura cuando el sistema
  tenga más componentes que replay verifique.
- **Predecir directamente next sensor reading en lugar de pose.**
  Rechazado: acopla el predictor al catálogo de sensores y mezcla
  dos contratos (modelo dinámico + modelo de medición). Pose es el
  ground truth canónico del agente; sensor reading es derivado.

## Invariants verified by test

- `BeliefForwardPrediction.__post_init__` rechaza `horizon_ns <= 0`,
  stamps inconsistentes, predictor_id mal formado,
  `associated_directive_hash` no-hex/no-64.
- `PoseStd.__post_init__` rechaza shapes inválidos, dtype incorrecto,
  componentes negativos o no finitos.
- `ConstantVelocityForwardPredictor` es pure: misma entrada produce
  el mismo `BeliefForwardPrediction` byte-equal (verificado vía
  encode_to_bytes).
- `ForwardPredictor` y `ForwardPredictionSink` Protocols son
  satisfechos estructuralmente por las implementaciones de referencia
  (verificado vía `isinstance`).
- Pipeline end-to-end belief → forward-predict → MCAP → decode
  reconstruye un `BeliefForwardPrediction` con todos los campos
  intactos.
- Cross-process byte determinism: el MCAP producido en N procesos
  distintos para el mismo input tiene SHA-256 idéntico.

## File map

```
src/project_ghost/core/prediction/
    __init__.py
    types.py                # PoseStd, BeliefForwardPrediction
    protocols.py            # ForwardPredictor, ForwardPredictionSink
    sinks.py                # NullForwardPredictionSink, RecordingForwardPredictionSink
    reference_predictor.py  # ConstantVelocityForwardPredictor
    orchestration.py        # forward_predict_and_publish

src/project_ghost/telemetry/
    channels.py             # + CHANNEL_FORWARD_PREDICTIONS
    adapters.py             # + ForwardPredictionToTelemetryAdapter
    replay.py               # + decoder registration
    __init__.py             # + re-exports

tests/core/prediction/
    __init__.py
    test_prediction.py      # types + reference + protocols + orchestration

tests/telemetry/
    test_forward_prediction_adapter.py  # adapter + MCAP round-trip + pipeline
```
