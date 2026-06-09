# ADR-0027 — Calibration-Aware Decision Context v1

## Status
Accepted (2026-06-08).

## Context

El smoke post-ADR-0026 (commit `aaa222c`) surfaceó un gap real e
inmediato. Diez ciclos con predicciones overconfident produjeron:

- `outcomes` consistentemente `BEYOND_5_STD`.
- `CalibratedSelfAssessment.adjusted_overall_level` downgrade de
  `KNOWN` a `UNCERTAIN` desde el ciclo 5.
- **Las 10 decisiones quedaron en `PROCEED`.**

ADR-0026 produce el artefacto calibrado pero **no lo wirea al lado
de decisión**. La `DecisionContext` (ADR-0021) lleva
`self_assessment: BeliefSelfAssessment | None` — el assessment crudo.
La policy `UncertaintyAwareReferencePolicy` lee `sa.overall_level` y
decide en consecuencia. Como el assessment crudo sigue siendo KNOWN
(la covarianza declarada es pequeña), la decisión sigue siendo
PROCEED — aunque toda la evidencia post-hoc dice que el modelo
dinámico está equivocado.

El test `test_smoke_decisions_stay_proceed_documented_gap` pinned ese
gap precisamente para que su falla futura señale el cierre. ADR-0027
cierra el gap.

## Decision

Extender `DecisionContext` (ADR-0021) con UN campo opcional adicional
+ una property derivada. Cambio puramente aditivo: contextos
existentes siguen funcionando sin tocar; policies que ignoren el
nuevo campo conservan su comportamiento.

### 1. `DecisionContext` (amendment aditivo)

```python
@dataclass(frozen=True)
class DecisionContext:
    belief_stamp_sim_ns: int
    self_assessment: BeliefSelfAssessment | None
    flight_status: FlightStatus
    mission_status: MissionStatus
    perception_mode: PerceptionMode | None
    calibrated_self_assessment: CalibratedSelfAssessment | None = None  # NEW
    schema_version: int = DECISION_PROTOCOL_VERSION

    @property
    def effective_overall_level(self) -> SelfAssessmentLevel | None:
        """Calibration-aware level used by calibration-aware policies.

        Priority order: calibrated.adjusted_overall_level (if present)
        > self_assessment.overall_level > None.
        """
        if self.calibrated_self_assessment is not None:
            return (
                self.calibrated_self_assessment.adjusted_overall_level
            )
        if self.self_assessment is not None:
            return self.self_assessment.overall_level
        return None
```

Invariantes nuevos (enforced por `__post_init__`):

- `calibrated_self_assessment`, cuando no es `None`, debe ser un
  `CalibratedSelfAssessment` real.
- Cuando ambos están presentes, su stamp debe ser consistente:
  `calibrated.raw_assessment.belief_stamp_sim_ns == self_assessment.belief_stamp_sim_ns`.
  Sin esa identidad la composición no tiene sentido — calibration
  estaría sobre un belief distinto al raw.

### 2. `UncertaintyAwareReferencePolicy` (semantic update)

La policy ahora lee `context.effective_overall_level` en lugar de
`context.self_assessment.overall_level`. El mapeo de niveles a kinds
queda IDÉNTICO:

| `effective_overall_level` | `DecisionKind`     | `reason`             |
|---|---|---|
| `None`                    | `ABSTAIN_UNCERTAIN`| `no_assessment`      |
| `UNKNOWN`                 | `ABSTAIN_UNCERTAIN`| `overall_unknown`    |
| `UNCERTAIN`               | `HOLD`             | `overall_uncertain`  |
| `KNOWN`                   | `PROCEED`          | `overall_known`      |

El `reason` no encoda "calibrated" — la fuente del level es
reconstruible cross-channel via stamp en MCAP
(`/decisions` ↔ `/self_assessment/calibrated`).

### 3. `decide_and_publish` / `decide_with_rationale` (sin cambios)

Reciben `DecisionContext` y producen `Decision` + `DecisionRationale`.
Como el wiring de calibración va EN el context (no en la signature),
estos orchestradores quedan intactos.

### 4. `DecisionRationale` (sin cambios)

`assessment_sha256` sigue refiriendo al BeliefSelfAssessment crudo
(viaja inline). La provenance de calibración queda implícita —
reconstruible por stamp en MCAP. Extender el rationale con
`calibrated_assessment_sha256` queda como ADR futura si la auditoría
explícita lo demanda.

## Scope deliberadamente fuera

- **No** se introducen reasons nuevas. El catálogo queda en
  4 niveles. Si el reader quiere saber "esta decisión fue informada
  por calibración", compara stamps en MCAP entre los canales
  `/decisions` y `/self_assessment/calibrated`.
- **No** se extiende `DecisionRationale`. El rationale sigue
  content-addressing el raw assessment.
- **No** se obliga al caller a pasar `calibrated_self_assessment`.
  El campo es opcional. Callers sin feedback simplemente lo dejan
  `None` y el comportamiento es idéntico al de ADR-0021 pre-amendment.
- **No** se construye una policy alternativa
  (`CalibrationAwareReferencePolicy`). La policy de referencia
  existente ahora ES calibration-aware vía el property —
  duplicarla sería ruido.

## Consequences

**Positive:**

- Cierra el loop epistémico completo: belief → assess → predict →
  outcome → calibrated → **decide → actuate** → siguiente ciclo.
- El smoke ahora observa el comportamiento cambiar como respuesta
  al feedback: cycles 5-10 pasan de `proceed` a `hold` (UNCERTAIN
  → HOLD).
- Backward-compat puro: cualquier test, smoke o sim existente que
  no pase `calibrated_self_assessment` mantiene su comportamiento.
- El patrón "campo opcional + property derivada" es replicable para
  futuras composiciones (perception_mode, mission constraints, etc.)
  sin romper el shape del context.

**Negative / cost:**

- Amend a ADR-0021 (aditivo, no superseding). Documentado como
  "amendment by ADR-0027" en la entrada del índice.
- El test pinned `test_smoke_decisions_stay_proceed_documented_gap`
  se reescribe en este mismo cambio — esa es la señal explícita del
  cierre.

**Neutral:**

- La provenance de calibración queda implícita en MCAP via stamps.
  Si en el futuro un consumer necesita audit explícito en el
  rationale, se introducirá como ADR amendment.

## Alternatives considered

- **Nueva policy `CalibrationAwareReferencePolicy` que tome
  `(raw, calibrated)` como inputs distintos.** Rechazado: duplica
  el shape del policy Protocol, requiere orchestración paralela
  (`decide_with_calibration_and_publish`), y el decision artifact
  no carga información sobre la policy usada salvo el `policy_id`
  — el cliente tendría que correlacionar manualmente.

- **Mutar `BeliefSelfAssessment.overall_level` para reflejar la
  calibración antes de pasar al policy.** Rechazado: viola la
  inmutabilidad del raw assessment y genera per-axis levels que
  mienten (overall calibrado pero axes crudos). Hack frágil.

- **Extender `DecisionRationale` para llevar el hash del
  `CalibratedSelfAssessment`.** Rechazado para v1: aumenta surface
  contractual sin desbloquear capacidad inmediata. Stamps en MCAP
  son suficientes para auditar la composición. Si la auditoría
  cross-channel se vuelve crítica, queda como ADR amendment
  trivial.

## Invariants verified by test

- `DecisionContext` con `calibrated_self_assessment=None` (default)
  preserva el comportamiento de ADR-0021 byte-equal.
- `effective_overall_level` devuelve el nivel ajustado cuando
  calibrated está presente.
- `__post_init__` rechaza `calibrated_self_assessment` cuyo stamp
  difiere del raw assessment.
- `UncertaintyAwareReferencePolicy.decide` produce decisiones
  consistentes con `effective_overall_level` en los cuatro paths
  (None / KNOWN / UNCERTAIN / UNKNOWN).
- En el smoke post-ADR-0027: 10 ciclos producen mix de PROCEED
  (cycles 1-4 sin calibration o calibration confirma KNOWN) y HOLD
  (cycles 5-10 con calibration downgrade a UNCERTAIN).

## File map

```
src/project_ghost/core/decisions/
    types.py                # + calibrated_self_assessment, + effective_overall_level
    reference_policy.py     # use effective_overall_level

src/project_ghost/examples/
    closed_loop_smoke.py    # pass calibrated through DecisionContext

tests/core/decisions/
    test_decisions.py       # + tests for new field + property + validation

tests/integration/
    test_closed_loop_smoke.py  # flip pinned gap test → closure assertion
```
