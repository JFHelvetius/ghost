# ADR-0032 — Eventual Reactivation Under Recovery Property v1 (ERUR)

## Status

Accepted (2026-06-09).

## Context

ADR-0031 estableció BAUD-v1: bajo la policy pair de referencia, cuando
los outcomes recientes señalan deriva, el agente no emite acciones no
conservadoras. Cita defendible. Verifier público (`verify_baud`).
Evidence en cada smoke run.

Pero BAUD-v1 sola es **vacuosamente satisfecha** por una policy
degenerada: "siempre emite HOLD." Esa policy nunca emite PROCEED, así
que nunca emite PROCEED bajo precondición de drift detectado. La
postcondición de BAUD es trivialmente verdad.

Lo que falta es la dirección inversa: cuando la señal de deriva
**desaparece**, el agente debe poder reanudar PROCEED. Sin esa
afirmación complementaria, la safety claim de Ghost es una solo de las
dos hojas del lazo de control:

| Dirección | Claim | ADR |
|---|---|---|
| Drift detectado → no PROCEED | BAUD-v1 | 0031 |
| Drift ausente → PROCEED | ERUR-v1 | **este** |

Juntas, las dos forman la afirmación completa: *la calibration policy
de referencia sigue correctamente la señal de deriva en ambas
direcciones*, y nada degenerado pasa el filtro.

La "eventual" del nombre viene del mecanismo de ventana de
`build_calibration_history` (ADR-0026): outcomes viejos caen fuera del
buffer (`max_history`), así que la condición de downgrade deja de
cumplirse "eventualmente" — el cuándo exacto depende de `W`. ERUR-v1
no acota ese cuándo (eso queda para una propiedad de latencia futura);
solo afirma que **cuando la condición de drift no se cumple, el
comportamiento es correcto**.

## Decision

### 1. Property statement (ERUR-v1)

Definiciones (reutilizadas de ADR-0031, mismo cycle index, mismas
notaciones):

- `H_t`, `C_t`, `D_t`, `A_t`, `raw_t` — como en ADR-0031 §1.
- **Drift-clean snapshot at t**: la condición de downgrade de
  `MahalanobisDowngradePolicy(M, K)` **no se cumple** sobre `H_t`. Por
  De Morgan, expansión literal:

  ```
  H_t.outcomes_considered < M
    OR  H_t.count_beyond_3_std + H_t.count_beyond_5_std < K
  ```

  Es la negación literal de la precondición de BAUD-v1; el calibrador
  de referencia bajo esta condición hace passthrough (no downgrade).
- **Raw-known cycle**: `raw_t.overall_level == SelfAssessmentLevel.KNOWN`.

#### Property ERUR-v1 (precondition / postcondition)

> Sea una ejecución `E` de la closed-loop pipeline con la misma policy
> pair de BAUD-v1:
>
> - `P_cal = MahalanobisDowngradePolicy(min_outcomes=M, downgrade_threshold=K)`
> - `P_dec = UncertaintyAwareReferencePolicy` (semantics ADR-0027)
> - `P_act = ReferenceActionEmissionContract` (ADR-0023)
>
> **Si** existe un ciclo `t` donde simultáneamente:
>
> 1. `H_t` es drift-clean (snapshot no cumple la condición de
>    downgrade).
> 2. `raw_t.overall_level == KNOWN`.
>
> **entonces** en ese mismo ciclo `t`:
>
> 1. `C_t.adjusted_overall_level == KNOWN`. (La policy de calibración
>    NO degrada el level — passthrough.)
> 2. `D_t.decision.kind == DecisionKind.PROCEED`. (La policy de
>    decisión emite la única kind compatible con effective_level =
>    KNOWN por la tabla de ADR-0027.)

#### Por qué no hay postcondición sobre `A_t`

A diferencia de BAUD, ERUR-v1 no afirma nada sobre `A_t.actuator_command`.
Razón: cuando la decisión es PROCEED, el contrato ADR-0023 admite
legítimamente cualquier shape de comando (incluyendo `None`, atttitude,
direct motor — son todos válidos para una decisión de avanzar).
Restringir el shape sería confundir "policy de actuación de referencia"
con "lo que ERUR-v1 garantiza." Cada policy de actuación tiene su
propia firma; ERUR-v1 se mantiene en el nivel de la decisión.

#### Witness (verificación third-party)

Los datos requeridos están todos in-line en canales existentes:

- `H_t.count_beyond_*_std`, `raw_t.overall_level` y
  `C_t.adjusted_overall_level` están en `C_t` que viaja por
  `/self_assessment/calibrated`.
- `D_t.decision.kind` viaja inline en `A_t` (`/actuations`) por
  ADR-0023.

El verificador ERUR reduce a:

```
for t in cycle_indices(mcap):
    C = read_calibrated_assessment_at(mcap, t)
    H = C.calibration_history
    raw = C.raw_assessment
    beyond_3_or_worse = H.count_beyond_3_std + H.count_beyond_5_std
    drift_clean = (
        H.outcomes_considered < M
        or beyond_3_or_worse < K
    )
    if drift_clean and raw.overall_level == KNOWN:
        A = read_actuation_at(mcap, t)
        # Postcondition 1
        assert C.adjusted_overall_level == KNOWN
        # Postcondition 2
        assert A.decision.kind == PROCEED
```

Reproducible byte-exacto por construcción (ADR-0030).

### 2. Scope — what ERUR-v1 claims and does NOT claim

**ERUR-v1 claims (v1):**

- Una condición suficiente, computable y local-en-tiempo bajo la cual
  el agente reanuda PROCEED.
- Una verificación third-party byte-exacta desde el MCAP.

**ERUR-v1 does NOT claim (v1):**

- **Reactivation latency**: ERUR-v1 no acota cuántos ciclos pasan
  entre el último outcome over-threshold y el ciclo donde la condición
  drift-clean se cumple. Eso depende del tamaño de ventana `W` usado
  por `build_calibration_history` (ADR-0026 §X) y del patrón de
  outcomes recientes. Una propiedad de latencia es un candidato
  separado.
- **Recovery bajo raw != KNOWN**: ERUR-v1 sólo afirma comportamiento
  cuando el assessment crudo dice KNOWN. Si el raw es UNCERTAIN
  (covarianza grande, por ejemplo), la decisión NO sería PROCEED
  aunque la deriva esté limpia — y eso es correcto. ERUR-v1 no entra
  en esa rama.
- **Soundness inversa**: ERUR-v1 no afirma "si los outcomes están
  realmente dentro de 1σ, la condición se cumple." La sensibilidad
  del detector frente al ruido real (false negatives) sigue siendo
  propiedad separada.
- **Robustez a policies no-reference**: como BAUD-v1, ERUR-v1 está
  enunciada sobre las policies de referencia. Custom policies
  requieren su propia variante.

### 3. Relación con BAUD-v1 (complementariedad)

ERUR-v1 y BAUD-v1 dividen el plano `(H_t drift-clean?, raw_t known?)`
en cuadrantes:

| H drift-clean | raw KNOWN | Aplica |
|---|---|---|
| no            | KNOWN     | BAUD-v1 (P1: ¬KNOWN, P2: ¬PROCEED) |
| no            | ¬KNOWN    | BAUD-v1 (P1: ¬KNOWN trivial, P2: ¬PROCEED) |
| sí            | KNOWN     | **ERUR-v1** (P1: KNOWN, P2: PROCEED) |
| sí            | ¬KNOWN    | (ninguna aplica — passthrough trivial) |

Una policy degenerada "siempre HOLD" satisface BAUD-v1 vacuamente
**pero falla ERUR-v1**: el cuadrante (sí, KNOWN) exige PROCEED y la
degenerada emite HOLD. Cierra el vacío de BAUD.

### 4. Verification plan

Mismo patrón triple que BAUD-v1.

#### 4.1 Verifier público (`src/project_ghost/properties/erur.py`)

`verify_erur(mcap_path, *, min_outcomes=M, downgrade_threshold=K) →
ERURVerificationReport`. API simétrica a `verify_baud`. Reutiliza el
helper de SHA-256 y la lógica de iteración por ciclos.

Reporte:

```python
@dataclass(frozen=True)
class ERURVerificationReport:
    mcap_sha256: str
    min_outcomes: int            # M used
    downgrade_threshold: int     # K used
    cycles_total: int
    cycles_precondition_held: int   # drift-clean AND raw-known
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[ERURViolation, ...]
    property_version: str        # "ERUR-v1"

    @property
    def holds(self) -> bool:
        return len(self.violations) == 0
```

`ERURViolation` clasifica el ciclo, la postcondición fallida, y los
valores observados (mismo posture que `BAUDViolation`).

#### 4.2 Sanity tests (`tests/properties/test_verify_erur_smoke.py`)

Sobre el smoke real (10 cycles, 5 m/s drift, M=4, K=2):

- Ciclos 1-4: outcomes_considered < M ⇒ drift-clean ⇒ ERUR aplica si
  raw es KNOWN. Y raw es KNOWN porque la covarianza declarada es
  pequeña. ⇒ ERUR debe disparar en ciclos 1-4 y sostenerse.
- Ciclos 5-10: `count_beyond_3_or_worse ≥ K` ⇒ NO drift-clean ⇒ ERUR
  no aplica. (BAUD aplica en su lugar.)
- Expected: `report.cycles_precondition_held >= 4`, `report.holds`.

#### 4.3 Hypothesis property test (`tests/properties/test_erur_property.py`)

Mismo shape que el property test de BAUD: genera
`(M, K, CalibrationHistory)` synthetic, ejecuta single-cycle a través
de la policy pair real, materializa MCAP, llama `verify_erur`, asserta
`report.holds`. Para cubrir el dominio interesante de ERUR el strategy
de history debe poder generar tanto drift-clean como over-threshold
snapshots; el property test ya tolera trivialmente los casos donde la
precondición no aplica (`cycles_precondition_held == 0` ⇒ `holds`
trivial).

Más adversarial:

- *recovery from drift*: history con `count_beyond_5_std == K` pero
  los `count_beyond_3_std + count_beyond_5_std` reducidos por exclusion
  de outcomes viejos — boundary del K threshold.
- *raw_uncertain skip*: raw assessment levels UNCERTAIN/UNKNOWN —
  ERUR no debe aplicar.

#### 4.4 Inline en smoke

`SmokeSummary` gana `erur_report: ERURVerificationReport`. CLI imprime
`ERUR-v1: HOLDS  (cycles eval)`. Integration test asserts
`summary.erur_report.holds`. Mismo patrón que BAUD-v1 §3.2.

### 5. Reporting

`ERURVerificationReport` sigue el mismo shape que `BAUDVerificationReport`
para que el código de consumo sea estructuralmente paralelo. `holds is
True` para toda ejecución de la policy pair de referencia; cualquier
`holds is False` es un bug del agente, no del verificador.

## Consequences

### Positivas

- **Cierra el agujero degenerado de BAUD-v1.** La policy "siempre
  HOLD" deja de satisfacer las dos propiedades juntas.
- **Frase citable completa**: "Project Ghost satisface BAUD-v1 y
  ERUR-v1 bajo la policy pair de referencia — el agente para cuando
  debe parar y reanuda cuando puede reanudar." Esto es exactamente la
  asimetría de safety que falta en la literatura aplicada.
- **Patrón de propiedad simétrica establecido**. Futuras
  ADRs siguen el molde (precondición → postcondición → verifier →
  smoke witness → property test) y se componen sin reabrir nada.
- **Smoke evidence reforzado**: cada commit del proyecto produce
  evidencia inline de las DOS direcciones del lazo, no solo una.

### Negativas / costos

- **Doble verificación inline en el smoke**: cada run ejecuta
  `verify_baud` Y `verify_erur`. Cada uno re-lee el MCAP. Costo
  marginal (~milisegundos en MCAPs de 10 cycles) pero no cero.
- **Riesgo de propiedades-complementarias-falsas-positivas**: si
  alguna vez se enmienda el calibrador para tener hysteresis (no
  passthrough inmediato cuando el window limpia), ERUR-v1 deja de
  aplicar y haría falta ERUR-v2. Igual que BAUD, el compromiso
  semántico está fijado a la versión actual de la policy.
- **El smoke de referencia exercita ERUR débilmente** porque su
  escenario es drift sostenido (no recovery). La cobertura fuerte
  vive en el property test, no en el smoke. Un escenario complementario
  *drift-then-recovery* es candidato a smoke separado (no ADR, solo
  ejemplo).

## Alternatives considered

1. **Strict reactivation latency bound** — "después de N ciclos de
   outcomes within_1_std, el agente DEBE emitir PROCEED." Rechazado
   por v1 porque depende de la window size `W` (parámetro de
   `build_calibration_history`, no del policy). Una propiedad de
   latencia requiere fijar W como parte del enunciado, ampliando el
   compromiso semántico más allá del mínimo necesario.
2. **Monotonicidad estricta del calibrador** — "el adjusted_level
   nunca sube." Más restrictiva pero ortogonal: dice algo sobre el
   shape de la trayectoria del nivel, no sobre la correctitud frente a
   la señal. Candidata a ADR-0033 si se decide formalizar.
3. **Property estadística (false-negative rate)** — "bajo ruido
   gaussiano puro con covarianza declarada, ERUR aplica al menos en
   1-ε de los ciclos." Requiere modelo probabilístico explícito y
   simulación Monte Carlo. Fuera del scope de v1.
4. **Enunciar ERUR sobre el calibrator únicamente** (sin el decision
   policy). Rechazado: el valor citable de ERUR es la garantía
   *end-to-end* — que la cadena entera reanuda PROCEED. Enunciar sólo
   sobre el calibrator pierde ese hilo.

## Implementation roadmap (informational, not binding)

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | ✅ done |
| 2 | `src/project_ghost/properties/erur.py` con `verify_erur` + `ERURVerificationReport` + `ERURViolation` + `ERURViolationKind` | ✅ done |
| 3 | `tests/properties/test_verify_erur_smoke.py` — 9 sanity tests sobre smoke MCAP real (incluido partition test BAUD+ERUR) | ✅ done |
| 4 | `tests/properties/test_erur_property.py` — Hypothesis property test (200 examples) + 5 adversarial scenarios | ✅ done |
| 5 | `SmokeSummary.erur_report` inline + CLI imprime `ERUR-v1: HOLDS` + 2 integration tests (inline + partition) | ✅ done |
| 6 | Lift ADR a Accepted | ✅ done — este commit |

Notas de ejecución (post-implementación):

- El primer sanity test del paso 3 (partition) detectó un bug
  semántico en mi enunciado original: la precondición `drift_clean
  := count_beyond_3_or_worse < K` dejaba una banda de ciclos donde
  el K threshold se alcanzaba pero el M-guard aún no, y ni BAUD ni
  ERUR firaban. La corrección fue expandir `drift_clean` a la
  negación literal completa de BAUD por De Morgan:
  `outcomes_considered < M OR count_beyond_3_or_worse < K`. ADR
  enmendado in-place en §1; verifier actualizado a usar ambos
  parámetros M y K en la precondición.
- El partition test (`baud + erur == total`, sin solapamiento) es la
  evidencia estructural de que las dos propiedades cubren entre
  ambas todo el espacio de comportamiento del policy pair de
  referencia bajo el smoke. Sin esa partición, la afirmación de
  bidirección sería incompleta.

## References

- ADR-0021 — Belief-to-Action Contract Layer v1
- ADR-0023 — Action Emission Contract Layer v1
- ADR-0026 — Closed-Loop Feedback v1 (window mechanism)
- ADR-0027 — Calibration-Aware Decision Context v1
- ADR-0030 — Replay Verification v1
- ADR-0031 — Bounded Action Under Drift Property v1 (complementary)
- `src/project_ghost/core/feedback/reference_policy.py` —
  `MahalanobisDowngradePolicy`
- `src/project_ghost/core/decisions/reference_policy.py` —
  `UncertaintyAwareReferencePolicy`
- `src/project_ghost/properties/baud.py` — estructural pattern del
  verifier
