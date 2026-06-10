# ADR-0034 — Recovery Latency Bound Property v1 (RLB)

## Status

Accepted (2026-06-09).

## Context

ERUR-v1 (ADR-0032) afirma que cuando la condición *drift-clean* se
cumple AND `raw.overall_level == KNOWN`, el agente emite PROCEED. Es
*per-cycle*: dice qué pasa *cuando* las condiciones se cumplen, pero
no acota *cuándo* se cumplirán después de un evento de drift.

La pregunta cuantitativa abierta es: *¿cuántos ciclos pasan entre el
momento en que los outcomes vuelven a ser within_1_std y el momento
en que la condición drift-clean se cumple?*

Tres respuestas posibles desde la arquitectura actual:

1. **Calibrador stateless** — el reference `MahalanobisDowngradePolicy`
   no lleva state entre ciclos. Cuando se llama con una history nueva,
   la salida depende sólo de esa history. *Per se*, no hay
   "latencia de reactivación" — la salida cambia el mismo ciclo en
   que la entrada cambia.
2. **Ventana del builder** — la `CalibrationHistory` es producida por
   `build_calibration_history(outcomes, max_history=W)` (ADR-0026). La
   ventana `W` determina cuántos outcomes viejos siguen contando
   contra el K threshold. Si recientemente hubo `n` outcomes
   over-threshold, hace falta que entren `W - n + 1` outcomes nuevos
   within_1_std para que TODOS los viejos hayan salido de la ventana.
3. **Bound emergente** — la latencia entre "último outcome
   over-threshold" y "first cycle con `count_beyond_3+5 == 0`" está
   acotada superiormente por `W` cuando los outcomes siguientes son
   sostenidamente within_1_std.

RLB-v1 hace explícito y verificable el punto 3: *el gap está acotado
por la ventana W usada por el builder*.

Esto cierra una pregunta que el spec deja abierta y produce una
**afirmación cuantitativa** sobre el comportamiento del lazo bajo
recovery. Diferente naturaleza que BAUD (condicional sobre drift),
ERUR (condicional sobre clean), MD (estructural sobre raw vs
adjusted). RLB es *temporal y cuantitativa*.

## Decision

### 1. Property statement (RLB-v1)

Definiciones:

- `H_t` — `CalibrationHistory` snapshot consumido en el ciclo `t`.
- **Dirty cycle**: cycle `t` donde
  `H_t.count_beyond_3_std + H_t.count_beyond_5_std > 0`.
- **Clean cycle**: cycle `t` donde
  `H_t.count_beyond_3_std + H_t.count_beyond_5_std == 0`.
- **Recovery transition at t**: cycle `t` es clean AND el cycle
  inmediatamente anterior (por stamp ordering) es dirty.
- **Pre-recovery dirty run length L(t)**: para una recovery
  transition en `t`, el número máximo de cycles consecutivos dirty
  inmediatamente anteriores a `t`.

#### Property RLB-v1 (per-recovery transition)

> Sea una ejecución `E` de la closed-loop pipeline con la calibration
> policy de referencia configurada con `(M, K)` y la calibration
> history producida con `max_history=W`.
>
> Para **toda recovery transition** en el ciclo `t`:
>
> ```
> L(t) <= peak(t) + W - 1
> ```
>
> Donde `peak(t)` es el valor máximo observado de
> `H_s.count_beyond_3_std + H_s.count_beyond_5_std` en algún ciclo
> `s ∈ [t - L(t), t - 1]` del dirty run inmediatamente anterior.
>
> Equivalentemente: el número de ciclos dirty consecutivos antes de
> una recuperación está acotado por (la peak count de outcomes
> over-threshold dentro de la ventana durante ese dirty run) + W -
> 1. Si fuera mayor, significaría que el builder no está expulsando
> outcomes al ritmo esperado de uno-por-ciclo — sería un bug
> estructural.

#### Por qué L(t) <= peak(t) + W - 1 (justificación)

Considera un dirty run de `L(t)` ciclos consecutivos. Cada ciclo añade
UN outcome al buffer; cuando el buffer está lleno
(`outcomes_considered == W`), expulsa al más viejo. El builder es
estructuralmente un sliding window.

El peor caso para una recovery transition es:
1. Llegan `N` outcomes over-threshold consecutivos. El buffer acumula
   hasta `peak = min(N, W)` outcomes dirty. Ciclos dirty hasta aquí:
   `N` (si `N < W`) o `W` (si `N >= W`).
2. Empiezan a llegar within_1_std consecutivos. Por cada uno entra
   un clean y sale el más viejo. Si el más viejo es dirty, el count
   baja en 1; si no, queda igual.
3. Hacen falta `peak` within_1_std nuevos para flushar todos los
   dirty del buffer.

Total: ciclos dirty = (acumulación) + (flush) - 1 = N + peak - 1.
Con `peak <= W`, el bound se simplifica a `L(t) <= peak + W - 1`.

Por encima de ese bound, el builder no estaría expulsando uno por
ciclo — violación estructural.

#### Witness (verificación third-party)

El verificador RLB itera por ciclos chronologically, mantiene el
"running dirty count" (cuántos ciclos dirty consecutivos llevamos),
y en cada recovery transition compara contra W:

```
W = parameter passed by caller (defaults to smoke's max_history=32)
dirty_run = 0
for t in chronologically_sorted_cycles(mcap):
    H = read_calibration_history_at(mcap, t)
    is_clean = (H.count_beyond_3_std + H.count_beyond_5_std == 0)
    if is_clean:
        if dirty_run > 0:
            # recovery transition at this cycle
            assert dirty_run <= W
        dirty_run = 0
    else:
        dirty_run += 1
```

Reproducible byte-exacto (ADR-0030).

### 2. Scope — what RLB-v1 claims and does NOT claim

**RLB-v1 claims (v1):**

- Una cota cuantitativa sobre el número de ciclos dirty consecutivos
  antes de una recuperación.
- Verificación third-party byte-exacta desde el MCAP, parametrizada
  por `W`.

**RLB-v1 does NOT claim (v1):**

- **Que la recuperación SUCEDA**: si los outcomes nunca vuelven a ser
  within_1_std (sustained drift como el smoke), RLB no observa
  ninguna recovery transition y la propiedad se cumple vacuamente
  con `cycles_precondition_held == 0`.
- **Bound apretado**: el bound de `W` es worst-case. En la práctica,
  la recovery puede ser mucho más rápida — si los outcomes
  over-threshold están todos al final de la ventana, una sola
  iteración los limpia.
- **Independencia de W**: la propiedad es parametrizada por `W`. Si
  el caller pasa un W distinto al usado realmente por el builder,
  el bound es matemáticamente inválido para esa ejecución. La
  reference smoke usa `W=32`; el verifier accepts the value as
  parameter.
- **Aplicación bajo W no constante**: si la ejecución usa un W
  variable entre ciclos (no es el caso del reference smoke), RLB-v1
  no aplica. Una versión generalizada podría manejarlo pero queda
  fuera de scope.

### 3. Relación con BAUD-v1, ERUR-v1, MD-v1

RLB es **ortogonal a las tres anteriores y temporal**.

| Propiedad | Naturaleza | Multi-cycle? |
|---|---|---|
| BAUD-v1 (0031) | Condicional sobre drift | No, per-cycle |
| ERUR-v1 (0032) | Condicional sobre clean | No, per-cycle |
| MD-v1 (0033) | Incondicional estructural | No, per-cycle |
| **RLB-v1 (0034)** | **Cuantitativa temporal** | **Sí, multi-cycle** |

RLB es la primera propiedad multi-cycle del set. Su witness requiere
mantener state ligero entre ciclos (`dirty_run` counter). La
verificación sigue siendo deterministic byte-exact pero no es
puramente per-cycle.

### 4. Verification plan

#### 4.1 Verifier público (`src/project_ghost/properties/rlb.py`)

`verify_rlb(mcap_path, *, max_history=32) → RLBVerificationReport`.
Defaults match el smoke's wiring.

Reporte:

```python
@dataclass(frozen=True)
class RLBVerificationReport:
    mcap_sha256: str
    max_history: int             # W used
    property_version: str        # "RLB-v1"
    cycles_total: int
    cycles_precondition_held: int   # number of recovery transitions
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[RLBViolation, ...]

    @property
    def holds(self) -> bool: return len(self.violations) == 0
```

#### 4.2 Sanity tests (`tests/properties/test_verify_rlb_smoke.py`)

Sobre el smoke (sustained drift): NUNCA hay recovery transition →
`cycles_precondition_held == 0` → trivially holds. El test asserta
exactamente esa shape (vacuously true) para pinear el comportamiento
en sustained-drift baseline.

#### 4.3 Hypothesis property test (`tests/properties/test_rlb_property.py`)

Genera secuencias de outcomes con patrones que incluyen recovery
transitions: drift sostenido seguido de outcomes within_1_std.
Construye MCAPs multi-cycle (no single-cycle como BAUD/ERUR/MD).
Verifica `report.holds`.

#### 4.4 Inline en smoke

`SmokeSummary.rlb_report` inline. CLI imprime `RLB-v1: HOLDS`. En
el smoke el reporte es trivially-holding pero el field existe para
shape parity con las otras propiedades.

## Consequences

### Positivas

- **Primera propiedad cuantitativa temporal del set.** Las cuatro
  juntas (BAUD, ERUR, MD, RLB) cubren cuatro naturalezas distintas:
  condicional-drift, condicional-clean, estructural-per-cycle,
  cuantitativa-multi-cycle.
- **Cierra una pregunta abierta**: ERUR no decía cuándo, RLB sí dice
  cuánto.
- **Detector de bugs en el builder**: si `build_calibration_history`
  alguna vez se rompiese y dejara de expulsar outcomes viejos al
  ritmo esperado, RLB lo detectaría.

### Negativas / costos

- **Trivialmente satisfecha bajo el smoke actual**: el smoke usa
  sustained drift y nunca tiene recovery transition. RLB se cumple
  vacuamente. Como BAUD/ERUR, la cobertura fuerte vive en el
  property test.
- **Parámetro W expuesto**: el verifier requiere saber W. Si el
  caller pasa el valor equivocado, el resultado es matemáticamente
  inválido. Convención: defaults al W del smoke (32). Otras
  ejecuciones DEBEN pasar el W real.
- **Multi-cycle complejidad**: la primera propiedad de este set que
  no es per-cycle. Introduce un patrón distinto de iteración que
  futuras propiedades multi-cycle pueden reutilizar.

## Alternatives considered

1. **Zero-Latency Reactivation** — "el reference calibrator es
   stateless, así que reactivation es instantánea." Rechazado:
   instantáneo *given input*, pero el input mismo depende del builder.
   La latencia real está en el builder, no en el adjust.
2. **Bound apretado dependiente del patrón de outcomes** — "L(t) <=
   number of within_1_std outcomes consecutive desde el primer
   over-threshold." Más preciso pero menos citable. RLB-v1 sacrifica
   tightness por simplicidad de enunciado.
3. **Propiedad estadística sobre la distribución de L(t)** — "bajo
   ruido gaussiano, E[L(t)] <= alpha * W para algún alpha < 1."
   Requiere modelo probabilístico explícito; fuera de scope de v1.

## Implementation roadmap (informational, not binding)

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | done at acceptance |
| 2 | `src/project_ghost/properties/rlb.py` | 1 sesión |
| 3 | `tests/properties/test_verify_rlb_smoke.py` (trivial holding) | 1 sesión |
| 4 | `tests/properties/test_rlb_property.py` (multi-cycle Hypothesis) | 1 sesión |
| 5 | `SmokeSummary.rlb_report` inline + CLI prints `RLB-v1: HOLDS` | 1 sesión |
| 6 | Lift ADR a Accepted | tras pasos 2-5 |

## References

- ADR-0026 — Closed-Loop Feedback v1 (window mechanism `max_history`)
- ADR-0031 — Bounded Action Under Drift Property v1
- ADR-0032 — Eventual Reactivation Under Recovery Property v1
- ADR-0033 — Monotonic Degradation Property v1
- `src/project_ghost/core/feedback/orchestration.py` —
  `build_calibration_history` con su `max_history` param
