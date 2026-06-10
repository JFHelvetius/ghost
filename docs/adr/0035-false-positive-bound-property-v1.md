# ADR-0035 — False Positive Bound Property v1 (FPB)

## Status

Accepted (2026-06-09).

## Context

ADR-0031..0034 establecen cuatro propiedades del lazo cerrado:

- BAUD-v1 — condicional sobre drift detectado
- ERUR-v1 — condicional sobre drift ausente + KNOWN
- MD-v1 — incondicional estructural raw vs adjusted
- RLB-v1 — cuantitativa temporal sobre recovery latency

Todas son *cualitativas*: cada `report.holds` es booleano. Lo que
falta es una propiedad **cuantitativa observacional** — un witness
del *rate* al que BAUD se dispara sobre una ejecución concreta.

El nombre "False Positive Bound" remite a la propiedad estadística
clásica: bajo un modelo probabilístico del ground truth (e.g. ruido
gaussiano puro con covarianza declarada), la probabilidad de que
BAUD se dispare espuriamente debería estar acotada por algún ε pequeño.

Esa propiedad **estadística estricta** requiere infraestructura
significativa que está fuera del scope del repo actual:

- Modelo probabilístico explícito de outcomes.
- Simulación Monte Carlo con muestras suficientes.
- Hypothesis testing sobre la distribución observada vs teórica.

ADR-0035 se queda con la versión **empírica observacional** de la
afirmación: el verifier *mide* la fracción de ciclos donde BAUD
dispara su precondición sobre el MCAP, y la compara contra un
`max_fire_fraction` configurable. Es genuinamente útil para CI
(detectar regresiones de sensibilidad), y deja la versión
estadística estricta como ADR futuro (FPB-v2) cuando haya
infraestructura probabilística.

## Decision

### 1. Property statement (FPB-v1)

Definiciones:

- `cycles_total` — número de cycles con `CalibratedSelfAssessment`
  en el MCAP.
- `cycles_baud_fires` — número de cycles donde la precondición de
  BAUD-v1 se cumple, es decir, donde el `MahalanobisDowngradePolicy(M, K)`
  habría hecho downgrade.
- `fire_fraction = cycles_baud_fires / cycles_total`.

#### Property FPB-v1 (caller-bounded fire rate)

> Sea una ejecución `E` con la policy pair de referencia configurada
> con `(M, K)` y un `max_fire_fraction ∈ [0, 1]` proporcionado por
> el caller.
>
> ```
> fire_fraction(E) <= max_fire_fraction
> ```

#### Por qué un bound observacional (no estadístico)

FPB-v1 *no* afirma que la tasa de disparo bajo ruido aleatorio es
pequeña. Eso requiere modelo probabilístico y muestreo Monte Carlo —
ambas son piezas que no están en el repo. Lo que FPB-v1 sí proporciona
es un observador empírico al que el caller puede atarle un bound:

- **Como puro observador** (`max_fire_fraction=1.0`, default): nunca
  falla. Reporta la fracción observada. Útil en CI para detectar
  cuando un refactor cambia la sensibilidad de BAUD (la fracción
  sube o baja inesperadamente).
- **Como regression gate** (caller fija el bound): pinea el
  comportamiento de BAUD para detectar regresiones. Por ejemplo, en
  el smoke baseline, `fire_fraction = 0.6`. Si después de un refactor
  baja a 0.4, el caller con `max_fire_fraction=0.5` lo detecta
  y debe investigar antes de aceptar.

FPB-v1 es así una *propiedad calibrable*, no booleana absoluta. El
juicio sobre qué es aceptable queda con el caller; el verifier
proporciona el dato exacto.

#### Witness (verificación third-party)

Trivial: solo necesita `/self_assessment/calibrated`. El verifier
itera por cada `CalibratedSelfAssessment`, evalúa la precondición de
BAUD-v1 sobre la `CalibrationHistory` inline, cuenta cuántas veces se
cumple:

```
fires = 0
total = 0
for t in cycle_indices(mcap):
    C = read_calibrated_assessment_at(mcap, t)
    H = C.calibration_history
    total += 1
    beyond_3_or_worse = H.count_beyond_3_std + H.count_beyond_5_std
    if H.outcomes_considered >= M and beyond_3_or_worse >= K:
        fires += 1
fire_fraction = fires / total
assert fire_fraction <= max_fire_fraction
```

Reproducible byte-exacto (ADR-0030).

### 2. Scope — what FPB-v1 claims and does NOT claim

**FPB-v1 claims (v1):**

- La fracción empírica de ciclos donde BAUD dispara en un MCAP
  específico, computada determinísticamente.
- Una comparación contra un bound user-configurable.

**FPB-v1 does NOT claim (v1):**

- **Bound estadístico bajo ruido gaussiano**: no hay modelo
  probabilístico. La afirmación "bajo Gaussian puro la tasa es ≤ ε"
  queda para una FPB-v2 futura con infraestructura Monte Carlo.
- **Que la tasa observada sea "buena"**: el verifier no hace juicio
  sobre si una tasa es aceptable. Eso es responsibility del caller.
- **Que las disparadas sean "falsos positivos"**: la fracción
  observada incluye tanto verdaderos positivos (drift real, como en
  el smoke) como falsos. El verifier no puede distinguir desde la
  MCAP sola.

### 3. Relación con BAUD-v1..RLB-v1

FPB-v1 es **observacional sobre BAUD**. Re-evalúa la misma
precondición que BAUD para CONTAR, no para postcondicionar.

| Propiedad | Naturaleza | Fire-rate visible? |
|---|---|---|
| BAUD-v1 (0031) | Pass/fail por ciclo | Implícita en `cycles_precondition_held` |
| ERUR-v1 (0032) | Pass/fail por ciclo | (No relevante) |
| MD-v1 (0033) | Pass/fail por ciclo | (No relevante) |
| RLB-v1 (0034) | Pass/fail por recovery transition | (No relevante) |
| **FPB-v1 (0035)** | **Cuantitativa observacional** | **Explícita** |

FPB-v1 expone explícitamente `fire_fraction` como métrica
top-level del reporte. Es el primer reporte del set que tiene un
campo float numérico (los anteriores solo tienen counts enteros).

### 4. Verification plan

#### 4.1 Verifier público (`src/project_ghost/properties/fpb.py`)

`verify_fpb(mcap_path, *, min_outcomes=4, downgrade_threshold=2,
max_fire_fraction=1.0) → FPBVerificationReport`.

Reporte:

```python
@dataclass(frozen=True)
class FPBVerificationReport:
    mcap_sha256: str
    min_outcomes: int
    downgrade_threshold: int
    max_fire_fraction: float
    property_version: str        # "FPB-v1"
    cycles_total: int
    cycles_precondition_held: int  # cycles BAUD fires
    fire_fraction: float
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[FPBViolation, ...]

    @property
    def holds(self) -> bool:
        return self.fire_fraction <= self.max_fire_fraction
```

`FPBViolation` se emite UN VEZ si la fraction excede el bound; carga
el observed fraction y el bound para diagnóstico.

#### 4.2 Sanity tests (`tests/properties/test_verify_fpb_smoke.py`)

Sobre el smoke (M=4, K=2, sustained drift):

- BAUD fires en 6 ciclos de 10 → `fire_fraction = 0.6`
- Con `max_fire_fraction = 1.0` (default): holds.
- Con `max_fire_fraction = 0.7`: holds (0.6 <= 0.7).
- Con `max_fire_fraction = 0.5`: NO holds (0.6 > 0.5).

El último caso es el "regression gate" útil: pinea el observed value.

#### 4.3 Hypothesis property test (`tests/properties/test_fpb_property.py`)

Genera `(M, K, max_fire_fraction, history)` y un MCAP single-cycle.
Asserta `verify_fpb` reporta `holds` iff la fraction observada (0 o 1
para un single-cycle MCAP) <= `max_fire_fraction`.

#### 4.4 Inline en smoke

`SmokeSummary.fpb_report` inline con `max_fire_fraction = 1.0`
(observador). CLI imprime `FPB-v1: HOLDS (fire_fraction=0.60)`.
Integration test asserts `holds` y pinea la fraction observada en 0.6
(regression gate del smoke baseline).

## Consequences

### Positivas

- **Quinta dimensión del set**: observacional cuantitativa.
  Complementa las cuatro qualitativas.
- **Regression gate natural**: el `fire_fraction` del smoke baseline
  queda pineado en CI. Cualquier refactor de la calibration policy
  que cambie su sensibilidad sin proponérselo lo detecta.
- **Tract para FPB-v2 estadística**: cuando haya infraestructura
  Monte Carlo, FPB-v2 puede heredar la API del reporte de FPB-v1 y
  añadir bounds teóricos.

### Negativas / costos

- **Sensible al N**: con cycles_total muy pequeño, fire_fraction es
  ruidoso (0/1, 1/1, etc.). FPB-v1 no aplica overflow protection ni
  smoothing — es responsibility del caller no establecer bounds
  apretados sobre MCAPs cortos.
- **No es una afirmación de safety**: el `holds` de FPB-v1 NO
  garantiza nada sobre el comportamiento del agente. Es una
  observación. Confundir uno por otro es bug del caller.
- **Sub-optimal naming**: "False Positive Bound" sin el modelo
  estadístico es un nombre que sugiere más de lo que entrega.
  Aceptable como nombre transitivo a FPB-v2 estadística.

## Alternatives considered

1. **Esperar a FPB estadística completa** — Monte Carlo + bound
   teórico. Rechazado: agrega complejidad significativa (Monte
   Carlo harness, statistical tests, validación de modelo probabilístico).
   FPB-v1 observacional entrega valor regression-gate inmediatamente.
2. **Renombrar FPB → "BAUD Fire Rate Observer" (BFRO)**. Rechazado:
   confuso, pierde la conexión con la propiedad estadística que
   queremos heredar en v2.
3. **No tener una quinta propiedad**. Considerado y rechazado: el
   conjunto de cuatro propiedades cualitativas no permite catch
   regresiones de sensibilidad. FPB es exactamente esa pieza.

## Implementation roadmap (informational)

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | done at acceptance |
| 2 | `src/project_ghost/properties/fpb.py` | 1 sesión |
| 3 | `tests/properties/test_verify_fpb_smoke.py` | 1 sesión |
| 4 | `tests/properties/test_fpb_property.py` | 1 sesión |
| 5 | `SmokeSummary.fpb_report` inline + CLI + integration test | 1 sesión |
| 6 | Lift ADR a Accepted | tras pasos 2-5 |

## References

- ADR-0026 — Closed-Loop Feedback v1 (`MahalanobisDowngradePolicy`)
- ADR-0031 — Bounded Action Under Drift Property v1 (precondition
  re-evaluated by FPB)
- ADR-0034 — Recovery Latency Bound (precedente cuantitativo)
