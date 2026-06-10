# ADR-0031 — Bounded Action Under Drift Property v1 (BAUD)

## Status

Accepted (2026-06-09).

## Context

ADRs 0020 → 0030 han construido una pipeline cerrada de extremo a extremo:
self-assessment crudo (ADR-0020) → contrato belief→action (ADR-0021) →
verificación de trace (ADR-0022) → contrato de emisión de acción
(ADR-0023) → predicción forward (ADR-0024) → divergencia
predicción-observación (ADR-0025) → feedback de calibración (ADR-0026)
→ contexto de decisión calibration-aware (ADR-0027) → fusion contract
(ADR-0028) → controlador de trayectoria de referencia (ADR-0029) →
replay verification (ADR-0030).

El sistema **funciona**. Está probado por componente, hay smoke tests
de extremo a extremo, los logs son byte-exactos replayables. Pero hasta
este ADR el proyecto **no enuncia ni demuestra ninguna propiedad
formal del comportamiento del lazo**. Toda afirmación sobre seguridad
es operacional ("estos tests pasan") y no es citable como garantía.

Esto es el cuello de botella entre **referencia bien construida** e
**infraestructura**. Una referencia bien construida se mira y se
adapta; una infraestructura se cita. Para citar hace falta una frase
falsificable que se pueda demostrar y referenciar:

> "Si usas Ghost configurado de tal manera, se cumple la propiedad X."

ADR-0031 introduce la primera propiedad de ese tipo: **Bounded Action
Under Drift** (BAUD). Es deliberadamente la más simple de las
propiedades candidatas — antes de añadir más (monotonicidad de
degradación, no-falsos-positivos bajo ruido puro, replay-determinism
bajo input adversarial), conviene establecer el patrón con una
propiedad que sea:

1. Trivialmente falsificable: un contraejemplo se detecta en un solo
   ciclo.
2. Anclada en código existente: no requiere nuevas abstracciones.
3. Witness-able: el testigo cabe en el MCAP actual sin nuevos
   schemas masivos.
4. Útil: cierra una pregunta operacional concreta ("¿cuándo deja el
   agente de emitir órdenes activas?").

## Decision

### 1. Property statement (BAUD-v1)

Definiciones (todas refieren a tipos congelados ya existentes):

- **Cycle index** `t ∈ ℕ` — ordenamiento determinista de ciclos del
  lazo cerrado tal como se materializa en el MCAP por
  `log_time_sim_ns` ascendente por canal.
- **Calibration snapshot at t** `H_t` —  el `CalibrationHistory`
  (ADR-0026) consumido por la calibration policy en el ciclo `t`.
  Construido por `build_calibration_history` desde los outcomes
  cronológicamente anteriores a `t`.
- **Calibrated assessment at t** `C_t` — el `CalibratedSelfAssessment`
  emitido en `/self_assessment/calibrated` con stamp del ciclo `t`.
- **Decision at t** `D_t` — el `DecisionRationale` emitido en
  `/decisions` con stamp del ciclo `t`.
- **Actuation at t** `A_t` — la `ActuationDirective` emitida en
  `/actuations` con stamp del ciclo `t`.
- **Policy pair** `(P_cal, P_dec, P_act)` — la tupla calibration
  policy, decision policy, action emission policy efectivamente
  wireada en la ejecución.

#### Property BAUD-v1 (precondition / postcondition)

> Sea una ejecución `E` de la closed-loop pipeline con policy pair:
>
> - `P_cal = MahalanobisDowngradePolicy(min_outcomes=M, downgrade_threshold=K)`
> - `P_dec = UncertaintyAwareReferencePolicy` (semantics ADR-0027)
> - `P_act = ReferenceActionEmissionContract` (ADR-0023)
>
> **Si** existe un ciclo `t` donde:
>
> ```
> H_t.outcomes_considered ≥ M
> ∧ H_t.count_beyond_3_std + H_t.count_beyond_5_std ≥ K
> ```
>
> **entonces** en ese mismo ciclo `t` se cumplen simultáneamente:
>
> 1. `C_t.adjusted_overall_level ∈ {UNCERTAIN, UNKNOWN}` (no KNOWN).
> 2. `D_t.decision.kind ≠ PROCEED`. (Las otras seis kinds —
>    `HOLD`, `ABSTAIN_UNCERTAIN`, `YIELD_TO_PILOT`, `ENGAGE_RTL`,
>    `ENGAGE_LAND`, `ENGAGE_KILL` — son todas legales bajo BAUD.)
> 3. **Si `A_t.actuator_command is not None`**, entonces
>    `A_t.reason ∈ S_baud_v1` donde `S_baud_v1` es el conjunto cerrado de
>    razones registradas como safe-for-non-proceed (sub-sección 1.1).

#### 1.1 Safe-for-non-proceed reason set `S_baud_v1`

Bajo HOLD u otros kinds no-PROCEED, emitir `actuator_command is None`
es **operacionalmente inseguro** en muchos dominios: un vehículo aéreo
sin comando corriente deriva, no se queda quieto. El contrato ADR-0029
explícitamente mapea HOLD a un `AttitudeCommand(identity, hold_thrust)`
— un comando que ordena al vehículo mantenerse en su orientación
actual sin translación — para resolver esa asimetría.

BAUD-v1 reconoce esa realidad fijando un conjunto cerrado de
`Decision.reason` strings que el verifier acepta como
safe-for-non-proceed:

```
S_baud_v1 = {
    "attitude_hold_hold",   # ADR-0029: identity attitude + bounded thrust
    "kill_zero_throttle",   # ADR-0029: zero throttle DirectMotor on ENGAGE_KILL
}
```

Cualquier comando non-None bajo no-PROCEED con un `reason` fuera de
`S_baud_v1` es violación de la postcondición 3. La taxonomía de
`Decision.reason` es snake_case cerrada-por-disciplina (ADR-0021), lo
que hace este whitelist verificable estáticamente.

Cualquier ampliación del set requiere un ADR amendment explícito —
añadir una nueva razón con justificación de por qué su efecto físico
es conservador bajo drift detectado.

#### Witness (verificación third-party)

Para todo ciclo `t` donde BAUD aplica, el MCAP de la ejecución
contiene los registros suficientes para que un tercero, sin
re-ejecutar el pipeline, verifique la propiedad:

- `H_t` está inline en `C_t.calibration_history`
  (`/self_assessment/calibrated`).
- `C_t.adjusted_overall_level` está inline en `C_t`.
- `D_t.decision.kind` está inline en `D_t` (`/decisions`).
- `A_t.actuator_command` está inline en `A_t` (`/actuations`).
- El stamp `t` correlaciona los cuatro records.

El verificador BAUD reduce a:

```
for t in cycle_indices(mcap):
    H = read_calibration_history_at(mcap, t)
    if H.outcomes_considered >= M and \
       H.count_beyond_3_std + H.count_beyond_5_std >= K:
        C = read_calibrated_assessment_at(mcap, t)
        A = read_actuation_at(mcap, t)
        # Postcondition 1
        assert C.adjusted_overall_level != KNOWN
        # Postcondition 2 (decision travels inline in A)
        assert A.decision.kind != PROCEED
        # Postcondition 3
        if A.actuator_command is not None:
            assert A.reason in S_baud_v1
```

Por construcción esto es byte-exacto y reproducible (ADR-0030).

### 2. Scope — what BAUD claims and does NOT claim

**BAUD claims (v1):**

- Una condición suficiente, computable y local-en-tiempo (un ciclo)
  bajo la cual el agente no emite acciones no-conservadoras.
- Una verificación third-party byte-exacta desde el MCAP de cualquier
  ejecución.

**BAUD does NOT claim (v1):**

- **Soundness inversa / completeness**: BAUD no dice "si hay drift
  real, BAUD se dispara". La detección depende de la elección de
  parámetros (`M`, `K`) y de la ventana usada por
  `build_calibration_history`. La sensibilidad/recall del detector es
  una propiedad separada (candidata a ADR-0032).
- **Detection latency bound**: BAUD no acota el número de ciclos
  entre la primera anomalía real del modelo y el ciclo `t` donde se
  cumple la precondición. Eso depende del tamaño de ventana y del
  patrón de errores.
- **Robustez a policies no-reference**: una calibration policy custom
  (cualquier implementación del `Protocol` de ADR-0026) está fuera
  del scope de BAUD-v1. Una propiedad análoga puede demostrarse para
  policies custom enunciando explícitamente la nueva condición; cada
  variante requiere una nueva versión (BAUD-v2, etc.).
- **Recuperación**: BAUD no dice nada sobre cuándo el agente vuelve a
  emitir PROCEED después de que la deriva remite. Esa es una
  propiedad complementaria (candidata: *Eventual Reactivation Under
  Recovery*).

### 3. Verification plan

Tres mecanismos complementarios, todos opt-in, todos byte-exactos:

#### 3.1 Hypothesis property test (`tests/properties/test_baud_v1.py`)

Test property-based con Hypothesis que:

- Genera ejecuciones sintéticas con parámetros `(M, K)` aleatorios en
  un rango razonable y secuencias de outcomes adversariales.
- Corre el lazo cerrado real (`run_closed_loop_smoke` o variante con
  outcomes inyectados deterministically).
- Para cada ciclo del MCAP resultante, evalúa la precondición BAUD y
  asserta las tres postcondiciones.
- Reporta también el número de ciclos donde la precondición se
  cumple y la primera ocurrencia — útil para regresión.

#### 3.2 Witness verifier (`src/project_ghost/properties/baud.py`)

Función pura `verify_baud(mcap_path, *, M, K) -> BAUDVerificationReport`
que:

- Lee el MCAP target.
- Evalúa BAUD en cada ciclo.
- Retorna un report con: número de ciclos verificados, número de
  ciclos donde aplicó la precondición, lista de violaciones (vacía si
  la propiedad se mantiene), y el SHA-256 del MCAP source.

Esta función es la **superficie citable**: un tercero puede ejecutar
`verify_baud` contra cualquier MCAP de Ghost y obtener un veredicto.

#### 3.3 Adversarial scenarios (`tests/properties/test_baud_adversarial.py`)

Suite explícita de escenarios diseñados para intentar romper BAUD,
todos deben verificar:

- *outcome storm*: ráfaga de outcomes `BEYOND_5_STD` justo en el
  borde de la ventana — verifica que la propiedad fira en cuanto se
  cumple la condición.
- *border outcome*: exactamente `K-1` outcomes beyond_3 — verifica
  que BAUD NO se dispara cuando no debe (precondición no cumplida).
- *recovery and re-drift*: deriva → recuperación → deriva — verifica
  que BAUD vuelve a aplicar en la segunda deriva.
- *interleaved sigma bands*: mezcla de `beyond_1`, `beyond_3`,
  `beyond_5` — verifica que sólo cuentan `beyond_3 + beyond_5`.

### 4. Reporting

Cuando `verify_baud` se ejecuta sobre un MCAP, produce un
`BAUDVerificationReport` con el shape:

```python
@dataclass(frozen=True)
class BAUDVerificationReport:
    mcap_sha256: str
    min_outcomes: int            # M used
    downgrade_threshold: int     # K used
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle: int | None
    violations: tuple[BAUDViolation, ...]
    property_version: str        # "BAUD-v1"

    @property
    def holds(self) -> bool:
        return len(self.violations) == 0
```

`BAUDViolation` identifica el ciclo, qué postcondición falló, y los
valores observados. Por construcción `holds is True` para toda
ejecución que use la policy pair de referencia. Cualquier `holds is
False` es un bug del agente, **no** del verificador.

## Consequences

### Positivas

- **Una afirmación citable**: "Project Ghost satisface BAUD-v1 bajo la
  policy pair de referencia." Esta es la primera frase del proyecto
  que es a la vez precisa, falsificable y demostrable.
- **Verificador como API pública**: `verify_baud` es una superficie
  de uso clara para investigadores y operadores. Permite que terceros
  validen MCAPs producidos por *cualquier* sistema que pretenda
  implementar Ghost.
- **Base para más propiedades**: una vez establecido el patrón
  (ADR + verifier + tests adversariales + witness en MCAP), añadir
  BAUD-v2, monotonicidad, eventual-reactivation, etc., es trabajo
  paralelizable e incremental.
- **Closes the originality gap**: pasa de "buena referencia de un
  patrón conocido" a "única implementación que enuncia y demuestra
  una propiedad formal de bound-on-action bajo drift detectado." La
  propiedad en sí no es novedosa teóricamente (es una consecuencia
  inmediata del contrato de ADR-0027); lo novedoso es que esté
  **enunciada, verificada y replayable** end-to-end en un sistema
  abierto.

### Negativas / costos

- **Compromiso semántico**: la formulación de BAUD-v1 fija el
  significado del contrato calibration-aware al de ADR-0027. Si
  ADR-0027 se enmienda con un mapping distinto
  (`UNCERTAIN → PROCEED`, por ejemplo) BAUD-v1 deja de aplicar; haría
  falta BAUD-v2.
- **Riesgo de propiedad trivial**: BAUD es deliberadamente sencilla.
  No es difícil que la satisfaga el código actual — eso es feature,
  no bug, pero conviene que el siguiente ADR aborde una propiedad
  no-trivial (típicamente recall/sensibilidad del detector) para
  evitar la percepción de teorema-tautológico.
- **Mantenimiento del verificador**: `verify_baud` debe mantenerse en
  paralelo a cualquier cambio en los schemas de `CalibrationHistory`,
  `CalibratedSelfAssessment`, `DecisionRationale` o
  `ActuationDirective`. El acoplamiento es explícito y vivirá en
  `tests/properties/` con el resto.

## Alternatives considered

1. **Monotonic Degradation** — "la calibration policy nunca upgrade
   un level basándose en outcomes; sólo downgrade o pass-through".
   Más restrictiva pero menos útil operacionalmente: dice algo sobre
   el calibrador, no sobre el agente. Candidata a propiedad
   siguiente.
2. **Replay Determinism Under Adversarial Input** — "para cualquier
   input adversarial bien-formado, el byte-exact replay coincide con
   la ejecución original." Es lo más cercano a la propiedad ya
   demostrada por ADR-0030; explicitarla como propiedad formal es
   incremental.
3. **False Positive Bound** — "bajo ruido gaussiano puro de los
   sensores, la probabilidad de que BAUD se dispare espuriamente es
   ≤ ε". Requiere un modelo probabilístico del ground truth y queda
   mejor servida por una propiedad estadística separada (no
   property-based testing sino simulación Monte Carlo). Posible
   ADR-0033.
4. **Empezar por una propiedad más ambiciosa directamente** (ej.
   detection latency bound). Rechazado por riesgo: si BAUD-v1 no
   puede establecerse limpiamente, propiedades más ambiciosas
   tampoco. BAUD-v1 valida el patrón con el menor compromiso.

## Implementation roadmap (informational, not binding)

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | ✅ done |
| 2 | `src/project_ghost/properties/{__init__,baud}.py` con `BAUDVerificationReport` + `verify_baud` | ✅ done |
| 3 | `tests/properties/test_verify_baud_smoke.py` — 9 sanity tests sobre smoke MCAP real | ✅ done |
| 4 | `tests/properties/test_baud_property.py` — Hypothesis property test (200 examples) + 5 adversarial scenarios | ✅ done |
| 5 | `SmokeSummary.baud_report` inline + CLI imprime `BAUD-v1: HOLDS` + integration test asegura `summary.baud_report.holds` | ✅ done |
| 6 | Lift ADR a Accepted | ✅ done — este commit |

Notas de ejecución (post-implementación):

- El verifier (paso 2) descubrió en el primer test que la postcondición
  3 original (``actuator_command is None``) era demasiado estricta:
  ``AttitudeHoldReferencePolicy`` (ADR-0029) emite legítimamente un
  ``AttitudeCommand(identity, hold_thrust)`` bajo HOLD porque
  operacionalmente es **más seguro** que un comando ausente (un dron
  sin comando deriva). El ADR fue enmendado in-place añadiendo la
  sub-sección §1.1 con el conjunto cerrado de razones safe-for-non-proceed
  ``S_baud_v1 = {attitude_hold_hold, kill_zero_throttle}``.
- El property test (paso 4) consolidó los pasos 3 y 4 del plan
  original en un único fichero porque comparten fixture y helpers, y
  los 5 escenarios adversariales son instancias específicas del mismo
  espacio que Hypothesis recorre. Reduce superficie cognitiva sin
  pérdida de cobertura.
- El escenario *recovery and re-drift* listado en §3.3 está fuera de
  scope de v1 porque es temporal (multi-cycle, requiere estado entre
  ciclos). Candidato natural para una propiedad complementaria
  *Eventual Reactivation Under Recovery* (mencionada en §2 fuera de
  scope).

## References

- ADR-0023 — Action Emission Contract Layer v1
- ADR-0025 — Prediction-Observation Divergence Check v1
- ADR-0026 — Closed-Loop Feedback v1
- ADR-0027 — Calibration-Aware Decision Context v1
- ADR-0030 — Replay Verification v1
- `src/project_ghost/core/feedback/reference_policy.py` —
  `MahalanobisDowngradePolicy`
- `src/project_ghost/core/decisions/reference_policy.py` —
  `UncertaintyAwareReferencePolicy`
