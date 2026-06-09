# ADR-0028 — Sensor-to-Belief Fusion Contract v1

## Status
Accepted (2026-06-08).

## Context

Ocho ADRs después, el loop epistémico está cerrado y los contratos
componen bajo carga. Pero el smoke todavía revela una ficción:
`VehicleState` aparece como input al ciclo sin contrato explícito que
diga **quién lo produce**. En el smoke, `_make_state(t_ns)` sintetiza
groundtruth directamente. En cualquier runtime real, el belief viene
de fusión de sensores — y eso no tiene shape en el proyecto.

Consecuencias para la cláusula central de la misión:

- "El agente cree X" es indemostrable mientras no haya artefacto que
  diga cómo se produjo X.
- El estimator (ADR-0015 noisy groundtruth) emite estados pero no es
  fusión — es ruido aplicado a verdad conocida. No hay contrato que
  un Kalman filter o factor graph pueda implementar para encajar en
  el ciclo.
- ADR-0027 ata calibración a decisiones, pero el belief de entrada
  no tiene provenance. Si el siguiente belief llega sin link al
  anterior, el closed-loop pierde la cadena.

ADR-0028 cierra ese gap con **el contrato** — no con un Kalman filter
real, no con un factor graph. Sólo shapes verificables: una `FusionInput`
content-addressed, un `FusionResult` que carga el belief producido y
el hash de su origen, los Protocols correspondientes, una reference
policy mínima que demuestra que el contrato es sound (oracle
groundtruth para sim), y el wiring de telemetría.

## Decision

Añadir el paquete `project_ghost.core.fusion` con cinco contratos
puros + un wiring mínimo de telemetría. Stdlib + numpy. Cero nuevas
dependencias.

### 1. `FusionInput` (frozen dataclass)

Bundle de inputs que un policy ve para producir el belief siguiente:

```python
sensor_samples: tuple[SensorSample[Any], ...]  # may be empty
prior_belief_stamp_sim_ns: int | None          # None on first cycle
target_stamp_sim_ns: int                        # when this fusion runs
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- `target_stamp_sim_ns >= 0`.
- Cuando `prior_belief_stamp_sim_ns` no es `None`, debe ser
  `< target_stamp_sim_ns` (la fusión avanza en el tiempo; no
  rewriting).
- `sensor_samples` es tuple inmutable (puede ser vacío para policies
  oracle).

### 2. `FusionResult` (frozen dataclass)

Envelope que ata el belief producido al hash del input que lo
produjo:

```python
belief: VehicleState
fusion_input_sha256: str                       # 64 hex lowercase
fusion_policy_id: str                          # snake_case taxonomy
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- `belief.stamp_sim_ns == target_stamp_sim_ns` del FusionInput
  productor (verificable cross-channel via stamps en MCAP; no se
  duplica `target_stamp_sim_ns` en el result para evitar redundancia).
- `fusion_input_sha256` es 64 hex chars lowercase (mismo posture que
  ADR-0022).
- `fusion_policy_id` matchea `^[a-z][a-z0-9_]*$`, longitud 1-64.

### 3. `SensorFusionPolicy` (Protocol, runtime_checkable)

```python
@property
def fusion_policy_id(self) -> str: ...

def fuse(self, fusion_input: FusionInput) -> FusionResult: ...
```

Pure function shape: mismo `FusionInput` → mismo `FusionResult`. Sin
reloj de pared, sin random, sin estado mutable visible.

### 4. `LinearMotionOracleFusionPolicy` (reference)

Policy mínima documentada: ignora `sensor_samples`, computa el belief
por propagación lineal desde un origen fijo configurado. Es el
equivalente de fusión a "kill-only" para actuación — la policy más
simple que valida que el contrato sostiene.

Parámetros (frozen al construir):

- `initial_position_enu_m: np.ndarray`, shape (3,) float64.
- `velocity_world_mps: np.ndarray`, shape (3,) float64.
- `start_stamp_sim_ns: int`, instante referencia para t=0.
- `covariance_diag: float`, varianza diagonal uniforme para el
  belief producido.

`fusion_policy_id` incluye los parámetros para distinguir instancias
en MCAP. Pose en `target_stamp` =
`initial + velocity * (target - start) / 1e9`.

**No es estimación.** Es oracle: el policy "sabe" la trayectoria
verdadera por configuración. Útil para sim deterministic.
Estimadores reales (KF, EKF, factor graph) implementan el mismo
Protocol consumiendo `sensor_samples` y produciendo `belief` con
covariance real.

### 5. `fuse_and_publish` (orquestación)

```python
def fuse_and_publish(
    policy: SensorFusionPolicy,
    fusion_input: FusionInput,
    sink: FusionResultSink,
) -> FusionResult: ...
```

One-shot canónico, mismo posture que `decide_and_publish` y
`actuate_and_publish`.

### 6. `compute_fusion_input_sha256` (helper público)

Función pure que produce el SHA-256 hex canónico de un FusionInput,
usable por el caller para verificar que un FusionResult está bien
atado a su input. Canonical JSON: `sort_keys=True`,
`ensure_ascii=False`, `separators=(",", ":")`.

### 7. Telemetry plumbing

- `CHANNEL_FUSION_RESULTS = "/fusion/results"`.
- `FusionResultToTelemetryAdapter`: usa `belief.stamp_sim_ns` como
  `log_time`.
- Decoder registrado en `replay._DECODERS` → round-trip MCAP completo.

## Scope deliberadamente fuera

- **No** se introduce un estimator real (KF/EKF/UKF/factor graph).
  Esos son policies que implementan el Protocol — fuera de scope.
- **No** se introduce un contrato de simulación de sensores. El
  `LinearMotionOracleFusionPolicy` no necesita generar samples; otras
  reference policies o adapters que sí los consuman llegarán cuando
  haya un contrato de sim sensors.
- **No** se valida estadísticamente la covariance producida. El
  policy declara una covariance; la calibración (ADR-0019) y los
  outcomes (ADR-0025) auditan post-hoc si esa declaración fue
  honesta.
- **No** se publica `FusionInput` por separado. Su hash queda en
  `FusionResult.fusion_input_sha256`; la reconstrucción del input
  exacto queda como ADR amendment futura si se necesita audit
  cross-process.

## Consequences

**Positive:**

- Por primera vez existe un artefacto auditable que dice "este
  belief vino de este policy con este input". El loop epistémico
  ya no descansa sobre groundtruth implícito.
- Estimadores reales (KF, factor graph) tienen un shape estándar
  contra el cual conformarse — el smoke puede comparar policies
  midiendo divergencia entre sus FusionResults.
- ADRs futuras (sim sensor contract, real HAL integration) heredan
  el patrón: cualquier productor de VehicleState al runtime
  implementa `SensorFusionPolicy`.

**Negative / cost:**

- Nuevo canal + nuevo schema. Pequeño mantenimiento.
- El smoke se reescribe ligeramente: pasa de `_make_state(t_ns)`
  directo a `policy.fuse(input)` indirecto.

**Neutral:**

- `LinearMotionOracleFusionPolicy` no es estimación real. Es el
  oracle que valida la shape. Real estimators llegarán como ADRs
  separadas.

## Alternatives considered

- **Hacer que `VehicleState` carry directamente el provenance del
  fusion policy.** Rechazado: viola la inmutabilidad y el shape
  rígido de ADR-0005 (canonical vehicle state). Wrapping en
  FusionResult es más limpio.
- **Sólo publicar el hash del input sin record completo.** Rechazado:
  rompe el patrón de "envelope auto-contenido" que ADRs 0021-0027
  establecieron. Result inline es trivialmente auditable.
- **Reusar `/state/nav` como canal de fusion results.** Rechazado:
  mezcla "el belief actual" con "la procedencia del belief". Canales
  separados permiten que tooling correlacione sin parsear records.

## Invariants verified by test

- `FusionInput.__post_init__` rechaza target_stamp negativo, prior
  posterior a target.
- `FusionResult.__post_init__` rechaza hash mal formado,
  policy_id mal formado.
- `compute_fusion_input_sha256` es pure: misma entrada → mismo hash
  byte-equal cross-process.
- `LinearMotionOracleFusionPolicy.fuse` es pure y produce belief
  consistente con propagación lineal exacta.
- Round-trip MCAP: FusionResult → write → read → decoded matchea.
- Cross-process byte determinism del MCAP capture.
- Integration smoke se actualiza para usar fusion como input de
  belief.

## File map

```
src/project_ghost/core/fusion/
    __init__.py
    types.py                # FusionInput, FusionResult, compute_fusion_input_sha256
    protocols.py            # SensorFusionPolicy, FusionResultSink
    sinks.py                # NullFusionResultSink, RecordingFusionResultSink
    reference_policy.py     # LinearMotionOracleFusionPolicy
    orchestration.py        # fuse_and_publish

src/project_ghost/telemetry/
    channels.py             # + CHANNEL_FUSION_RESULTS
    adapters.py             # + FusionResultToTelemetryAdapter
    replay.py               # + decoder
    __init__.py             # + re-exports

tests/core/fusion/
    __init__.py
    test_fusion.py

tests/telemetry/
    test_fusion_result_adapter.py

src/project_ghost/examples/
    closed_loop_smoke.py    # use fusion policy to produce belief
```
