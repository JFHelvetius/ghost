# ADR-0033 — Monotonic Degradation Property v1 (MD)

## Status

Accepted (2026-06-09).

## Context

ADR-0031 (BAUD-v1) y ADR-0032 (ERUR-v1) cubren las dos direcciones
del lazo de control bajo la policy pair de referencia: el agente para
cuando debe parar y reanuda cuando puede reanudar. Las dos propiedades
son **conjuntamente verdad** del comportamiento *en el smoke*, pero
ambas son *condicionales*: cada una afirma postcondiciones cuando su
precondición se cumple, y trivialmente verdadera cuando no.

Hay una **propiedad incondicional** de la calibration policy de
referencia que ni BAUD ni ERUR enuncian: la policy nunca *crea
confianza*. Es decir, el `adjusted_overall_level` que emite nunca es
más confiado que el `raw.overall_level` que recibe.

Esto es delgado pero importante. El contrato de la calibration policy
(ADR-0026) explícitamente **no** restringe la dirección del ajuste:
*"Una policy puede legítimamente upgrade o downgrade el level. La
reference sólo hace passthrough o downgrade; otras policies pueden
hacer otra cosa."* Es decir, el contrato admite policies "upgraders"
que veían evidencia y deciden subir el nivel — algo muy peligroso en
contexto de safety: una calibration policy que *inventa confianza*
puede empujar la cadena de decisión a PROCEED donde no debería estar.

ADR-0033 enuncia la propiedad **Monotonic Degradation (MD-v1)**:

> Bajo la calibration policy de referencia
> `MahalanobisDowngradePolicy`, el ajuste es monótonamente
> conservador: el `adjusted_overall_level` está en el lattice de
> autoevaluación en una posición igual o más conservadora (menor o
> igual confianza) que el `raw.overall_level`.

La propiedad **es del policy específico**, no del contrato. Custom
policies pueden no satisfacerla — y ese es precisamente el punto.
MD-v1 hace explícito y verificable que la *reference* hace lo
prudente. Cualquier proyecto downstream que dependa de la reference
puede citar MD-v1 como contrato implícito; cualquier proyecto que use
una calibration policy custom debe declarar si la satisface o no.

Es la tercera de tres propiedades complementarias:

| Propiedad | Dirección | Naturaleza |
|---|---|---|
| BAUD-v1 (0031) | Drift detectado → no PROCEED | Condicional |
| ERUR-v1 (0032) | Drift ausente + KNOWN → PROCEED | Condicional |
| **MD-v1 (0033)** | **Adjusted no más confiado que raw** | **Incondicional** |

Las tres juntas establecen: *la policy pair de referencia detecta el
drift correctamente, reanuda correctamente, y nunca lo niega*. Es el
shape completo del comportamiento del calibrator más decisión.

## Decision

### 1. Property statement (MD-v1)

Definiciones:

- `C_t` — `CalibratedSelfAssessment` emitido en
  `/self_assessment/calibrated` con stamp del ciclo `t`.
- `raw_t := C_t.raw_assessment` — el raw assessment inline.
- `level_lattice` — la relación de orden total sobre
  `SelfAssessmentLevel`:

  ```
  KNOWN  <  UNCERTAIN  <  UNKNOWN
  ```

  Donde "<" significa "más confiado que." Numerificación canonical:
  `KNOWN=0, UNCERTAIN=1, UNKNOWN=2`. Mayor número = menos confianza.

#### Property MD-v1 (incondicional)

> Sea una ejecución `E` de la closed-loop pipeline con la calibration
> policy de referencia
> `MahalanobisDowngradePolicy(min_outcomes=M, downgrade_threshold=K)`.
>
> Para **todo** ciclo `t` presente en el MCAP:
>
> ```
> level_num(C_t.adjusted_overall_level)
>     >=
> level_num(raw_t.overall_level)
> ```
>
> Equivalentemente: el ajuste es passthrough o downgrade; nunca
> upgrade.

#### Por qué no hay precondición

A diferencia de BAUD y ERUR, MD-v1 no tiene precondición: aplica a
*todo* ciclo donde se emite un `CalibratedSelfAssessment`. La razón es
que MD-v1 enuncia una propiedad *estructural* del shape del ajuste,
no una de comportamiento condicionado a la historia de outcomes. Cada
`CalibratedSelfAssessment` lleva inline tanto el raw como el ajuste,
así que la condición a verificar es local al record.

Consecuencia: en el reporte, `cycles_precondition_held` siempre es
igual a `cycles_total` (precondición trivial). Mantenemos el campo
para mantener el shape paralelo a BAUD y ERUR; un consumer que itere
sobre las tres propiedades se beneficia de la simetría aunque cargue
con un campo redundante en MD.

#### Witness (verificación third-party)

Trivial: solo necesita `/self_assessment/calibrated`. La actuation y
decisión no entran en la postcondición. El verificador MD reduce a:

```
for t in cycle_indices(mcap):
    C = read_calibrated_assessment_at(mcap, t)
    raw = C.raw_assessment
    assert level_num(C.adjusted_overall_level) >= level_num(raw.overall_level)
```

Reproducible byte-exacto (ADR-0030).

### 2. Scope — what MD-v1 claims and does NOT claim

**MD-v1 claims (v1):**

- Una propiedad *estructural* de la calibration policy de referencia
  bajo cualquier valor de `(M, K)`.
- Una verificación third-party byte-exacta desde el MCAP.

**MD-v1 does NOT claim (v1):**

- **Que el contrato lo exija**: el contrato `CalibrationAdjustmentPolicy`
  (ADR-0026) explícitamente admite upgrades. MD-v1 es propiedad
  *de la reference*, no del contrato. Una policy custom que upgrade es
  legal por contrato pero falla MD-v1.
- **Monotonicidad temporal**: MD-v1 no dice nada sobre la trayectoria
  del adjusted level a lo largo del tiempo. El adjusted level puede
  subir y bajar entre ciclos (cuando la ventana cambia y el raw
  cambia). MD-v1 sólo afirma la relación raw → adjusted *en un solo
  ciclo*.
- **Optimalidad**: MD-v1 no dice que el downgrade sea apropiado, sólo
  que cuando se produce es en la dirección correcta (más conservador).
  Si el downgrade fuera espurio (false positive), MD-v1 lo aceptaría —
  esa es propiedad estadística separada (FPB).

### 3. Relación con BAUD-v1 y ERUR-v1

MD-v1 es *ortogonal*. BAUD y ERUR particionan el espacio de
comportamiento condicional; MD aplica a todos los ciclos
incondicionalmente. Concretamente, en un smoke run típico:

| Cycle | BAUD aplica | ERUR aplica | MD aplica |
|---|---|---|---|
| 1-4 (drift-clean) | no | sí | sí (raw=adj=KNOWN) |
| 5-10 (drift-detected) | sí | no | sí (raw=KNOWN, adj=UNCERTAIN) |

MD aplica siempre. BAUD y ERUR siguen siendo la *partición* del
comportamiento condicional; MD añade una *ortogonal* sobre el shape
del ajuste.

### 4. Verification plan

Mismo patrón triple que BAUD-v1 y ERUR-v1.

#### 4.1 Verifier público (`src/project_ghost/properties/md.py`)

`verify_md(mcap_path) → MDVerificationReport`. No parametrizado por
(M, K) — la propiedad es estructural, no parametrizada por la policy
config. Defaults para `min_outcomes` y `downgrade_threshold` se
incluyen en el reporte sólo para consistencia con BAUD/ERUR pero no
afectan la evaluación.

Reporte:

```python
@dataclass(frozen=True)
class MDVerificationReport:
    mcap_sha256: str
    property_version: str        # "MD-v1"
    cycles_total: int
    cycles_precondition_held: int  # == cycles_total trivially
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[MDViolation, ...]

    @property
    def holds(self) -> bool:
        return len(self.violations) == 0
```

`MDViolation` clasifica el ciclo, el raw level y el adjusted level
observados.

#### 4.2 Sanity tests (`tests/properties/test_verify_md_smoke.py`)

Sobre el smoke real:

- Cycles 1-4: raw=KNOWN, adjusted=KNOWN. MD: 0 >= 0 ✓.
- Cycles 5-10: raw=KNOWN, adjusted=UNCERTAIN. MD: 1 >= 0 ✓.
- Expected: `report.holds`, `report.cycles_precondition_held == 10`.

El smoke ejercita MD débilmente (raw siempre KNOWN). La cobertura
fuerte vive en el property test.

#### 4.3 Hypothesis property test (`tests/properties/test_md_property.py`)

Varía:

- `(M, K)` en rangos razonables (iguales a BAUD/ERUR).
- `CalibrationHistory` synthetic (mismo strategy).
- **Raw level**: `KNOWN`, `UNCERTAIN`, `UNKNOWN`. Es la nueva
  dimensión que MD necesita; el raw assessment se construye con tres
  fixtures distintos (uno por covarianza adecuada para cada
  threshold).

Materializa single-cycle MCAP, ejecuta la cadena real, verifica con
`verify_md`. Total esperado: ~600 ejemplos.

Más adversariales:

- *passthrough en cualquier nivel*: history empty + raw en los 3
  niveles. Adjusted == raw. MD holds trivialmente.
- *downgrade desde KNOWN*: history que dispara K threshold + raw =
  KNOWN. Adjusted = UNCERTAIN. MD: 1 >= 0 ✓.
- *downgrade desde UNCERTAIN*: igual con raw = UNCERTAIN. Adjusted =
  UNKNOWN. MD: 2 >= 1 ✓.
- *downgrade desde UNKNOWN (idempotente)*: igual con raw = UNKNOWN.
  Adjusted = UNKNOWN. MD: 2 >= 2 ✓.

#### 4.4 Inline en smoke

`SmokeSummary.md_report` inline. CLI imprime `MD-v1: HOLDS`. Mismo
patrón que BAUD/ERUR. Integration test asserts
`summary.md_report.holds`.

## Consequences

### Positivas

- **Propiedad ortogonal y citable**: "la calibration policy de
  referencia nunca crea confianza." Esto cierra un agujero retórico:
  sin MD, alguien podría argumentar "BAUD y ERUR no dicen nada sobre
  upgrades — ¿y si el calibrador *inventa* KNOWN?" Con MD-v1 esa
  pregunta tiene respuesta verificable.
- **Distingue contrato y reference**: el contrato admite upgrades; la
  reference no los hace. Tener una propiedad que pin la conducta
  *real* de la reference (mientras el contrato sigue siendo
  flexible) es exactamente el shape de afirmación que da
  granularidad a la promesa de safety.
- **Trío completo**: BAUD + ERUR + MD juntas describen el shape
  *completo* del comportamiento del policy pair de referencia: dos
  direcciones condicionales más una propiedad estructural
  incondicional. La frase citable se compacta a "Project Ghost
  satisface el trío BAUD-v1 / ERUR-v1 / MD-v1 bajo policy pair de
  referencia."

### Negativas / costos

- **Triple verificación inline en el smoke**: cada run ejecuta tres
  verifiers. Costo en milisegundos pero no cero. Aceptable en escala
  de tests, hay que medir si en escenarios grandes resulta caro.
- **Trivial bajo el smoke actual**: el smoke fija raw=KNOWN siempre,
  así que sólo ejercita las dos primeras filas del case-analysis (`raw
  KNOWN → adj {KNOWN, UNCERTAIN}`). Las otras filas (raw=UNCERTAIN o
  UNKNOWN) sólo se ejercitan en el property test.
- **Riesgo de propiedad obvia**: MD-v1 es estructural y muy directa
  de demostrar. Eso podría leerse como "teorema trivial". El
  contraargumento es que *no es obvia desde el contrato* — solo desde
  la implementación de la reference. Sin MD-v1 enunciada y verificada
  inline, una modificación accidental que introduzca un upgrade-path
  no sería caught por BAUD ni ERUR.

## Alternatives considered

1. **Monotonicidad temporal estricta** — "para cualquier dos ciclos
   consecutivos `t, t+1` con la misma raw level, `adjusted_{t+1}` ≥
   `adjusted_t`." Rechazado porque NO es verdad del reference
   calibrator: cuando la ventana evoluciona y la condición de
   downgrade deja de cumplirse, el adjusted level baja correctamente
   (ese es el comportamiento que ERUR-v1 captura). Una propiedad de
   monotonicidad temporal aplicaría a un calibrador *con histéresis*
   (sticky downgrade), no a la reference.
2. **MD enunciada sobre el contrato** — "todo policy de calibración
   debe satisfacer adjusted ≥ raw." Rechazado: el contrato ADR-0026
   admite upgrades por diseño (algunas policies futuras podrían usar
   evidencia exógena para subir el nivel). Restringir el contrato
   ahora cerraría puertas. MD-v1 se queda como propiedad *de la
   reference*; future policies opt-in al satisfacerla.
3. **Combinar MD-v1 con BAUD-v1 como una sola propiedad**. Rechazado:
   son afirmaciones de naturaleza distinta (BAUD condicional sobre
   outcome history, MD incondicional sobre raw→adjusted). Combinarlas
   pierde claridad de cita.

## Implementation roadmap (informational, not binding)

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | done at acceptance |
| 2 | `src/project_ghost/properties/md.py` con `verify_md` + `MDVerificationReport` | 1 sesión |
| 3 | `tests/properties/test_verify_md_smoke.py` — sanity tests sobre smoke MCAP real | 1 sesión |
| 4 | `tests/properties/test_md_property.py` — Hypothesis property test (varía raw level) + adversarial scenarios | 1 sesión |
| 5 | `SmokeSummary.md_report` inline + CLI imprime `MD-v1: HOLDS` + integration test | 1 sesión |
| 6 | Lift ADR a Accepted | tras pasos 2-5 |

## References

- ADR-0020 — Belief Self-Assessment v1 (`SelfAssessmentLevel` lattice)
- ADR-0026 — Closed-Loop Feedback v1 (contrato calibration policy)
- ADR-0031 — Bounded Action Under Drift Property v1 (complementary)
- ADR-0032 — Eventual Reactivation Under Recovery Property v1 (complementary)
- `src/project_ghost/core/feedback/reference_policy.py` —
  `MahalanobisDowngradePolicy` con su `_DOWNGRADE` map
