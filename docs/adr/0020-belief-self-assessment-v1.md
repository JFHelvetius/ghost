# ADR-0020 — Belief Self-Assessment v1

## Status
Accepted (2026-06-07).

## Context

Todos los ADRs de análisis (0016 / 0017 / 0018 / 0019) producen artefactos
que el **operador** lee para entender qué pasó con la creencia del
agente. Pero ninguno responde a la pregunta más directa de la misión:

> ¿Qué afirma **el agente** que sabe — y no sabe — en tiempo de ejecución?

Hasta ADR-0019 el sistema **mide** errores y covarianzas, los **audita**
post-hoc, los **compara** entre runs. En ningún momento el agente
**emite una afirmación estructurada** sobre el estado de su propio
conocimiento. La covarianza `15x15` que el estimador adjunta es una
matriz: información cruda, no una claim interpretable.

ADR-0020 corrige ese gap añadiendo una capa de **introspección runtime**:
para cada `VehicleState` que la creencia produzca, el agente puede
publicar — vía un componente puro y determinista — un
**`BeliefSelfAssessment`** que clasifica por-eje y por-bloque qué
afirma saber, con qué calidad, frente a qué umbrales explícitos
escogidos por el operador.

La clasificación es discreta y descriptiva:

- **KNOWN**: per-axis std declarado ≤ umbral "known".
- **UNCERTAIN**: per-axis std entre umbrales "known" y "unknown".
- **UNKNOWN**: per-axis std ≥ umbral "unknown", o covarianza ausente.

No hay inferencia probabilística. No hay scoring. No hay verdict de
"calibrado". El agente emite una clasificación rule-based contra
umbrales que el operador elige y que viajan con el assessment para que
toda lectura sea verificable y reproducible.

Este es el primer ADR que añade **un productor runtime** desde la línea
de misión (vs. los ADRs previos que añaden consumidores offline).

## Decision

Tres componentes nuevos, todos disciplinados al posture observacional
del proyecto:

### 1. Núcleo runtime: `core.uncertainty.self_assessment`

- `SelfAssessmentLevel` (StrEnum, cerrado): `"known"`, `"uncertain"`,
  `"unknown"`.
- `AssessmentThresholds` (frozen dataclass): los seis umbrales que el
  caller declara (`{position,velocity,orientation} × {known,unknown}_std`),
  validados (`> 0`, `known < unknown`).
- `BeliefSelfAssessment` (frozen dataclass): por-eje std declarado,
  por-eje level, por-bloque overall level, overall_level global, hash
  SHA-256 de los thresholds usados, copia del propio `AssessmentThresholds`
  para auto-contención auditable.
- `assess_belief(state, thresholds) -> BeliefSelfAssessment`: función
  pura. Cero clock, cero random, cero I/O. Si `state.nav.covariance_15x15`
  es `None`, todos los stds son `None` y todos los levels son `UNKNOWN` —
  el agente reconoce abiertamente que su belief carece de covarianza.

### 2. Plumbing telemetría

- `CHANNEL_SELF_ASSESSMENT = "/self_assessment"` en `telemetry.channels`.
- `SelfAssessmentToTelemetryAdapter` en `telemetry.adapters` — mismo
  patrón que `ModeEventToTelemetryAdapter`. Publica cada assessment
  usando `belief_stamp_sim_ns` como log_time (ADR-0002, sin reloj de
  pared).
- Decoder registrado en el catálogo cerrado de `telemetry.replay`.
  Replay produce instancias `BeliefSelfAssessment` reconstruidas con
  re-validación de invariantes.

### 3. Análisis offline: `analysis.self_assessment`

- `SelfAssessmentSummary` (frozen dataclass): conteo de records por
  level (KNOWN/UNCERTAIN/UNKNOWN) en cada bloque (position/velocity/
  orientation) y overall. Timestamp first/last/span. Cobertura
  temporal por level (qué fracción del run estuvo en cada level).
- `summarize_self_assessments(records) -> SelfAssessmentSummary`:
  función pura.
- `read_self_assessments_from_mcap(path) -> tuple[BeliefSelfAssessment,
  ...]`: lectura determinista de un MCAP capturado.
- CLI: `ghost analyze-self-assessment --mcap PATH [--output PATH]`.
  Lee `/self_assessment` del MCAP, decodea y emite el summary JSON
  canónico.

### Constantes versionadas

- `SELF_ASSESSMENT_PROTOCOL_VERSION: int = 1`
- `SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION: str = "1"`

### Lógica de clasificación (frozen)

Para cada eje cartesiano de cada bloque (position X/Y/Z, velocity X/Y/Z,
orientation tangent X/Y/Z):

1. Si `covariance_15x15 is None` o el std calculado no es finito → level
   = `UNKNOWN`, std = `None`.
2. Else `std_axis = sqrt(covariance[i, i])` para el índice de bloque
   correspondiente.
3. Si `std_axis ≤ threshold_known` → `KNOWN`.
4. Elif `std_axis ≥ threshold_unknown` → `UNKNOWN`.
5. Else → `UNCERTAIN`.

Para `block_overall_level` (e.g. `position_overall_level`):

- `max` (en el ordenamiento KNOWN(0) < UNCERTAIN(1) < UNKNOWN(2))
  sobre los tres axes del bloque. El bloque hereda el peor nivel de
  sus axes.

Para `overall_level` global:

- `max` sobre `position_overall_level`, `velocity_overall_level`,
  `orientation_overall_level`. Si cualquier bloque es UNKNOWN, el
  agente declara UNKNOWN en su conocimiento total.

### Block-to-covariance-index mapping

`covariance_15x15` tiene estructura por-bloque (cf. `NavigationState`
en ADR-0005):

- `[0:3]` posición ENU.
- `[3:6]` velocidad world.
- `[6:9]` orientación tangent (axis-angle).
- `[9:12]` accel bias.
- `[12:15]` gyro bias.

V1 audita los tres primeros bloques (los que tienen umbrales explícitos
en `AssessmentThresholds`). Accel/gyro biases NO se evalúan en V1 — su
exposición como dimensión separada queda diferida. Esto está documentado
en el ADR y reflejado en las pruebas.

### Self-contención auditable

Cada `BeliefSelfAssessment` contiene:

1. Los stds por-axis (los números crudos que se usaron).
2. Los levels por-axis y por-bloque (la clasificación que produjo).
3. `thresholds_used: AssessmentThresholds` (los umbrales completos
   inline).
4. `thresholds_sha256: str` (hash content-addressed de la
   `AssessmentThresholds` canónicamente serializada).

Un auditor que tenga sólo el assessment puede:

- Verificar bit-a-bit la clasificación re-aplicando las reglas.
- Verificar que `thresholds_sha256` matchea SHA-256 del JSON canónico
  de `thresholds_used` — provenance content-addressed.

## Inputs

- **Runtime**: un `VehicleState` (del estimador o del aggregator) + un
  `AssessmentThresholds` (escogido por el operador del experimento).
- **Análisis**: un MCAP que contenga records en el canal
  `/self_assessment`.

## Outputs

- `BeliefSelfAssessment` por cada `VehicleState` que el caller asese.
- Publicación opcional en `/self_assessment` vía adapter.
- `SelfAssessmentSummary` post-hoc por run.

## Limits

- **No retrocompatibilidad ascendente del enum.** Si un futuro ADR añade
  niveles intermedios (e.g. "low_confidence"), bump
  `SELF_ASSESSMENT_PROTOCOL_VERSION` y crea decodificador específico.
- **Per-axis std es marginal**, no principal. Para covarianzas con
  correlaciones cruzadas fuertes la per-axis std subestima la
  incertidumbre direccional. V1 acepta este trade-off por simplicidad y
  por alineación con thresholds per-axis del operador. Una extensión
  futura puede agregar análisis de eigenvalores.
- **Bloques biases (accel, gyro) NO se evalúan en V1.** Su umbral no
  está en `AssessmentThresholds`. Documentado y testeable.
- **Tie-breaking**: KNOWN vs UNCERTAIN frontera (`std == known_threshold`)
  resuelve hacia KNOWN. UNCERTAIN vs UNKNOWN frontera
  (`std == unknown_threshold`) resuelve hacia UNKNOWN. Estricta
  documentación de la convención.
- **Health/perception mode NO se integran en V1.** Sensor health
  degradado no fuerza UNKNOWN automáticamente. El operador debe
  combinar con `/perception/mode` por separado si quiere ese efecto.
- **Stale data NO se penaliza en V1.** Si un belief se publica con
  timestamp viejo, el assessment sólo refleja covarianza, no edad. Un
  ADR futuro puede agregar staleness explícitamente.

## Determinism

- `assess_belief` es función pura. Mismo `(state, thresholds)` → mismo
  `BeliefSelfAssessment` byte-a-byte tras serialización.
- `SelfAssessmentToTelemetryAdapter.publish` no lee reloj de pared.
- MCAP capture + replay → `BeliefSelfAssessment` reconstruido = original.
- `summarize_self_assessments` es función pura.
- SHA-256 de los thresholds usados es estable cross-CPython.

## Exclusiones explícitas

- **No ML / clustering / scoring.** Sólo reglas determinísticas
  contra umbrales explícitos.
- **No "el agente está bien calibrado".** El assessment **no** habla
  de calibración; ADR-0019 sí lo hace, y son artefactos disjuntos.
- **No detección de cambio de régimen.** El assessment es por-record
  estático. Cualquier comparación temporal vive en `analysis.*` o en
  el operador.
- **No control / actuación.** El assessment es un signal observacional.
  Nada en V1 lo conecta a comandos del actuador.
- **No agregación tipo NEES/NIS.** Mismo razonamiento que ADR-0019.
- **No "uncertainty budget" o "remaining confidence".** Solo levels
  discretos.

## Determinism guarantees verificables

| # | Invariante | Verificación |
|---|---|---|
| 1 | `assess_belief(s, t) == assess_belief(s, t)` byte-a-byte tras encode | Test directo. |
| 2 | covariance None → todos los stds None, todos los levels UNKNOWN | Test. |
| 3 | covariance diagonal con std = known_threshold → todos los levels KNOWN | Test (frontera). |
| 4 | covariance diagonal con std = unknown_threshold → todos los levels UNKNOWN | Test (frontera). |
| 5 | `assess_belief(s, t).thresholds_sha256 == sha256(json(t))` | Test. |
| 6 | `assess_belief(s, t).thresholds_used == t` | Test. |
| 7 | `block_overall_level = max(axis_x, axis_y, axis_z)` en ordenamiento KNOWN < UNCERTAIN < UNKNOWN | Test sobre casos mixtos. |
| 8 | `overall_level = max(position_overall, velocity_overall, orientation_overall)` | Test. |
| 9 | `AssessmentThresholds(known >= unknown)` raises ValueError | Test. |
| 10 | `AssessmentThresholds(*_std <= 0)` raises ValueError | Test. |
| 11 | Adapter publica con `belief_stamp_sim_ns` como log_time | Test sobre InMemorySink. |
| 12 | Round-trip MCAP: write N assessments → read → reconstrucción byte-equal | Test. |
| 13 | `summarize_self_assessments([]) → counts all zero` | Test. |
| 14 | `summarize` cuenta levels correctamente | Test. |
| 15 | CLI smoke: mcap con N records → JSON con N en total_records | Test. |
| 16 | Cross-process SHA-256 estabilidad sobre summary final | Test/Script. |

## Consecuencias

**Positivo.**

- Por primera vez el agente **emite** una afirmación estructurada sobre
  su propio conocimiento. La línea entre "el operador analiza" y "el
  agente reporta" se cruza.
- Cualquier capa futura de decisión (autonomy tiers de ADR-0009)
  puede consumir `/self_assessment` directamente sin re-implementar
  la lógica de clasificación.
- El assessment es **content-addressed** vía `thresholds_sha256`: un
  cambio de umbrales produce un assessment trivialmente distinguible.
- El channel `/self_assessment` es un nuevo canal MCAP estándar
  reproducible / analizable / comparable con todo el toolchain ADR-0013
  / 0017 / 0018.
- Operadores pueden ejecutar experimentos del tipo "¿qué fracción del
  run el agente cree que es KNOWN bajo umbrales X?" sin escribir código.

**Negativo.**

- Aumenta el espacio MCAP por record (~200 bytes / assessment).
  Aceptable; los assessments se publican por step de belief, no por
  step de sensor.
- El operador ahora elige umbrales — una decisión que tiene
  consecuencias. La cláusula de honestidad del ADR exige que los
  umbrales viajen con el assessment para que la decisión sea
  reproducible.
- Acopla `core.uncertainty` al concepto de "level" que es nuevo. Mismo
  module ya tenía `PerceptionMode` (enum cerrado), `Validity` (ladder),
  etc. La adición es coherente.

## Alternativas consideradas

1. **Levels continuos en `[0, 1]`** (e.g. confidence score). Rechazado:
   re-introduce scoring/heurística. Niveles discretos son auditables y
   no exigen tolerancia.
2. **Integrar perception mode / sensor health en el assessment.**
   Rechazado v1: agrega dimensiones y dependencias antes de que esté
   probada la dimensión más simple (covarianza). Diferido.
3. **Publicar covarianza completa en el assessment.** Rechazado: el
   assessment es una *afirmación clasificatoria*, no una réplica de la
   matriz. La matriz vive en `VehicleState.nav.covariance_15x15` y se
   publica en `/state/nav` aparte.
4. **Un comparativo N-vía entre assessments de runs distintos.** Mismo
   patrón que ADR-0018, pero diferido a v2 — primero ganamos
   experiencia con la primitiva.
5. **Hacer assess automático dentro de `NoisyGroundTruthEstimator`.**
   Rechazado: violaría ADR-0015 (no modificar) y acoplaría productores
   con introspección. El caller wiring decide qué componer.

## Backward compatibility

- ADR-0013, 0014, 0015, 0016, 0017, 0018, 0019 sin tocar.
- `telemetry.channels` añade un canal nuevo (canal previo intactos).
- `telemetry.adapters` añade una clase (clases previas intactas).
- `telemetry.replay` añade una entrada al catálogo cerrado del decoder
  (entradas previas intactas). Compatible con MCAPs ya escritos
  porque el decoder sólo se invoca cuando aparece el nuevo `schema_name`.
- `core.uncertainty.__init__` añade re-exports nuevos.
- `cli.py` añade un subcomando nuevo.

Cero rotura.

## Mission posture

Es el primer ADR que añade un **productor runtime de introspección**.
Hasta ahora el agente no decía nada sobre sí mismo en tiempo de
ejecución — sólo dejaba evidencia para que el operador la juzgara
offline. Ahora el agente publica una **afirmación clasificatoria**
verificable, contenida, comparable, replayable, auditable.

Este es el primer paso concreto hacia el agente que, en palabras de la
misión, **sabe cuándo no sabe** — y, además, lo dice.
